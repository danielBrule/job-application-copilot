"""Process-local guard for mutually exclusive remote reference-asset operations."""

from threading import Lock

_REMOTE_REFERENCE_OPERATION_LOCK = Lock()


def try_acquire_remote_reference_operation() -> bool:
    """Claim remote reference-asset work without blocking the UI process."""

    return _REMOTE_REFERENCE_OPERATION_LOCK.acquire(blocking=False)


def release_remote_reference_operation() -> None:
    """Release the current process's remote reference-asset claim."""

    _REMOTE_REFERENCE_OPERATION_LOCK.release()
