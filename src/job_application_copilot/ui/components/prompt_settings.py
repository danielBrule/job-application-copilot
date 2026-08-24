"""Prompt-specific Settings component and presentation shaping."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from job_application_copilot.domain import PromptCompleteness
from job_application_copilot.errors import (
    ApplicationNotFoundError,
    ApplicationStorageError,
    ApplicationValidationError,
)
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories import (
    PromptDefinitionNotFoundError,
    ReferenceAssetVersionNotFoundError,
)
from job_application_copilot.repositories.models import PromptDefinition
from job_application_copilot.services import (
    PromptActivationError,
    PromptService,
    PromptStorageError,
)

logger = get_logger(__name__)
PROMPT_UI_ERROR_MESSAGE = "Prompt settings could not be updated. See the private UI log."


@dataclass(frozen=True, slots=True)
class PromptCompletenessRow:
    """User-facing completeness values for one pipeline group."""

    pipeline_group: str
    language: str
    ready: str
    missing: str

    def as_dict(self) -> dict[str, str]:
        return {
            "Pipeline group": self.pipeline_group,
            "Language": self.language,
            "Ready": self.ready,
            "Missing": self.missing,
        }


def build_completeness_rows(
    groups: tuple[PromptCompleteness, ...],
) -> list[PromptCompletenessRow]:
    """Shape completeness results without coupling the service to Streamlit."""

    return [
        PromptCompletenessRow(
            pipeline_group=_display_group(group.pipeline_group),
            language=(group.language_code or "—").upper(),
            ready=f"{group.ready_count}/{group.required_count}",
            missing=", ".join(group.missing_asset_keys) or "—",
        )
        for group in groups
    ]


def render_prompt_settings(
    service: PromptService,
    *,
    show_page_title: bool = True,
    show_completeness: bool = True,
) -> None:
    """Render prompt completeness, definitions, editing, and activation."""

    if show_page_title:
        st.title("Settings")
    st.header("Prompts")
    st.caption(
        "Prompt definitions determine required pipeline stages. Saving text creates "
        "an immutable active version stored in the local SQLite database."
    )

    try:
        definitions = service.list_definitions()
        completeness = service.completeness()
    except Exception:
        logger.exception("prompt_settings_load_failed")
        st.error(PROMPT_UI_ERROR_MESSAGE)
        return

    if show_completeness:
        rows = build_completeness_rows(completeness)
        if rows:
            st.dataframe(
                [row.as_dict() for row in rows],
                hide_index=True,
                width="stretch",
            )
        else:
            st.warning("No enabled prompt definitions are configured.")

    if not definitions:
        st.info("No prompt definitions exist.")
    else:
        for pipeline_group, grouped_definitions in groupby(
            definitions,
            key=lambda definition: definition.pipeline_group,
        ):
            st.subheader(_display_group(pipeline_group))
            for definition in grouped_definitions:
                _render_definition(service, definition)


def _render_definition(service: PromptService, definition: PromptDefinition) -> None:
    active = service.get_active_version(definition.asset_key)
    versions = service.list_versions(definition.asset_key)
    status = f"v{active.version} READY" if active is not None else "Missing"
    enabled_status = "Required" if definition.is_enabled else "Disabled"

    with st.expander(f"{definition.position}. {definition.name} — {status}"):
        st.caption(
            f"`{definition.asset_key}` · {enabled_status} · "
            f"Language: {(definition.language_code or 'none').upper()}"
        )
        if st.button(
            "Disable" if definition.is_enabled else "Enable",
            key=f"prompt_enabled_{definition.asset_key}",
        ):
            _set_enabled(service, definition)

        try:
            active_text = service.get_active_text(definition.asset_key) or ""
        except PromptStorageError as error:
            st.error(str(error))
            active_text = ""

        with st.form(f"prompt_text_{definition.asset_key}"):
            text = st.text_area(
                "Prompt text",
                value=active_text,
                height=240,
            )
            save = st.form_submit_button("Save as new active version")

        if save:
            _save_prompt_text(service, definition, text)

        if versions:
            version_numbers = [version.version for version in versions]
            selected_version = st.selectbox(
                "Retained versions",
                options=version_numbers,
                format_func=lambda version: (
                    f"Version {version}"
                    + (" (active)" if active is not None and version == active.version else "")
                ),
                key=f"prompt_version_{definition.asset_key}",
            )
            if st.button(
                "Activate selected version",
                key=f"prompt_activate_{definition.asset_key}",
                disabled=active is not None and selected_version == active.version,
            ):
                _activate_prompt_version(service, definition.asset_key, selected_version)


def _set_enabled(service: PromptService, definition: PromptDefinition) -> None:
    try:
        service.set_enabled(definition.asset_key, not definition.is_enabled)
    except PromptDefinitionNotFoundError as error:
        st.error(str(error))
    except (SQLAlchemyError, OSError):
        logger.exception("prompt_definition_enable_failed asset_key=%s", definition.asset_key)
        st.error(PROMPT_UI_ERROR_MESSAGE)
    else:
        st.rerun()


def _save_prompt_text(
    service: PromptService,
    definition: PromptDefinition,
    text: str,
) -> None:
    try:
        asset = service.save_text(definition.asset_key, text)
    except (
        ApplicationNotFoundError,
        ApplicationStorageError,
        ApplicationValidationError,
    ) as error:
        st.error(str(error))
    except (SQLAlchemyError, OSError):
        logger.exception("prompt_save_failed asset_key=%s", definition.asset_key)
        st.error(PROMPT_UI_ERROR_MESSAGE)
    else:
        st.success(f"{definition.name} version {asset.version} is active.")
        st.rerun()


def _activate_prompt_version(
    service: PromptService,
    asset_key: str,
    version: int,
) -> None:
    try:
        service.activate_version(asset_key, version)
    except (
        PromptActivationError,
        PromptDefinitionNotFoundError,
        ReferenceAssetVersionNotFoundError,
    ) as error:
        st.error(str(error))
    except SQLAlchemyError:
        logger.exception(
            "prompt_activation_failed asset_key=%s version=%s",
            asset_key,
            version,
        )
        st.error(PROMPT_UI_ERROR_MESSAGE)
    else:
        st.rerun()


def _display_group(pipeline_group: str) -> str:
    return pipeline_group.replace("/", " / ").replace("-", " ").title()
