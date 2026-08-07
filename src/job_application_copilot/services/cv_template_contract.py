"""Derive and validate the exact final-CV contract from the active template manifest."""

import json
from dataclasses import dataclass

from job_application_copilot.domain import (
    ENGLISH_CV_TEMPLATE_KEY,
    CvExperienceBlock,
    CvTemplateManifest,
    CvTemplateManifestStatus,
    CvTemplateSlotKind,
    CvTemplateSlotMapping,
    FinalCvOutput,
)
from job_application_copilot.errors import ApplicationValidationError
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.cv_template_manifest_repository import (
    CvTemplateManifestRepository,
)
from job_application_copilot.repositories.reference_asset_repository import ReferenceAssetRepository


class CvTemplateContractError(ApplicationValidationError):
    """Raised when a final CV does not exactly match the confirmed template."""


@dataclass(frozen=True, slots=True)
class CvTemplateContract:
    manifest: CvTemplateManifest

    def prompt_input(self) -> str:
        return json.dumps(
            {
                "required_slots": [slot.model_dump(mode="json") for slot in self.manifest.slots],
                "instruction": "Return exactly one value for every required slot and no unlisted placeholders.",
            },
            sort_keys=True,
        )

    def validate(self, output: FinalCvOutput) -> None:
        slots = self.manifest.slots
        self._require_one(slots, CvTemplateSlotKind.OPENING_TITLE, output.opening_title.placeholder)
        self._require_one(
            slots, CvTemplateSlotKind.OPENING_PROFILE, output.opening_profile.placeholder
        )
        self._require_one(slots, CvTemplateSlotKind.SKILLS, output.skills.placeholder)

        expected_experience = {
            slot.placeholder: slot.experience_target
            for slot in slots
            if slot.kind is CvTemplateSlotKind.EXPERIENCE
        }
        if set(expected_experience) != {item.placeholder for item in output.experience}:
            raise CvTemplateContractError(
                "Final CV experience placeholders do not match the template."
            )
        expected_titles = {
            slot.experience_target: slot.placeholder
            for slot in slots
            if slot.kind is CvTemplateSlotKind.EXPERIENCE_TITLE
        }
        for item in output.experience:
            expected_title = expected_titles.get(expected_experience[item.placeholder])
            actual_title = None if item.title is None else item.title.placeholder
            if expected_title is None and actual_title is not None:
                raise CvTemplateContractError(
                    "Final CV experience title placeholders do not match the template."
                )
            if expected_title is not None and actual_title not in {None, expected_title}:
                raise CvTemplateContractError(
                    "Final CV experience title placeholders do not match the template."
                )

    def normalise_experience_titles(self, output: FinalCvOutput) -> FinalCvOutput:
        """Assign title content to its template-defined experience-title placeholder."""

        experience_targets = {
            slot.placeholder: slot.experience_target
            for slot in self.manifest.slots
            if slot.kind is CvTemplateSlotKind.EXPERIENCE
        }
        title_placeholders = {
            slot.experience_target: slot.placeholder
            for slot in self.manifest.slots
            if slot.kind is CvTemplateSlotKind.EXPERIENCE_TITLE
        }

        def normalise_title(item: CvExperienceBlock) -> CvExperienceBlock:
            target = experience_targets.get(item.placeholder)
            if target is None:
                return item
            title_placeholder = title_placeholders.get(target)
            if title_placeholder is None:
                return item.model_copy(update={"title": None})
            if item.title is None:
                return item
            return item.model_copy(
                update={"title": item.title.model_copy(update={"placeholder": title_placeholder})}
            )

        experience = tuple(normalise_title(item) for item in output.experience)
        return output.model_copy(update={"experience": experience})

    @staticmethod
    def _require_one(
        slots: tuple[CvTemplateSlotMapping, ...], kind: CvTemplateSlotKind, actual: str
    ) -> None:
        expected = [slot.placeholder for slot in slots if slot.kind is kind]
        if len(expected) != 1 or actual != expected[0]:
            raise CvTemplateContractError(f"Final CV must provide exactly one {kind.value} slot.")


class CvTemplateContractService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def active(self) -> CvTemplateContract:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).get_active(ENGLISH_CV_TEMPLATE_KEY)
            if asset is None:
                raise CvTemplateContractError("A confirmed active English CV template is required.")
            record = CvTemplateManifestRepository(session).get_for_template_asset(asset.id)
            if record is None:
                raise CvTemplateContractError("The active English CV template has no manifest.")
            manifest = CvTemplateManifest(
                template_asset_id=record.template_asset_id,
                status=record.status,
                placeholders=tuple(record.placeholders),
                slots=tuple(CvTemplateSlotMapping.model_validate(slot) for slot in record.slots),
            )
        if manifest.status is not CvTemplateManifestStatus.CONFIRMED:
            raise CvTemplateContractError(
                "The active English CV template mapping is not confirmed."
            )
        return CvTemplateContract(manifest)
