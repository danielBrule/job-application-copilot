"""Stable semantic error categories shared across application boundaries."""


class ApplicationError(Exception):
    """Base class for expected application failures."""


class ApplicationValidationError(ApplicationError, ValueError):
    """A caller supplied an invalid value or requested a disallowed transition."""


class ApplicationNotFoundError(ApplicationError, LookupError):
    """A requested local domain object does not exist."""


class ApplicationOperationError(ApplicationError, RuntimeError):
    """An expected application operation could not complete."""


class ApplicationStorageError(ApplicationOperationError):
    """Local persistence or private-file storage could not complete safely."""


class ApplicationIntegrityError(ApplicationOperationError):
    """Persisted content no longer satisfies its recorded invariants."""


class ExternalServiceError(ApplicationOperationError):
    """An explicit external-service workflow could not complete."""
