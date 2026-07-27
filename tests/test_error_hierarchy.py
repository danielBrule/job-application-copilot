"""Tests for stable semantic application-error categories."""

from job_application_copilot.errors import (
    ApplicationError,
    ApplicationIntegrityError,
    ApplicationNotFoundError,
    ApplicationStorageError,
    ApplicationValidationError,
    ExternalServiceError,
)
from job_application_copilot.repositories import JobNotFoundError
from job_application_copilot.services import (
    DocumentAProcessingError,
    DuplicateJobUrlError,
    PromptStorageError,
    ReferenceAssetIntegrityError,
    ReferenceAssetValidationError,
)


def test_existing_errors_expose_semantic_categories() -> None:
    assert isinstance(DuplicateJobUrlError(1), ApplicationValidationError)
    assert isinstance(ReferenceAssetValidationError("invalid"), ApplicationValidationError)
    assert isinstance(JobNotFoundError(1), ApplicationNotFoundError)
    assert isinstance(PromptStorageError("unavailable"), ApplicationStorageError)
    assert isinstance(ReferenceAssetIntegrityError("changed"), ApplicationIntegrityError)
    assert isinstance(DocumentAProcessingError("unavailable"), ExternalServiceError)


def test_semantic_categories_preserve_existing_builtin_compatibility() -> None:
    assert isinstance(DuplicateJobUrlError(1), ValueError)
    assert isinstance(JobNotFoundError(1), LookupError)
    assert isinstance(PromptStorageError("unavailable"), RuntimeError)
    assert isinstance(DocumentAProcessingError("unavailable"), RuntimeError)


def test_all_semantic_categories_share_application_error_base() -> None:
    errors = (
        ApplicationValidationError("invalid"),
        ApplicationNotFoundError("missing"),
        ApplicationStorageError("unavailable"),
        ApplicationIntegrityError("changed"),
        ExternalServiceError("unavailable"),
    )

    assert all(isinstance(error, ApplicationError) for error in errors)
