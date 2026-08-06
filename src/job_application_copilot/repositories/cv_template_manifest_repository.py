"""Persistence operations for English CV template manifests."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_application_copilot.domain import CvTemplateManifestStatus
from job_application_copilot.repositories.models import CvTemplateManifestRecord, ReferenceAsset


class CvTemplateManifestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_template_asset(self, template_asset_id: int) -> CvTemplateManifestRecord | None:
        return self.session.scalar(
            select(CvTemplateManifestRecord).where(
                CvTemplateManifestRecord.template_asset_id == template_asset_id
            )
        )

    def create_draft(
        self, *, template_asset_id: int, placeholders: tuple[str, ...]
    ) -> CvTemplateManifestRecord:
        manifest = CvTemplateManifestRecord(
            template_asset_id=template_asset_id,
            status=CvTemplateManifestStatus.DRAFT,
            placeholders=list(placeholders),
            slots=[],
        )
        self.session.add(manifest)
        self.session.flush()
        return manifest

    def latest_draft(self) -> CvTemplateManifestRecord | None:
        return self.session.scalar(
            select(CvTemplateManifestRecord)
            .join(ReferenceAsset, CvTemplateManifestRecord.template_asset_id == ReferenceAsset.id)
            .where(CvTemplateManifestRecord.status == CvTemplateManifestStatus.DRAFT)
            .order_by(ReferenceAsset.version.desc())
        )
