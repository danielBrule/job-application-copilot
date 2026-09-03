"""Create and validate private English and French CV templates."""

from datetime import UTC, datetime

from job_application_copilot.config import AppSettings
from job_application_copilot.documents.template_placeholders import extract_template_placeholders
from job_application_copilot.domain import (
    ENGLISH_CV_TEMPLATE_KEY,
    FRENCH_CV_TEMPLATE_KEY,
    CvTemplateManifest,
    CvTemplateManifestStatus,
    CvTemplateSlotMapping,
    ReferenceAssetType,
)
from job_application_copilot.errors import ApplicationNotFoundError, ApplicationValidationError
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.cv_template_manifest_repository import (
    CvTemplateManifestRepository,
)
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import ReferenceAssetRepository
from job_application_copilot.services.reference_asset_storage import ReferenceAssetStorageService


class CvTemplateManifestError(ApplicationValidationError):
    """Raised when a template manifest is unsafe or incomplete."""


class CvTemplateManifestNotFoundError(ApplicationNotFoundError):
    """Raised when a template version has no private manifest."""


class CvTemplateManifestService:
    def __init__(self, database: Database, settings: AppSettings) -> None:
        self.database = database
        self.settings = settings
        self.storage = ReferenceAssetStorageService(database, settings)

    def upload(
        self, *, filename: str, content: bytes, name: str = "English CV template"
    ) -> CvTemplateManifest:
        placeholders = extract_template_placeholders(content)
        if not placeholders:
            raise CvTemplateManifestError("The English CV template has no bracketed placeholders.")
        asset = self.storage.store_template_candidate(
            filename=filename,
            content=content,
            asset_key=ENGLISH_CV_TEMPLATE_KEY,
            name=name,
            language_code="en",
        )
        with self.database.session() as session:
            record = CvTemplateManifestRepository(session).create_draft(
                template_asset_id=asset.id, placeholders=placeholders
            )
            return self._model(record)

    def replace_french(
        self,
        *,
        filename: str,
        content: bytes,
        name: str = "French CV template",
    ) -> ReferenceAsset:
        """Validate a French template against English slots, then activate it."""

        self.validate_french_template(content)
        return self.storage.replace(
            filename=filename,
            content=content,
            asset_key=FRENCH_CV_TEMPLATE_KEY,
            asset_type=ReferenceAssetType.TEMPLATE,
            name=name,
            language_code="fr",
        )

    def validate_french_template(self, content: bytes) -> CvTemplateManifest:
        """Return the authoritative English manifest when placeholders match exactly."""

        placeholders = extract_template_placeholders(content)
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).get_active(ENGLISH_CV_TEMPLATE_KEY)
            if asset is None:
                raise CvTemplateManifestError(
                    "A confirmed active English CV template is required before adding a French "
                    "CV template."
                )
            record = CvTemplateManifestRepository(session).get_for_template_asset(asset.id)
            if record is None or record.status is not CvTemplateManifestStatus.CONFIRMED:
                raise CvTemplateManifestError(
                    "The active English CV template mapping must be confirmed before adding a "
                    "French CV template."
                )
            manifest = self._model(record)

        if len(placeholders) != len(manifest.placeholders) or set(placeholders) != set(
            manifest.placeholders
        ):
            raise CvTemplateManifestError(
                "The French CV template must contain exactly the same placeholder names as the "
                "active English CV template."
            )
        return manifest

    def get(self, template_asset_id: int) -> CvTemplateManifest:
        with self.database.session() as session:
            record = CvTemplateManifestRepository(session).get_for_template_asset(template_asset_id)
            if record is None:
                raise CvTemplateManifestNotFoundError(
                    f"English template version {template_asset_id} has no placeholder manifest."
                )
            return self._model(record)

    def latest_draft(self) -> CvTemplateManifest | None:
        with self.database.session() as session:
            record = CvTemplateManifestRepository(session).latest_draft()
            return None if record is None else self._model(record)

    def confirm(
        self, *, template_asset_id: int, slots: tuple[CvTemplateSlotMapping, ...]
    ) -> CvTemplateManifest:
        with self.database.session() as session:
            manifests = CvTemplateManifestRepository(session)
            record = manifests.get_for_template_asset(template_asset_id)
            if record is None:
                raise CvTemplateManifestNotFoundError(
                    f"English template version {template_asset_id} has no placeholder manifest."
                )
            manifest = CvTemplateManifest(
                template_asset_id=template_asset_id,
                status=CvTemplateManifestStatus.CONFIRMED,
                placeholders=tuple(record.placeholders),
                slots=slots,
            )
            candidate = session.get(ReferenceAsset, template_asset_id)
            if candidate is None or candidate.asset_key != ENGLISH_CV_TEMPLATE_KEY:
                raise CvTemplateManifestError("The manifest must reference an English CV template.")
            assets = ReferenceAssetRepository(session)
            current = assets.get_active(ENGLISH_CV_TEMPLATE_KEY)
            if current is not None:
                current.is_active = False
            candidate.is_active = True
            record.status = CvTemplateManifestStatus.CONFIRMED
            record.slots = [slot.model_dump(mode="json") for slot in slots]
            record.confirmed_at = datetime.now(UTC).replace(tzinfo=None)
            session.flush()
            return manifest

    @staticmethod
    def _model(record: object) -> CvTemplateManifest:
        return CvTemplateManifest(
            template_asset_id=record.template_asset_id,  # type: ignore[attr-defined]
            status=record.status,  # type: ignore[attr-defined]
            placeholders=tuple(record.placeholders),  # type: ignore[attr-defined]
            slots=tuple(record.slots),  # type: ignore[attr-defined]
        )
