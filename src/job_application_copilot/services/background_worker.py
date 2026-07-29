"""Sequential local worker for durable background tasks."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable, Mapping
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
from job_application_copilot.repositories.background_task_repository import BackgroundTaskRepository
from job_application_copilot.repositories.models import BackgroundTask
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.local_directories import ensure_local_directories

DEFAULT_IDLE_POLL_INTERVAL_SECONDS = 60.0
STOP_CHECK_INTERVAL_SECONDS = 1.0

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
    """Run registered task handlers sequentially outside Streamlit execution."""

    def __init__(
        self,
        database: Database,
        handlers: Mapping[BackgroundOperation, BackgroundTaskHandler],
        *,
        idle_poll_interval_seconds: float = DEFAULT_IDLE_POLL_INTERVAL_SECONDS,
        stop_requested: Callable[[], bool] | None = None,
        lease: BackgroundWorkerLease | None = None,
    ) -> None:
        if idle_poll_interval_seconds <= 0:
            raise ValueError("idle_poll_interval_seconds must be greater than zero.")
        self.database = database
        self.handlers = dict(handlers)
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
            while not self._should_stop():
                self._heartbeat()
                processed = self.process_next_task()
                if not processed:
                    self._wait_for_next_poll()
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
        return True

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
    worker = BackgroundWorker(
        database,
        handlers={},
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
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_process_id(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return 0


if __name__ == "__main__":
    main()
