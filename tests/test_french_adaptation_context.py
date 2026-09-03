"""French adaptation starts from the final English CV without changing evidence."""

import json
from datetime import date
from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    BackgroundOperation,
    CvExperienceBlock,
    CvSkillEntry,
    CvSkillsBlock,
    CvTemplateSlotKind,
    CvTemplateSlotMapping,
    CvTemplateText,
    FinalCvOutput,
    FrenchReferencePassage,
    Language,
    Location,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import CvGenerationFinalRepository, create_database
from job_application_copilot.repositories.models import BackgroundBatch, BackgroundTask, Job
from job_application_copilot.repositories.reference_asset_repository import ReferenceAssetRepository
from job_application_copilot.services import (
    CvTemplateManifestService,
    FrenchAdaptationContextBuilder,
    FrenchAdaptationContextError,
    PromptService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from tests.app_test_support import make_docx


def final_english_cv() -> FinalCvOutput:
    return FinalCvOutput(
        opening_title=CvTemplateText(
            placeholder="[OPENING_TITLE]", content="AI Solutions Director"
        ),
        opening_profile=CvTemplateText(
            placeholder="[OPENING_PROFILE]",
            content="Led an evidenced programme that improved delivery by 42%.",
        ),
        experience=(
            CvExperienceBlock(
                placeholder="[EXPERIENCE_CURRENT]",
                introduction="Director at Example Ltd.",
                bullets=("Delivered £2.5m of validated outcomes with shared ownership.",),
            ),
        ),
        skills=CvSkillsBlock(
            placeholder="[SKILLS]",
            entries=(CvSkillEntry(name="Architecture", content="Evidence-led delivery"),),
        ),
    )


def template_content(*placeholders: str) -> bytes:
    return make_docx("\n".join(placeholders))


@pytest.fixture
def context_setup(tmp_path: Path):
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    templates = CvTemplateManifestService(database, settings)
    placeholders = (
        "[OPENING_TITLE]",
        "[OPENING_PROFILE]",
        "[EXPERIENCE_CURRENT]",
        "[SKILLS]",
    )
    english = templates.upload(filename="english.docx", content=template_content(*placeholders))
    templates.confirm(
        template_asset_id=english.template_asset_id,
        slots=(
            CvTemplateSlotMapping(
                placeholder="[OPENING_TITLE]", kind=CvTemplateSlotKind.OPENING_TITLE
            ),
            CvTemplateSlotMapping(
                placeholder="[OPENING_PROFILE]", kind=CvTemplateSlotKind.OPENING_PROFILE
            ),
            CvTemplateSlotMapping(
                placeholder="[EXPERIENCE_CURRENT]",
                kind=CvTemplateSlotKind.EXPERIENCE,
                experience_target="Current employer",
            ),
            CvTemplateSlotMapping(placeholder="[SKILLS]", kind=CvTemplateSlotKind.SKILLS),
        ),
    )
    templates.replace_french(
        filename="french.docx",
        content=template_content(*reversed(placeholders)),
    )
    PromptService(database).save_text(
        "cv-generation-fr-extension-1", "Adaptez le CV final en français."
    )

    with database.session() as session:
        job = Job(
            company="Example Ltd",
            job_title="Directeur",
            location=Location.FR,
            language=Language.FR,
            source="LinkedIn",
            job_description="Poste français",
            date_added=date(2026, 9, 3),
        )
        session.add(job)
        session.flush()
        batch = BackgroundBatch(operation=BackgroundOperation.CV_GENERATION)
        session.add(batch)
        session.flush()
        task = BackgroundTask(
            batch_id=batch.id,
            job_id=job.id,
            operation=BackgroundOperation.CV_GENERATION,
        )
        session.add(task)
        session.flush()
        task_id = task.id
        CvGenerationFinalRepository(session).store(
            task_id=task_id,
            output=final_english_cv(),
            document_a_version=7,
            document_b_version=4,
            routing_set_id=2,
            prompt_version=3,
        )

    try:
        yield database, settings, task_id
    finally:
        database.dispose()


def active_reference(database, settings: AppSettings) -> FrenchReferencePassage:
    stored = ReferenceAssetStorageService(database, settings).store(
        filename="reference.docx",
        content=make_docx("Profil : direction de solutions."),
        asset_key="french-example-direction",
        asset_type=ReferenceAssetType.REFERENCE_EXAMPLE,
        name="French direction CV",
        language_code="fr",
    )
    with database.session() as session:
        asset = ReferenceAssetRepository(session).require_version(stored.asset_key, stored.version)
        asset.processing_status = ReferenceAssetProcessingStatus.READY
        asset.is_active = True
        session.flush()
    return FrenchReferencePassage(
        text="Profil : direction de solutions.",
        score=0.91,
        reference_asset_id=stored.id,
        asset_key=stored.asset_key,
        version=stored.version,
        name=stored.name,
        source_metadata={"style_reference_only": "true"},
    )


def test_context_starts_with_complete_final_english_cv_and_preserves_evidence(
    context_setup,
) -> None:
    database, settings, task_id = context_setup
    reference = active_reference(database, settings)

    context = FrenchAdaptationContextBuilder(database, settings).build(
        task_id,
        model_identifier="gpt-test",
        response_schema={"type": "object"},
        references=(reference,),
    )

    assert [item.section for item in context.input] == [
        "final_english_cv",
        "stage_instructions",
        "evidence_preservation",
        "template_contract",
        "french_style_references",
    ]
    assert FinalCvOutput.model_validate_json(context.input[0].text) == final_english_cv()
    assert "42%" in context.input[0].text
    assert "£2.5m" in context.input[0].text
    assert "shared ownership" in context.input[0].text
    assert "style and terminology guidance only" in context.input[2].text
    references = json.loads(context.input[-1].text)
    assert references[0]["style_reference_only"] is True
    assert context.traceability.french_reference_versions == ("french-example-direction:v1",)


def test_context_rejects_missing_final_english_output(context_setup) -> None:
    database, settings, task_id = context_setup
    with database.session() as session:
        stored = CvGenerationFinalRepository(session).require_for_task(task_id)
        session.delete(stored)

    with pytest.raises(FrenchAdaptationContextError, match="final English CV output"):
        FrenchAdaptationContextBuilder(database, settings).build(
            task_id,
            model_identifier="gpt-test",
            response_schema={"type": "object"},
        )


def test_context_requires_active_ready_french_prompt_one(context_setup) -> None:
    database, settings, task_id = context_setup
    with database.session() as session:
        prompt = ReferenceAssetRepository(session).get_active("cv-generation-fr-extension-1")
        assert prompt is not None
        prompt.is_active = False

    with pytest.raises(FrenchAdaptationContextError, match="not READY"):
        FrenchAdaptationContextBuilder(database, settings).build(
            task_id,
            model_identifier="gpt-test",
            response_schema={"type": "object"},
        )


def test_context_rejects_reference_without_style_only_source_marker(context_setup) -> None:
    database, settings, task_id = context_setup
    reference = active_reference(database, settings).model_copy(update={"source_metadata": {}})

    with pytest.raises(FrenchAdaptationContextError, match="style-only"):
        FrenchAdaptationContextBuilder(database, settings).build(
            task_id,
            model_identifier="gpt-test",
            response_schema={"type": "object"},
            references=(reference,),
        )


def test_context_defensively_rejects_an_active_french_template_with_different_placeholders(
    context_setup,
) -> None:
    database, settings, task_id = context_setup
    ReferenceAssetStorageService(database, settings).replace(
        filename="legacy-invalid-french.docx",
        content=template_content("[OPENING_TITLE]", "[SKILLS]"),
        asset_key="cv-template-fr",
        asset_type=ReferenceAssetType.TEMPLATE,
        name="French CV template",
        language_code="fr",
    )

    with pytest.raises(FrenchAdaptationContextError, match="same placeholder names"):
        FrenchAdaptationContextBuilder(database, settings).build(
            task_id,
            model_identifier="gpt-test",
            response_schema={"type": "object"},
        )
