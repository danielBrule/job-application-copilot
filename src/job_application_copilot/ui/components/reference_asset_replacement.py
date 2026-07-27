"""Settings component for validated local DOCX replacement."""

from typing import Protocol

import streamlit as st

from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    REQUIRED_REFERENCE_ASSETS,
    FrenchReferenceExamplesOverview,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
    ReferenceAssetVersionSummary,
    RequiredReferenceAsset,
)
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.services import (
    DocumentBProcessingError,
    ReferenceAssetStorageError,
    ReferenceAssetStorageService,
    ReferenceExampleNotFoundError,
)

logger = get_logger(__name__)
REPLACEMENT_SUCCESS_KEY = "reference_asset_replacement_success"
REPLACEMENT_ERROR_KEY = "reference_asset_replacement_error"
REPLACEMENT_ERROR_MESSAGE = "The reference asset could not be stored. See the private UI log."


class UploadedDocx(Protocol):
    """Small boundary shared by Streamlit uploads and focused tests."""

    name: str

    def getvalue(self) -> bytes:
        """Return the complete uploaded content."""


class DocumentBReplacementProcessor(Protocol):
    """Boundary for the combined Document B replacement workflow."""

    def replace_and_process(self, *, filename: str, content: bytes) -> ReferenceAsset:
        """Store, process, validate, and activate a Document B replacement."""


def render_reference_asset_replacements(
    service: ReferenceAssetStorageService,
    french_examples: FrenchReferenceExamplesOverview | None,
    document_b_processor: DocumentBReplacementProcessor,
    *,
    document_b_exists: bool,
) -> None:
    """Render canonical replacement controls and dynamic French-example input."""

    st.subheader("Local DOCX uploads")
    st.caption(
        "Templates and French examples become active after local validation. "
        "Document A remains pending until its later OpenAI processing succeeds. "
        "Document B is stored, processed with OpenAI and activated in one explicit workflow. "
        "Earlier local versions are retained."
    )
    if message := st.session_state.pop(REPLACEMENT_SUCCESS_KEY, None):
        st.success(message)
    if message := st.session_state.pop(REPLACEMENT_ERROR_KEY, None):
        st.error(message)

    for requirement in REQUIRED_REFERENCE_ASSETS:
        _render_required_asset_form(
            service,
            requirement,
            document_b_processor,
            document_b_exists=document_b_exists,
        )
    _render_french_example_form(service, french_examples)


def _render_required_asset_form(
    service: ReferenceAssetStorageService,
    requirement: RequiredReferenceAsset,
    document_b_processor: DocumentBReplacementProcessor,
    *,
    document_b_exists: bool,
) -> None:
    with st.expander(f"Upload or replace {requirement.label}"):
        with st.form(
            f"replace_reference_asset_{requirement.asset_key}",
            clear_on_submit=True,
        ):
            upload = st.file_uploader(
                f"{requirement.label} DOCX",
                type=["docx"],
                key=f"reference_asset_file_{requirement.asset_key}",
            )
            if requirement.asset_key == DOCUMENT_B_KEY:
                st.caption(
                    "Validates and stores the file locally, uploads it to OpenAI, verifies its "
                    "vector store, then activates it. The current version remains active if "
                    "processing fails."
                )
            submitted = st.form_submit_button(
                _required_asset_submit_label(
                    requirement,
                    document_b_exists=document_b_exists,
                )
            )

        if submitted:
            if requirement.asset_key == DOCUMENT_B_KEY:
                _replace_and_process_document_b(
                    document_b_processor,
                    upload=upload,
                )
            else:
                _replace_uploaded_asset(
                    service,
                    upload=upload,
                    asset_key=requirement.asset_key,
                    asset_type=requirement.asset_type,
                    name=requirement.label,
                    language_code=requirement.language_code,
                )


def _required_asset_submit_label(
    requirement: RequiredReferenceAsset,
    *,
    document_b_exists: bool,
) -> str:
    if requirement.asset_key != DOCUMENT_B_KEY:
        return "Validate and store"
    return (
        "Replace and activate with OpenAI"
        if document_b_exists
        else "Upload and activate with OpenAI"
    )


def _render_french_example_form(
    service: ReferenceAssetStorageService,
    french_examples: FrenchReferenceExamplesOverview | None,
) -> None:
    with st.expander("Manage French CV examples"):
        st.caption(
            "The name identifies the example. Reuse the same name with changed content "
            "to create its next version."
        )
        with st.form("replace_french_reference_example", clear_on_submit=True):
            name = st.text_input("Example name")
            upload = st.file_uploader(
                "French CV example DOCX",
                type=["docx"],
                key="reference_asset_file_french_example",
            )
            submitted = st.form_submit_button("Validate and store")

        if submitted:
            _replace_french_example(
                service,
                upload=upload,
                name=name,
            )

        if french_examples is None:
            return

        st.divider()
        _render_active_french_examples(service, french_examples.active_versions)
        _render_removed_french_examples(service, french_examples.removed_versions)


def _render_active_french_examples(
    service: ReferenceAssetStorageService,
    examples: tuple[ReferenceAssetVersionSummary, ...],
) -> None:
    if not examples:
        st.caption("No active French examples.")
        return

    selected_key = st.selectbox(
        "Active example",
        options=[example.asset_key for example in examples],
        format_func=lambda asset_key: _example_label(examples, asset_key),
        key="active_french_example",
    )
    if st.button(
        "Remove from active examples",
        key="remove_french_example",
    ):
        _change_french_example_state(
            service,
            asset_key=selected_key,
            restore=False,
        )


def _render_removed_french_examples(
    service: ReferenceAssetStorageService,
    examples: tuple[ReferenceAssetVersionSummary, ...],
) -> None:
    if not examples:
        return

    selected_key = st.selectbox(
        "Removed example",
        options=[example.asset_key for example in examples],
        format_func=lambda asset_key: _example_label(examples, asset_key),
        key="removed_french_example",
    )
    if st.button("Restore example", key="restore_french_example"):
        _change_french_example_state(
            service,
            asset_key=selected_key,
            restore=True,
        )


def _replace_french_example(
    service: ReferenceAssetStorageService,
    *,
    upload: UploadedDocx | None,
    name: str,
) -> None:
    if upload is None:
        st.error("Choose a DOCX file.")
        return

    try:
        asset = service.replace_french_example(
            filename=upload.name,
            content=upload.getvalue(),
            name=name,
        )
    except (ReferenceAssetStorageError, ValueError) as error:
        st.error(str(error))
    except Exception:
        logger.exception("french_reference_example_replacement_failed name=%s", name)
        st.error(REPLACEMENT_ERROR_MESSAGE)
    else:
        st.session_state[REPLACEMENT_SUCCESS_KEY] = _success_message(asset)
        st.rerun()


def _change_french_example_state(
    service: ReferenceAssetStorageService,
    *,
    asset_key: str,
    restore: bool,
) -> None:
    try:
        asset = (
            service.restore_french_example(asset_key)
            if restore
            else service.remove_french_example(asset_key)
        )
    except ReferenceExampleNotFoundError as error:
        st.error(str(error))
    except Exception:
        logger.exception(
            "french_reference_example_state_change_failed asset_key=%s restore=%s",
            asset_key,
            restore,
        )
        st.error(REPLACEMENT_ERROR_MESSAGE)
    else:
        action = "restored" if restore else "removed from active examples"
        st.session_state[REPLACEMENT_SUCCESS_KEY] = (
            f"'{asset.name}' version {asset.version} was {action}."
        )
        st.rerun()


def _example_label(
    examples: tuple[ReferenceAssetVersionSummary, ...],
    asset_key: str,
) -> str:
    example = next(example for example in examples if example.asset_key == asset_key)
    return f"{example.name} (v{example.version})"


def _replace_uploaded_asset(
    service: ReferenceAssetStorageService,
    *,
    upload: UploadedDocx | None,
    asset_key: str,
    asset_type: ReferenceAssetType,
    name: str,
    language_code: str | None,
) -> None:
    if upload is None:
        st.error("Choose a DOCX file.")
        return

    try:
        asset = service.replace(
            filename=upload.name,
            content=upload.getvalue(),
            asset_key=asset_key,
            asset_type=asset_type,
            name=name,
            language_code=language_code,
        )
    except (ReferenceAssetStorageError, ValueError) as error:
        st.error(str(error))
    except Exception:
        logger.exception(
            "reference_asset_replacement_failed asset_key=%s asset_type=%s",
            asset_key,
            asset_type.value,
        )
        st.error(REPLACEMENT_ERROR_MESSAGE)
    else:
        st.session_state[REPLACEMENT_SUCCESS_KEY] = _success_message(asset)
        st.rerun()


def _replace_and_process_document_b(
    service: DocumentBReplacementProcessor,
    *,
    upload: UploadedDocx | None,
) -> None:
    if upload is None:
        st.error("Choose a DOCX file.")
        return

    try:
        with st.spinner("Validating, uploading and activating Document B with OpenAI..."):
            asset = service.replace_and_process(
                filename=upload.name,
                content=upload.getvalue(),
            )
    except (ReferenceAssetStorageError, ValueError) as error:
        st.error(str(error))
    except DocumentBProcessingError as error:
        st.session_state[REPLACEMENT_ERROR_KEY] = (
            f"Document B could not be activated: {error} "
            "Any existing active version remains in use."
        )
        st.rerun()
    except Exception:
        logger.exception("document_b_replacement_processing_failed")
        st.session_state[REPLACEMENT_ERROR_KEY] = (
            "Document B could not be activated. See the private UI log. "
            "Any existing active version remains in use."
        )
        st.rerun()
    else:
        st.session_state[REPLACEMENT_SUCCESS_KEY] = _success_message(asset)
        st.rerun()


def _success_message(asset: ReferenceAsset) -> str:
    if asset.processing_status is ReferenceAssetProcessingStatus.READY:
        return f"'{asset.asset_key}' version {asset.version} is active and READY."
    return (
        f"'{asset.asset_key}' version {asset.version} is stored as PENDING. "
        "Any existing active version remains in use."
    )
