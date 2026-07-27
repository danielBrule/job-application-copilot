"""Shared lifecycle for mutually exclusive OpenAI reference-asset operations."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Lock

from job_application_copilot.config import AppSettings
from job_application_copilot.llm import OpenAIClient, OpenAIConfigurationError

REMOTE_OPERATION_BUSY_MESSAGE = (
    "Another OpenAI reference-asset operation is already running. Wait for it to finish."
)

OpenAIClientFactory = Callable[[AppSettings], OpenAIClient]
WorkflowErrorFactory = Callable[[str], RuntimeError]

_REMOTE_REFERENCE_OPERATION_LOCK = Lock()


class RemoteReferenceOperation:
    """Lazily own one workflow client while the process-local guard is held."""

    def __init__(
        self,
        settings: AppSettings,
        client_factory: OpenAIClientFactory,
        error_factory: WorkflowErrorFactory,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._error_factory = error_factory
        self._client: OpenAIClient | None = None

    @property
    def client(self) -> OpenAIClient:
        """Create the workflow client on first use and translate configuration failures."""

        if self._client is None:
            try:
                self._client = self._client_factory(self._settings)
            except OpenAIConfigurationError as error:
                raise self._error_factory(str(error)) from error
        return self._client

    def close(self) -> None:
        """Close a created client at most once; do nothing when it was never needed."""

        client, self._client = self._client, None
        if client is not None:
            client.close()


@contextmanager
def remote_reference_operation(
    settings: AppSettings,
    client_factory: OpenAIClientFactory,
    error_factory: WorkflowErrorFactory,
) -> Iterator[RemoteReferenceOperation]:
    """Guard one remote workflow and always release its client and process lock."""

    if not _REMOTE_REFERENCE_OPERATION_LOCK.acquire(blocking=False):
        raise error_factory(REMOTE_OPERATION_BUSY_MESSAGE)

    operation = RemoteReferenceOperation(settings, client_factory, error_factory)
    try:
        yield operation
    finally:
        try:
            operation.close()
        finally:
            _REMOTE_REFERENCE_OPERATION_LOCK.release()
