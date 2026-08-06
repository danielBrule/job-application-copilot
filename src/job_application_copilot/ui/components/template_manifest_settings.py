"""Minimal Settings workflow for English template upload and placeholder mapping."""

import streamlit as st

from job_application_copilot.domain import CvTemplateSlotKind, CvTemplateSlotMapping
from job_application_copilot.errors import ApplicationValidationError
from job_application_copilot.services import CvTemplateManifestService


def _suggest_mapping(placeholder: str) -> tuple[CvTemplateSlotKind, str]:
    name = placeholder.removeprefix("[").removesuffix("]")
    if name == "OPENING_TITLE":
        return CvTemplateSlotKind.OPENING_TITLE, ""
    if name == "OPENING_PROFILE":
        return CvTemplateSlotKind.OPENING_PROFILE, ""
    if name == "SKILLS":
        return CvTemplateSlotKind.SKILLS, ""
    if name.endswith("_TITLE"):
        return CvTemplateSlotKind.EXPERIENCE_TITLE, name.removesuffix("_TITLE").title()
    if name.startswith("EXPERIENCE_"):
        return CvTemplateSlotKind.EXPERIENCE, name.removeprefix("EXPERIENCE_").title()
    return CvTemplateSlotKind.OPENING_TITLE, ""


def _experience_target(placeholder: str, suggested_target: str) -> str:
    if suggested_target:
        return suggested_target
    return (
        placeholder.removeprefix("[")
        .removesuffix("]")
        .removeprefix("EXPERIENCE_")
        .removesuffix("_TITLE")
        .replace("_", " ")
        .title()
    )


def render_english_template_manifest(service: CvTemplateManifestService) -> None:
    with st.expander("Upload or replace English CV template"):
        st.caption("Upload a template, then map each discovered placeholder before activation.")
        with st.form("upload_english_template", clear_on_submit=True):
            upload = st.file_uploader("English CV template DOCX", type=["docx"])
            submitted = st.form_submit_button("Upload and scan placeholders")
        if submitted:
            if upload is None:
                st.error("Choose a DOCX file.")
            else:
                try:
                    service.upload(filename=upload.name, content=upload.getvalue())
                except ApplicationValidationError as error:
                    st.error(str(error))
                else:
                    st.success("Template stored. Configure its placeholders below.")
                    st.rerun()

        draft = service.latest_draft()
        if draft is None:
            return
        st.caption("Map the latest uploaded template before it becomes active.")
        with st.form(f"confirm_template_manifest_{draft.template_asset_id}"):
            values: list[tuple[str, CvTemplateSlotKind, str]] = []
            for placeholder in draft.placeholders:
                suggested_kind, suggested_target = _suggest_mapping(placeholder)
                kind = st.selectbox(
                    placeholder,
                    options=list(CvTemplateSlotKind),
                    index=list(CvTemplateSlotKind).index(suggested_kind),
                    format_func=lambda value: value.value.replace("_", " ").title(),
                    key=f"template_slot_kind_{draft.template_asset_id}_{placeholder}",
                )
                target = (
                    _experience_target(placeholder, suggested_target)
                    if kind
                    in {CvTemplateSlotKind.EXPERIENCE, CvTemplateSlotKind.EXPERIENCE_TITLE}
                    else ""
                )
                values.append((placeholder, kind, target))
            confirmed = st.form_submit_button("Confirm template mapping and activate")
        if confirmed:
            try:
                service.confirm(
                    template_asset_id=draft.template_asset_id,
                    slots=tuple(
                        CvTemplateSlotMapping(
                            placeholder=placeholder,
                            kind=kind,
                            experience_target=target or None,
                        )
                        for placeholder, kind, target in values
                    ),
                )
            except ApplicationValidationError as error:
                st.error(str(error))
            else:
                st.success("English template mapping confirmed and activated.")
                st.rerun()
