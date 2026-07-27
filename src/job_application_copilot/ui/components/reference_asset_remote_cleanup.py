"""Settings controls for explicit cleanup of inactive OpenAI resources."""

from dataclasses import dataclass

import streamlit as st

from job_application_copilot.observability import get_logger
from job_application_copilot.services import (
    InactiveRemoteAsset,
    ReferenceAssetRemoteCleanupError,
    ReferenceAssetRemoteCleanupNotAllowedError,
    ReferenceAssetRemoteCleanupService,
    ReferenceAssetRemoteRestoreError,
    ReferenceAssetRemoteRestoreNotAllowedError,
)

logger = get_logger(__name__)
REMOTE_CLEANUP_SUCCESS_KEY = "reference_asset_remote_cleanup_success"
REMOTE_CLEANUP_BUTTON_KEY = "delete_inactive_openai_resources"
REMOTE_RESTORE_SUCCESS_KEY = "reference_asset_remote_restore_success"
REMOTE_RESTORE_BUTTON_KEY = "restore_retained_reference_version"
REMOTE_CLEANUP_ERROR_MESSAGE = (
    "Inactive OpenAI resources could not be cleaned. See the private UI log."
)


@dataclass(frozen=True, slots=True)
class RemoteCleanupRow:
    """One user-facing inactive remote-resource row."""

    asset: str
    version: str
    status: str
    vector_store: str
    openai_file: str
    stored_usage: str
    local_file: str

    def as_dict(self) -> dict[str, str]:
        return {
            "Asset": self.asset,
            "Version": self.version,
            "Status": self.status,
            "Vector store": self.vector_store,
            "OpenAI file": self.openai_file,
            "Stored usage": self.stored_usage,
            "Local file retained": self.local_file,
        }


def render_reference_asset_remote_cleanup(
    service: ReferenceAssetRemoteCleanupService,
) -> None:
    """List safely cleanable remote resources and require explicit confirmation."""

    st.subheader("Inactive OpenAI resources")
    st.caption(
        "Delete remote resources no longer used by an active reference version. "
        "Local DOCX files and version metadata are retained."
    )
    if message := st.session_state.pop(REMOTE_CLEANUP_SUCCESS_KEY, None):
        st.success(message)

    try:
        candidates = service.list_candidates()
        restorable_versions = service.list_restorable_versions()
    except Exception:
        logger.exception("inactive_remote_resource_list_failed")
        st.error(REMOTE_CLEANUP_ERROR_MESSAGE)
        return

    _render_cleanup_controls(service, candidates)
    _render_restoration_controls(service, restorable_versions)


def _render_cleanup_controls(
    service: ReferenceAssetRemoteCleanupService,
    candidates: tuple[InactiveRemoteAsset, ...],
) -> None:
    if not candidates:
        st.caption("No inactive OpenAI resources are available for cleanup.")
    else:
        st.dataframe(
            [_row(candidate).as_dict() for candidate in candidates],
            hide_index=True,
            width="stretch",
        )
        options = [(candidate.asset_key, candidate.version) for candidate in candidates]
        selected = st.selectbox(
            "Inactive reference version",
            options=options,
            format_func=lambda value: _option_label(candidates, value),
            key="inactive_remote_cleanup_selection",
        )
        candidate = next(item for item in candidates if (item.asset_key, item.version) == selected)
        confirmed = st.checkbox(
            (
                f"Delete the tracked OpenAI resources for {candidate.name} "
                f"v{candidate.version}. Keep its local DOCX and metadata."
            ),
            key=f"confirm_remote_cleanup_{candidate.asset_key}_{candidate.version}",
        )
        if st.button(
            "Delete inactive OpenAI resources",
            key=REMOTE_CLEANUP_BUTTON_KEY,
            disabled=not confirmed,
        ):
            _delete_remote_resources(service, candidate)


def _delete_remote_resources(
    service: ReferenceAssetRemoteCleanupService,
    candidate: InactiveRemoteAsset,
) -> None:
    try:
        with st.spinner(
            f"Deleting inactive OpenAI resources for {candidate.name} v{candidate.version}..."
        ):
            result = service.cleanup(candidate.asset_key, candidate.version)
    except (
        ReferenceAssetRemoteCleanupError,
        ReferenceAssetRemoteCleanupNotAllowedError,
        LookupError,
    ) as error:
        logger.exception(
            "inactive_remote_resource_cleanup_failed asset_key=%s version=%s",
            candidate.asset_key,
            candidate.version,
        )
        st.error(str(error))
    except Exception:
        logger.exception(
            "inactive_remote_resource_cleanup_unexpected_failure asset_key=%s version=%s",
            candidate.asset_key,
            candidate.version,
        )
        st.error(REMOTE_CLEANUP_ERROR_MESSAGE)
    else:
        deleted = []
        if result.vector_store_deleted:
            deleted.append("vector store")
        if result.file_deleted:
            deleted.append("OpenAI file")
        st.session_state[REMOTE_CLEANUP_SUCCESS_KEY] = (
            f"Deleted {' and '.join(deleted)} for {candidate.name} v{candidate.version}. "
            "The local DOCX and metadata were retained."
        )
        st.rerun()


def _render_restoration_controls(
    service: ReferenceAssetRemoteCleanupService,
    candidates: tuple[InactiveRemoteAsset, ...],
) -> None:
    st.subheader("Retained local document versions")
    st.caption(
        "Restore a retained Document A or Document B version by verifying its local DOCX, "
        "rebuilding its OpenAI resources and activating it only after processing succeeds."
    )
    if message := st.session_state.pop(REMOTE_RESTORE_SUCCESS_KEY, None):
        st.success(message)
    if not candidates:
        st.caption("No retained document versions are available for restoration.")
        return

    options = [(candidate.asset_key, candidate.version) for candidate in candidates]
    selected = st.selectbox(
        "Retained document version",
        options=options,
        format_func=lambda value: _retained_option_label(candidates, value),
        key="retained_remote_restore_selection",
    )
    candidate = next(item for item in candidates if (item.asset_key, item.version) == selected)
    if not st.button(
        "Restore and activate with OpenAI",
        key=REMOTE_RESTORE_BUTTON_KEY,
        type="primary",
    ):
        return

    try:
        with st.spinner(
            f"Restoring and activating {candidate.name} v{candidate.version} with OpenAI..."
        ):
            restored = service.restore(candidate.asset_key, candidate.version)
    except (
        ReferenceAssetRemoteRestoreError,
        ReferenceAssetRemoteRestoreNotAllowedError,
        LookupError,
    ) as error:
        logger.exception(
            "retained_reference_restore_failed asset_key=%s version=%s",
            candidate.asset_key,
            candidate.version,
        )
        st.error(str(error))
    except Exception:
        logger.exception(
            "retained_reference_restore_unexpected_failure asset_key=%s version=%s",
            candidate.asset_key,
            candidate.version,
        )
        st.error("The retained reference version could not be restored. See the private UI log.")
    else:
        st.session_state[REMOTE_RESTORE_SUCCESS_KEY] = (
            f"Restored {restored.name} v{restored.version}; it is active and READY."
        )
        st.rerun()


def _row(candidate: InactiveRemoteAsset) -> RemoteCleanupRow:
    return RemoteCleanupRow(
        asset=candidate.name,
        version=f"v{candidate.version}",
        status=candidate.processing_status.value,
        vector_store=candidate.openai_vector_store_id or "—",
        openai_file=candidate.openai_file_id or "—",
        stored_usage=_format_bytes(candidate.openai_vector_store_usage_bytes),
        local_file=candidate.file_path,
    )


def _option_label(
    candidates: tuple[InactiveRemoteAsset, ...],
    value: tuple[str, int],
) -> str:
    candidate = next(item for item in candidates if (item.asset_key, item.version) == value)
    resources = []
    if candidate.openai_vector_store_id is not None:
        resources.append("vector store")
    if candidate.openai_file_id is not None:
        resources.append("file")
    return f"{candidate.name} v{candidate.version} — {' + '.join(resources)}"


def _retained_option_label(
    candidates: tuple[InactiveRemoteAsset, ...],
    value: tuple[str, int],
) -> str:
    candidate = next(item for item in candidates if (item.asset_key, item.version) == value)
    return (
        f"{candidate.name} v{candidate.version} — "
        f"{candidate.processing_status.value}, local DOCX retained"
    )


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    if value < 1_024:
        return f"{value} B"
    if value < 1_024 * 1_024:
        return f"{value / 1_024:.1f} KiB"
    return f"{value / (1_024 * 1_024):.1f} MiB"
