"""Sequential local worker for durable background tasks."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from job_application_copilot.config import load_settings
from job_application_copilot.domain import BackgroundOperation, BackgroundTaskStatus
from job_application_copilot.errors import ApplicationOperationError
from job_application_copilot.observability import (
    LogComponent,
    configure_logging,
    get_logger,
    log_event,
)
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.background_task_repository import (
    BackgroundBatchRepository,
    BackgroundTaskRepository,
)
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask
from job_application_copilot.services.background_task_recovery import (
    BackgroundTaskRecoveryService,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.default_assessment_prompt import (
    DefaultAssessmentPromptService,
)
from job_application_copilot.services.local_directories import ensure_local_directories

_IS_WINDOWS = os.name == "nt"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5

DEFAULT_IDLE_POLL_INTERVAL_SECONDS = 60.0
STOP_CHECK_INTERVAL_SECONDS = 1.0
MAX_WORKER_COUNT = 5

BackgroundTaskHandler = Callable[[BackgroundTask], None]
logger = get_logger("job_application_copilot.services.background_worker")


class BackgroundWorkerAlreadyRunningError(ApplicationOperationError):
    """Raised when a live local worker already owns the private worker lease."""

    def __init__(self, process_id: int) -> None:
        self.process_id = process_id
        super().__init__(f"Background worker is already running with process ID {process_id}.")


@dataclass(frozen=True, slots=True)
class BackgroundWorkerLeaseMetadata:
    """Private metadata used to identify the single active local worker."""

    process_id: int
    token: str
    started_at: str
    heartbeat_at: str


class BackgroundWorkerLease:
    """A crash-tolerant private file lease that permits one live worker process."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.token = uuid.uuid4().hex
        self._acquired = False
        self._started_at: str | None = None

    def acquire(self) -> None:
        """Atomically acquire the lease or reject a worker that is already alive."""

        while True:
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                self._remove_stale_lease()
                continue

            self._started_at = _utc_timestamp()
            metadata = self._metadata()
            with os.fdopen(descriptor, "w", encoding="utf-8") as lease_file:
                lease_file.write(_serialize_metadata(metadata))
            self._acquired = True
            return

    def heartbeat(self) -> None:
        """Atomically refresh the lease heartbeat while this worker remains active."""

        if not self._acquired:
            return
        _write_metadata(self.path, self._metadata())

    def release(self) -> None:
        """Remove the lease only when it is still owned by this worker instance."""

        if not self._acquired:
            return
        metadata = _read_metadata(self.path)
        if metadata is not None and metadata.token == self.token:
            self.path.unlink(missing_ok=True)
        self._acquired = False

    def _remove_stale_lease(self) -> None:
        cleanup_path = self.path.with_name(f"{self.path.name}.cleanup")
        while True:
            try:
                descriptor = os.open(cleanup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _process_is_alive(_read_process_id(cleanup_path)):
                    time.sleep(0.05)
                else:
                    cleanup_path.unlink(missing_ok=True)
                continue
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as cleanup_file:
                    cleanup_file.write(str(os.getpid()))
                break

        try:
            metadata = _read_metadata(self.path)
            if metadata is not None and _process_is_alive(metadata.process_id):
                raise BackgroundWorkerAlreadyRunningError(metadata.process_id)
            self.path.unlink(missing_ok=True)
        finally:
            cleanup_path.unlink(missing_ok=True)

    def _metadata(self) -> BackgroundWorkerLeaseMetadata:
        started_at = self._started_at
        if started_at is None:
            raise RuntimeError("Cannot write a worker lease before it has started.")
        return BackgroundWorkerLeaseMetadata(
            process_id=os.getpid(),
            token=self.token,
            started_at=started_at,
            heartbeat_at=_utc_timestamp(),
        )


class BackgroundWorker:
    """Run one batch at a time with bounded parallel tasks outside Streamlit."""

    def __init__(
        self,
        database: Database,
        handlers: Mapping[BackgroundOperation, BackgroundTaskHandler],
        *,
        worker_counts: Mapping[BackgroundOperation, int] | None = None,
        idle_poll_interval_seconds: float = DEFAULT_IDLE_POLL_INTERVAL_SECONDS,
        stop_requested: Callable[[], bool] | None = None,
        lease: BackgroundWorkerLease | None = None,
    ) -> None:
        if idle_poll_interval_seconds <= 0:
            raise ValueError("idle_poll_interval_seconds must be greater than zero.")
        self.database = database
        self.handlers = dict(handlers)
        self.worker_counts = _validated_worker_counts(self.handlers, worker_counts)
        self.idle_poll_interval_seconds = idle_poll_interval_seconds
        self.stop_requested = stop_requested or (lambda: False)
        self.lease = lease
        self._stop_event = Event()

    def request_stop(self) -> None:
        """Request shutdown after the handler currently in progress returns."""

        self._stop_event.set()

    def run(self) -> None:
        """Process tasks until a local or external clean shutdown is requested."""

        if self.lease is not None:
            self.lease.acquire()
        try:
            log_event(logger, logging.INFO, "background_worker_started")
            recovered_task_ids = BackgroundTaskRecoveryService(
                self.database
            ).recover_abandoned_tasks()
            if recovered_task_ids:
                log_event(
                    logger,
                    logging.WARNING,
                    "background_tasks_interrupted_after_worker_restart",
                    recovered_task_count=len(recovered_task_ids),
                    recovered_task_ids=list(recovered_task_ids),
                )
            self._run_batches()
        finally:
            log_event(logger, logging.INFO, "background_worker_stopped")
            if self.lease is not None:
                self.lease.release()

    def process_next_task(self) -> bool:
        """Claim and process one task, returning false when no registered work is pending."""

        with self.database.session() as session:
            task = BackgroundTaskRepository(session).claim_next_pending(self.handlers)
        if task is None:
            return False

        self._process_claimed_task(task)
        return True

    def _run_batches(self) -> None:
        """Run one selected batch at a time until shutdown is requested."""

        with ThreadPoolExecutor(
            max_workers=max(self.worker_counts.values(), default=1)
        ) as executor:
            active_batch_id: int | None = None
            active_worker_count = 0
            futures: set[Future[None]] = set()
            while True:
                self._heartbeat()
                futures = {future for future in futures if not future.done()}

                if self._should_stop():
                    if not futures:
                        return
                    self._wait_for_futures(futures)
                    continue

                if active_batch_id is None:
                    active_batch = self._next_pending_batch()
                    if active_batch is None:
                        self._wait_for_next_poll()
                        continue
                    active_batch_id = active_batch.id
                    active_worker_count = self.worker_counts[active_batch.operation]

                while len(futures) < active_worker_count and not self._should_stop():
                    task = self._claim_next_task_in_batch(active_batch_id)
                    if task is None:
                        break
                    futures.add(executor.submit(self._process_claimed_task, task))

                if futures:
                    self._wait_for_futures(futures)
                    continue

                # This batch has no pending or running tasks, so choose the next one.
                active_batch_id = None
                active_worker_count = 0

    def _next_pending_batch(self) -> BackgroundBatch | None:
        with self.database.session() as session:
            return BackgroundBatchRepository(session).next_pending_for_operations(self.handlers)

    def _claim_next_task_in_batch(self, batch_id: int) -> BackgroundTask | None:
        with self.database.session() as session:
            return BackgroundTaskRepository(session).claim_next_pending_in_batch(batch_id)

    def _process_claimed_task(self, task: BackgroundTask) -> None:
        """Run one detached task and record its terminal lifecycle state."""

        handler = self.handlers[task.operation]
        log_event(
            logger,
            logging.INFO,
            "background_task_started",
            operation=task.operation.value,
            task_id=task.id,
        )
        try:
            handler(task)
        except Exception as error:
            logger.exception(
                "background_task_handler_failed task_id=%s operation=%s exception_type=%s",
                task.id,
                task.operation.value,
                type(error).__name__,
            )
            with self.database.session() as session:
                stored_task = BackgroundTaskRepository(session).require(task.id)
                BackgroundTaskRepository(session).transition(
                    stored_task,
                    BackgroundTaskStatus.FAILED,
                    error_message="Task handler failed; see the private worker log.",
                )
            log_event(
                logger,
                logging.WARNING,
                "background_task_failed",
                operation=task.operation.value,
                task_id=task.id,
            )
        else:
            with self.database.session() as session:
                stored_task = BackgroundTaskRepository(session).require(task.id)
                BackgroundTaskRepository(session).transition(
                    stored_task,
                    BackgroundTaskStatus.COMPLETED,
                )
            log_event(
                logger,
                logging.INFO,
                "background_task_completed",
                operation=task.operation.value,
                task_id=task.id,
            )

    def _wait_for_futures(self, futures: set[Future[None]]) -> None:
        """Wait briefly for running work while refreshing the worker lease."""

        wait(futures, timeout=STOP_CHECK_INTERVAL_SECONDS)

    def _should_stop(self) -> bool:
        return self._stop_event.is_set() or self.stop_requested()

    def _wait_for_next_poll(self) -> None:
        """Wait for the next database poll while checking an external stop request promptly."""

        elapsed = 0.0
        while elapsed < self.idle_poll_interval_seconds and not self._should_stop():
            wait_seconds = min(
                STOP_CHECK_INTERVAL_SECONDS, self.idle_poll_interval_seconds - elapsed
            )
            self._stop_event.wait(wait_seconds)
            elapsed += wait_seconds
            self._heartbeat()

    def _heartbeat(self) -> None:
        if self.lease is not None:
            self.lease.heartbeat()


def main() -> None:
    """Run the local worker process with no production handlers until later pipeline tickets."""

    arguments = _parse_arguments()
    settings = load_settings()
    ensure_local_directories(settings)
    configure_logging(settings, LogComponent.WORKER)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    DefaultAssessmentPromptService(database, settings).ensure()
    worker = BackgroundWorker(
        database,
        handlers={},
        worker_counts={
            BackgroundOperation.ASSESSMENT: settings.assessment_worker_count,
            BackgroundOperation.CV_GENERATION: settings.cv_worker_count,
        },
        stop_requested=lambda: arguments.stop_file is not None and arguments.stop_file.exists(),
        lease=BackgroundWorkerLease(settings.logs_folder / "worker.lock"),
    )
    _install_shutdown_handlers(worker)
    try:
        try:
            worker.run()
        except BackgroundWorkerAlreadyRunningError as error:
            log_event(
                logger,
                logging.WARNING,
                "background_worker_already_running",
                process_id=error.process_id,
            )
            raise SystemExit(str(error)) from error
    finally:
        database.dispose()


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local background worker.")
    parser.add_argument(
        "--stop-file",
        type=Path,
        help="Private launcher-created file that requests a clean worker shutdown.",
    )
    return parser.parse_args()


def _install_shutdown_handlers(worker: BackgroundWorker) -> None:
    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        worker.request_stop()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _serialize_metadata(metadata: BackgroundWorkerLeaseMetadata) -> str:
    return json.dumps(
        {
            "heartbeat_at": metadata.heartbeat_at,
            "process_id": metadata.process_id,
            "started_at": metadata.started_at,
            "token": metadata.token,
        },
        sort_keys=True,
    )


def _write_metadata(path: Path, metadata: BackgroundWorkerLeaseMetadata) -> None:
    temporary_path = path.with_name(f"{path.name}.{metadata.token}.tmp")
    temporary_path.write_text(_serialize_metadata(metadata), encoding="utf-8")
    temporary_path.replace(path)


def _read_metadata(path: Path) -> BackgroundWorkerLeaseMetadata | None:
    try:
        raw_metadata = json.loads(path.read_text(encoding="utf-8"))
        return BackgroundWorkerLeaseMetadata(
            process_id=int(raw_metadata["process_id"]),
            token=str(raw_metadata["token"]),
            started_at=str(raw_metadata["started_at"]),
            heartbeat_at=str(raw_metadata["heartbeat_at"]),
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _process_is_alive(process_id: int) -> bool:
    if process_id <= 0:
        return False
    if _IS_WINDOWS:
        return _windows_process_is_alive(process_id)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_is_alive(process_id: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    open_process.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int

    handle = open_process(_PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if handle:
        close_handle(handle)
        return True
    return ctypes.get_last_error() == _ERROR_ACCESS_DENIED


def _read_process_id(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return 0


def _validated_worker_counts(
    handlers: Mapping[BackgroundOperation, BackgroundTaskHandler],
    worker_counts: Mapping[BackgroundOperation, int] | None,
) -> dict[BackgroundOperation, int]:
    """Return bounded per-operation counts, defaulting registered handlers to one."""

    configured = dict(worker_counts or {})
    counts: dict[BackgroundOperation, int] = {}
    for operation in handlers:
        count = configured.get(operation, 1)
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 1 <= count <= MAX_WORKER_COUNT
        ):
            raise ValueError(
                f"Worker count for {operation.value} must be an integer between 1 and "
                f"{MAX_WORKER_COUNT}."
            )
        counts[operation] = count
    return counts


if __name__ == "__main__":
    main()
