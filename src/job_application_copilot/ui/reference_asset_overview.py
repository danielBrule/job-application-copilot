"""Settings overview presentation for required local reference assets."""

from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from job_application_copilot.domain import (
    ReferenceAssetVersionSummary,
    SettingsAssetOverview,
)
from job_application_copilot.observability import get_logger
from job_application_copilot.services import ReferenceAssetOverviewService

logger = get_logger(__name__)
REFERENCE_OVERVIEW_ERROR_MESSAGE = "Reference assets could not be loaded. See the private UI log."


@dataclass(frozen=True, slots=True)
class ReferenceAssetOverviewRow:
    """One user-facing active, candidate, missing, or aggregate overview row."""

    category: str
    asset_key: str
    role: str
    name: str
    stored_filename: str
    version_or_count: str
    uploaded: str
    status: str
    active: str
    details: str

    def as_dict(self) -> dict[str, str]:
        return {
            "Category": self.category,
            "Asset key": self.asset_key,
            "Role": self.role,
            "Name": self.name,
            "Stored filename": self.stored_filename,
            "Version / count": self.version_or_count,
            "Uploaded": self.uploaded,
            "Status": self.status,
            "Active": self.active,
            "Details": self.details,
        }


def build_reference_asset_rows(
    overview: SettingsAssetOverview,
) -> list[ReferenceAssetOverviewRow]:
    """Shape the complete overview without coupling services to Streamlit."""

    rows: list[ReferenceAssetOverviewRow] = []
    for item in overview.required_assets:
        if item.active_version is None and item.latest_version is None:
            rows.append(
                _missing_row(
                    category=item.requirement.label,
                    asset_key=item.requirement.asset_key,
                    name=item.requirement.label,
                )
            )
            continue

        if item.active_version is not None:
            rows.append(
                _version_row(
                    category=item.requirement.label,
                    role="Active input",
                    version=item.active_version,
                )
            )
        if item.latest_version is not None and (
            item.active_version is None or item.latest_version.id != item.active_version.id
        ):
            rows.append(
                _version_row(
                    category=item.requirement.label,
                    role="Latest candidate",
                    version=item.latest_version,
                )
            )

    examples = overview.french_examples
    rows.append(
        ReferenceAssetOverviewRow(
            category="French CV examples",
            asset_key="french-reference-examples",
            role="Requirement",
            name="French style and terminology references",
            stored_filename="—",
            version_or_count=f"{examples.ready_count}/{examples.minimum_required}",
            uploaded="—",
            status="READY" if examples.is_ready else "MISSING",
            active="—",
            details=(
                "Minimum ready examples satisfied."
                if examples.is_ready
                else f"{examples.minimum_required - examples.ready_count} more ready "
                "example(s) required."
            ),
        )
    )
    active_examples = {version.asset_key: version for version in examples.active_versions}
    for latest in examples.latest_versions:
        active = active_examples.get(latest.asset_key)
        if active is not None:
            rows.append(
                _version_row(
                    category="French CV examples",
                    role="Active example",
                    version=active,
                )
            )
        if active is None or active.id != latest.id:
            rows.append(
                _version_row(
                    category="French CV examples",
                    role="Latest candidate",
                    version=latest,
                )
            )

    for group in overview.prompt_groups:
        rows.append(
            ReferenceAssetOverviewRow(
                category="Prompts",
                asset_key=group.pipeline_group,
                role="Required group",
                name=_display_group(group.pipeline_group),
                stored_filename="—",
                version_or_count=f"{group.ready_count}/{group.required_count}",
                uploaded="—",
                status="READY" if group.is_ready else "MISSING",
                active="—",
                details=(
                    "All enabled prompts are ready."
                    if group.is_ready
                    else "Missing: " + ", ".join(group.missing_asset_keys)
                ),
            )
        )
    return rows


def render_reference_asset_overview(service: ReferenceAssetOverviewService) -> None:
    """Render required reference inputs and their active/latest status."""

    st.header("Reference assets")
    st.caption(
        "Active inputs remain usable while newer pending or failed candidates are shown "
        "separately. Stored filenames are private immutable local versions."
    )
    try:
        overview = service.get_overview()
    except Exception:
        logger.exception("reference_asset_overview_load_failed")
        st.error(REFERENCE_OVERVIEW_ERROR_MESSAGE)
        return

    rows = build_reference_asset_rows(overview)
    st.dataframe(
        [row.as_dict() for row in rows],
        hide_index=True,
        width="stretch",
    )


def _missing_row(
    *,
    category: str,
    asset_key: str,
    name: str,
) -> ReferenceAssetOverviewRow:
    return ReferenceAssetOverviewRow(
        category=category,
        asset_key=asset_key,
        role="Required input",
        name=name,
        stored_filename="—",
        version_or_count="—",
        uploaded="—",
        status="MISSING",
        active="No",
        details="Required asset has no stored version.",
    )


def _version_row(
    *,
    category: str,
    role: str,
    version: ReferenceAssetVersionSummary,
) -> ReferenceAssetOverviewRow:
    return ReferenceAssetOverviewRow(
        category=category,
        asset_key=version.asset_key,
        role=role,
        name=version.name,
        stored_filename=version.filename,
        version_or_count=f"v{version.version}",
        uploaded=_format_utc(version.uploaded_at),
        status=(
            version.processing_status.value
            if version.is_active
            else f"{version.processing_status.value} — not active"
        ),
        active="Yes" if version.is_active else "No",
        details="—",
    )


def _format_utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def _display_group(pipeline_group: str) -> str:
    return pipeline_group.replace("/", " / ").replace("-", " ").title()
