from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pytest
import streamlit as st
from docx import Document
from sqlalchemy import inspect
from streamlit.testing.v1 import AppTest

from job_application_copilot.domain import (
    CreateJob,
    Language,
    Location,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
    Relevance,
    UserDecision,
)
from job_application_copilot.observability import reset_logging
from job_application_copilot.repositories import create_database
from job_application_copilot.repositories.models import Job, ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DocumentAProcessingError,
    DocumentAProcessingService,
    DocumentBProcessingError,
    DocumentBProcessingService,
    JobService,
    ReferenceAssetRemoteCleanupResult,
    ReferenceAssetRemoteCleanupService,
)
from job_application_copilot.ui.app import UNEXPECTED_ERROR_MESSAGE
from job_application_copilot.ui.components.document_b_processing import (
    DOCUMENT_B_PROCESSING_BUTTON_KEY,
)
from job_application_copilot.ui.components.job_details import LOAD_ERROR_MESSAGE
from job_application_copilot.ui.components.job_filters import (
    CLEAR_FILTERS_KEY,
    FILTER_APPLICATION_STATUS_KEY,
    FILTER_LANGUAGE_KEY,
    FILTER_LOCATION_KEY,
    FILTER_SOURCE_KEY,
    FILTER_TEXT_KEY,
    FILTER_USER_DECISION_KEY,
)
from job_application_copilot.ui.components.job_form import SAVE_ERROR_MESSAGE
from job_application_copilot.ui.components.jobs_dashboard import (
    JOBS_TABLE_KEY,
    SELECTED_JOB_IDS_KEY,
)
from job_application_copilot.ui.components.jobs_dashboard import (
    LOAD_ERROR_MESSAGE as JOBS_LOAD_ERROR_MESSAGE,
)
from job_application_copilot.ui.components.reference_asset_remote_cleanup import (
    REMOTE_CLEANUP_BUTTON_KEY,
    REMOTE_RESTORE_BUTTON_KEY,
)
from job_application_copilot.ui.dependencies import get_database, get_job_service

APP_PATH = Path(__file__).parents[1] / "src" / "job_application_copilot" / "ui" / "app.py"
SETTINGS_APP_TIMEOUT = 30


def make_docx(text: str = "Reference content") -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def clear_ui_database_cache() -> None:
    get_database.clear()
    yield
    get_database.clear()


def test_streamlit_app_starts_and_creates_private_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert (data_dir / "database").is_dir()
        assert (data_dir / "cvs").is_dir()
        assert (data_dir / "logs").is_dir()
        assert (data_dir / "reference" / "document_a").is_dir()
        assert (data_dir / "reference" / "document_b").is_dir()
        assert (data_dir / "reference" / "templates").is_dir()
        assert (data_dir / "reference" / "examples").is_dir()
        assert (data_dir / "reference" / "prompts" / "assessment").is_dir()
        assert (data_dir / "reference" / "prompts" / "generation" / "english").is_dir()
        assert (data_dir / "reference" / "prompts" / "generation" / "french").is_dir()
        log_contents = (data_dir / "logs" / "ui.log").read_text(encoding="utf-8")
        assert "application_started" in log_contents
        database_path = data_dir / "database" / "job_application_copilot.db"
        database = create_database(database_path)
        try:
            assert inspect(database.engine).get_table_names() == [
                "alembic_version",
                "document_b_sections",
                "jobs",
                "prompt_definitions",
                "reference_assets",
            ]
        finally:
            database.dispose()
    finally:
        reset_logging()


@pytest.mark.parametrize(
    ("page_path", "expected_title", "expected_message"),
    [
        (
            "pages/background_runs.py",
            "Background Runs",
            "Background task monitoring will be implemented in milestone M4.",
        ),
    ],
)
def test_navigation_reaches_each_primary_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page_path: str,
    expected_title: str,
    expected_message: str,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        app.switch_page(page_path).run()

        assert not app.exception
        assert app.title[0].value == expected_title
        assert app.info[0].value == expected_message
    finally:
        reset_logging()


def test_settings_page_displays_seeded_prompt_completeness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()

    try:
        app.switch_page("pages/settings.py").run()

        assert not app.exception
        assert app.title[0].value == "Settings"
        assert [header.value for header in app.header] == [
            "Reference assets",
            "Prompts",
        ]
        assert [subheader.value for subheader in app.subheader] == [
            "Local DOCX uploads",
            "Inactive OpenAI resources",
            "Retained local document versions",
            "Assessment",
            "Generation / English",
            "Generation / French",
        ]
        assert len(app.dataframe) == 1
        overview_table = app.dataframe[0].value
        assert overview_table["Asset key"].tolist() == [
            "document-a",
            "document-b",
            "cv-template-en",
            "cv-template-fr",
            "french-reference-examples",
            "assessment",
            "generation/english",
            "generation/french",
        ]
        assert overview_table["Status"].tolist() == ["MISSING"] * 8
        assert [expander.label for expander in app.expander] == [
            "Upload or replace Document A",
            "Upload or replace Document B",
            "Upload or replace English CV template",
            "Upload or replace French CV template",
            "Manage French CV examples",
            "1. Assessment prompt — Missing",
            "1. English generation prompt 1 — Missing",
            "2. English generation prompt 2 — Missing",
            "3. English generation prompt 3 — Missing",
            "4. English generation prompt 4 — Missing",
            "1. French extension prompt 1 — Missing",
            "2. French extension prompt 2 — Missing",
            "Add pipeline prompt",
        ]
    finally:
        reset_logging()


def test_settings_page_saves_prompt_text_as_active_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()

    try:
        app.switch_page("pages/settings.py").run()
        app.text_area[0].set_value("Assessment instructions.\n")
        app.button(
            key="FormSubmitter:prompt_text_assessment-Save as new active version"
        ).click().run()

        assert not app.exception
        assert app.expander[5].label == "1. Assessment prompt — v1 READY"
        assert (
            data_dir / "reference" / "prompts" / "assessment" / "assessment-v0001.txt"
        ).read_text(encoding="utf-8") == "Assessment instructions.\n"
    finally:
        reset_logging()


def test_settings_page_activates_valid_template_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()

    try:
        app.switch_page("pages/settings.py").run()
        app.file_uploader[2].upload(
            "english-template.docx",
            make_docx("English template"),
        )
        app.button(
            key=("FormSubmitter:replace_reference_asset_cv-template-en-Validate and store")
        ).click().run()

        assert not app.exception
        assert app.success[0].value == "'cv-template-en' version 1 is active and READY."
        overview_table = app.dataframe[0].value
        template = overview_table.loc[overview_table["Asset key"] == "cv-template-en"].iloc[0]
        assert template["Version / count"] == "v1"
        assert template["Status"] == "READY"
        assert template["Active"] == "Yes"
        assert (data_dir / "reference" / "templates" / "cv-template-en-v0001.docx").exists()
    finally:
        reset_logging()


def test_settings_page_requires_a_docx_before_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()

    try:
        app.switch_page("pages/settings.py").run()
        app.button(
            key=("FormSubmitter:replace_reference_asset_document-a-Upload and activate with OpenAI")
        ).click().run()

        assert not app.exception
        assert app.error[0].value == "Choose a DOCX file."
    finally:
        reset_logging()


def test_settings_page_uploads_and_activates_document_a(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()
    active_content = make_docx("Active Document A")
    active_path = data_dir / "reference" / "document_a" / "document-a-v0001.docx"
    active_path.write_bytes(active_content)
    database = get_database(data_dir / "database" / "job_application_copilot.db")
    with database.session() as session:
        session.add(
            ReferenceAsset(
                asset_key="document-a",
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document A",
                version=1,
                file_path="document_a/document-a-v0001.docx",
                file_hash="hash-document-a-v1",
                processing_status=ReferenceAssetProcessingStatus.READY,
                is_active=True,
            )
        )

    def activate(
        service: DocumentAProcessingService,
        version: int,
        operation: object,
    ) -> ReferenceAsset:
        del operation
        with service.database.session() as session:
            repository = ReferenceAssetRepository(session)
            previous = repository.get_active("document-a")
            candidate = repository.require_version("document-a", version)
            if previous is not None:
                previous.is_active = False
            candidate.openai_file_id = "file_a_2"
            candidate.processing_status = ReferenceAssetProcessingStatus.READY
            candidate.is_active = True
            session.flush()
            return candidate

    monkeypatch.setattr(DocumentAProcessingService, "_upload", activate)

    try:
        app.switch_page("pages/settings.py").run()
        app.file_uploader[0].upload(
            "document-a-replacement.docx",
            make_docx("Replacement Document A"),
        )
        app.button(
            key=(
                "FormSubmitter:replace_reference_asset_document-a-Replace and activate with OpenAI"
            )
        ).click().run()

        assert not app.exception
        assert app.success[0].value == "'document-a' version 2 is active and READY."
        overview_table = app.dataframe[0].value
        document_rows = overview_table.loc[overview_table["Asset key"] == "document-a"]
        assert document_rows["Role"].tolist() == ["Active input"]
        assert document_rows["Version / count"].tolist() == ["v2"]
        assert document_rows["Status"].tolist() == ["READY"]
        assert document_rows["Active"].tolist() == ["Yes"]
        assert active_path.read_bytes() == active_content
    finally:
        reset_logging()


def test_settings_page_reports_document_a_upload_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()

    def fail_upload(
        service: DocumentAProcessingService,
        version: int,
        operation: object,
    ) -> ReferenceAsset:
        del service, version, operation
        raise DocumentAProcessingError("OpenAI could not be reached after the configured retries.")

    monkeypatch.setattr(DocumentAProcessingService, "_upload", fail_upload)

    try:
        app.switch_page("pages/settings.py").run()
        app.file_uploader[0].upload(
            "document-a.docx",
            make_docx("Document A"),
        )
        app.button(
            key=("FormSubmitter:replace_reference_asset_document-a-Upload and activate with OpenAI")
        ).click().run()

        assert not app.exception
        assert app.error[0].value == (
            "Document A could not be activated: "
            "OpenAI could not be reached after the configured retries. "
            "Any existing active version remains in use."
        )
    finally:
        reset_logging()


def test_settings_page_uploads_processes_and_activates_document_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()

    def activate(
        service: DocumentBProcessingService,
        version: int,
        operation: object,
    ) -> ReferenceAsset:
        del operation
        with service.database.session() as session:
            candidate = ReferenceAssetRepository(session).require_version(
                "document-b",
                version,
            )
            candidate.openai_file_id = "file_b"
            candidate.openai_vector_store_id = "vs_b"
            candidate.processing_status = ReferenceAssetProcessingStatus.READY
            candidate.is_active = True
            session.flush()
            return candidate

    monkeypatch.setattr(DocumentBProcessingService, "_process", activate)

    try:
        app.switch_page("pages/settings.py").run()
        initial_button_key = (
            "FormSubmitter:replace_reference_asset_document-b-Upload and activate with OpenAI"
        )
        app.file_uploader[1].upload(
            "document-b.docx",
            make_docx("Document B"),
        )
        app.button(key=initial_button_key).click().run()

        assert not app.exception
        assert app.success[0].value == "'document-b' version 1 is active and READY."
        overview_table = app.dataframe[0].value
        document_b = overview_table.loc[overview_table["Asset key"] == "document-b"].iloc[0]
        assert document_b["Status"] == "READY"
        assert document_b["Active"] == "Yes"
        assert app.button(
            key=(
                "FormSubmitter:replace_reference_asset_document-b-Replace and activate with OpenAI"
            )
        )
    finally:
        reset_logging()


def test_settings_page_processes_and_activates_pending_document_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()
    database = get_database(data_dir / "database" / "job_application_copilot.db")
    with database.session() as session:
        session.add(
            ReferenceAsset(
                asset_key="document-b",
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document B",
                version=1,
                file_path="document_b/document-b-v0001.docx",
                file_hash="hash-document-b",
                processing_status=ReferenceAssetProcessingStatus.PENDING,
            )
        )

    def activate(
        service: DocumentBProcessingService,
        version: int,
    ) -> ReferenceAsset:
        with service.database.session() as session:
            candidate = ReferenceAssetRepository(session).require_version(
                "document-b",
                version,
            )
            candidate.openai_file_id = "file_b"
            candidate.openai_vector_store_id = "vs_b"
            candidate.processing_status = ReferenceAssetProcessingStatus.READY
            candidate.is_active = True
            session.flush()
            return candidate

    monkeypatch.setattr(DocumentBProcessingService, "process", activate)

    try:
        app.switch_page("pages/settings.py").run()

        assert app.button(key=DOCUMENT_B_PROCESSING_BUTTON_KEY)
        assert any(
            caption.value.startswith("Document B v1 is PENDING and not active.")
            for caption in app.caption
        )

        app.button(key=DOCUMENT_B_PROCESSING_BUTTON_KEY).click().run()

        assert not app.exception
        assert app.success[0].value == "Document B version 1 is active and READY."
        overview_table = app.dataframe[0].value
        document_b = overview_table.loc[overview_table["Asset key"] == "document-b"].iloc[0]
        assert document_b["Status"] == "READY"
        assert document_b["Active"] == "Yes"
    finally:
        reset_logging()


def test_settings_page_reports_document_b_processing_failure_without_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()
    database = get_database(data_dir / "database" / "job_application_copilot.db")
    with database.session() as session:
        session.add(
            ReferenceAsset(
                asset_key="document-b",
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Document B",
                version=1,
                file_path="document_b/document-b-v0001.docx",
                file_hash="hash-document-b",
                processing_status=ReferenceAssetProcessingStatus.PENDING,
            )
        )

    def fail_processing(
        service: DocumentBProcessingService,
        version: int,
    ) -> ReferenceAsset:
        del service, version
        raise DocumentBProcessingError("OpenAI could not be reached after the configured retries.")

    monkeypatch.setattr(DocumentBProcessingService, "process", fail_processing)

    try:
        app.switch_page("pages/settings.py").run()
        app.button(key=DOCUMENT_B_PROCESSING_BUTTON_KEY).click().run()

        assert not app.exception
        assert app.error[0].value == (
            "Document B processing failed: "
            "OpenAI could not be reached after the configured retries."
        )
        with database.session() as session:
            candidate = ReferenceAssetRepository(session).require_version(
                "document-b",
                1,
            )
            assert candidate.processing_status is ReferenceAssetProcessingStatus.PENDING
            assert not candidate.is_active
    finally:
        reset_logging()


def test_settings_page_cleans_inactive_remote_resources_and_preserves_active_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()
    database = get_database(data_dir / "database" / "job_application_copilot.db")
    with database.session() as session:
        session.add_all(
            [
                ReferenceAsset(
                    asset_key="document-b",
                    asset_type=ReferenceAssetType.DOCUMENT,
                    name="Document B",
                    version=1,
                    file_path="document_b/document-b-v0001.docx",
                    file_hash="hash-document-b-v1",
                    processing_status=ReferenceAssetProcessingStatus.READY,
                    is_active=False,
                    openai_file_id="file_old",
                    openai_vector_store_id="vs_old",
                    openai_vector_store_usage_bytes=8_192,
                ),
                ReferenceAsset(
                    asset_key="document-b",
                    asset_type=ReferenceAssetType.DOCUMENT,
                    name="Document B",
                    version=2,
                    file_path="document_b/document-b-v0002.docx",
                    file_hash="hash-document-b-v2",
                    processing_status=ReferenceAssetProcessingStatus.READY,
                    is_active=True,
                    openai_file_id="file_active",
                    openai_vector_store_id="vs_active",
                    openai_vector_store_usage_bytes=16_384,
                ),
            ]
        )

    def cleanup(
        service: ReferenceAssetRemoteCleanupService,
        asset_key: str,
        version: int,
    ) -> ReferenceAssetRemoteCleanupResult:
        with service.database.session() as session:
            candidate = ReferenceAssetRepository(session).require_version(
                asset_key,
                version,
            )
            candidate.openai_vector_store_id = None
            candidate.openai_vector_store_usage_bytes = None
            candidate.openai_file_id = None
        return ReferenceAssetRemoteCleanupResult(
            asset_key=asset_key,
            version=version,
            vector_store_deleted=True,
            file_deleted=True,
        )

    monkeypatch.setattr(ReferenceAssetRemoteCleanupService, "cleanup", cleanup)

    try:
        app.switch_page("pages/settings.py").run()

        assert app.button(key=REMOTE_CLEANUP_BUTTON_KEY).disabled
        cleanup_table = app.dataframe[1].value
        assert cleanup_table["Asset"].tolist() == ["Document B"]
        assert cleanup_table["Vector store"].tolist() == ["vs_old"]
        assert cleanup_table["OpenAI file"].tolist() == ["file_old"]

        app.checkbox(key="confirm_remote_cleanup_document-b_1").check().run()
        app.button(key=REMOTE_CLEANUP_BUTTON_KEY).click().run()

        assert not app.exception
        assert app.success[0].value == (
            "Deleted vector store and OpenAI file for Document B v1. "
            "The local DOCX and metadata were retained."
        )
        with database.session() as session:
            repository = ReferenceAssetRepository(session)
            cleaned = repository.require_version("document-b", 1)
            active = repository.require_version("document-b", 2)
            assert cleaned.openai_file_id is None
            assert cleaned.openai_vector_store_id is None
            assert not cleaned.is_active
            assert active.openai_file_id == "file_active"
            assert active.openai_vector_store_id == "vs_active"
            assert active.is_active
    finally:
        reset_logging()


def test_settings_page_restores_retained_version_without_creating_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()
    database = get_database(data_dir / "database" / "job_application_copilot.db")
    with database.session() as session:
        session.add_all(
            [
                ReferenceAsset(
                    asset_key="document-b",
                    asset_type=ReferenceAssetType.DOCUMENT,
                    name="Document B",
                    version=1,
                    file_path="document_b/document-b-v0001.docx",
                    file_hash="hash-document-b-v1",
                    processing_status=ReferenceAssetProcessingStatus.READY,
                    is_active=False,
                ),
                ReferenceAsset(
                    asset_key="document-b",
                    asset_type=ReferenceAssetType.DOCUMENT,
                    name="Document B",
                    version=2,
                    file_path="document_b/document-b-v0002.docx",
                    file_hash="hash-document-b-v2",
                    processing_status=ReferenceAssetProcessingStatus.READY,
                    is_active=True,
                    openai_file_id="file_current",
                    openai_vector_store_id="vs_current",
                ),
            ]
        )

    def restore(
        service: ReferenceAssetRemoteCleanupService,
        asset_key: str,
        version: int,
    ) -> ReferenceAsset:
        with service.database.session() as session:
            repository = ReferenceAssetRepository(session)
            current = repository.get_active(asset_key)
            assert current is not None
            current.is_active = False
            session.flush()
            candidate = repository.require_version(asset_key, version)
            candidate.openai_file_id = "file_restored"
            candidate.openai_vector_store_id = "vs_restored"
            candidate.processing_status = ReferenceAssetProcessingStatus.READY
            candidate.is_active = True
            session.flush()
            return candidate

    monkeypatch.setattr(ReferenceAssetRemoteCleanupService, "restore", restore)

    try:
        app.switch_page("pages/settings.py").run()
        app.button(key=REMOTE_RESTORE_BUTTON_KEY).click().run()

        assert not app.exception
        assert app.success[0].value == ("Restored Document B v1; it is active and READY.")
        with database.session() as session:
            versions = ReferenceAssetRepository(session).list_versions("document-b")
            assert len(versions) == 2
            restored = next(version for version in versions if version.version == 1)
            previous = next(version for version in versions if version.version == 2)
            assert restored.is_active
            assert restored.openai_vector_store_id == "vs_restored"
            assert not previous.is_active
            assert previous.openai_vector_store_id == "vs_current"
    finally:
        reset_logging()


def test_settings_page_adds_dynamic_french_reference_example(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()

    try:
        app.switch_page("pages/settings.py").run()
        app.text_input[0].input("French platform CV")
        app.file_uploader[4].upload(
            "french-example.docx",
            make_docx("French style example"),
        )
        app.button(
            key="FormSubmitter:replace_french_reference_example-Validate and store"
        ).click().run()

        assert not app.exception
        overview_table = app.dataframe[0].value
        example_key = "french-example-french-platform-cv"
        example = overview_table.loc[overview_table["Asset key"] == example_key].iloc[0]
        assert example["Role"] == "Active example"
        assert example["Status"] == "READY"
        assert example["Active"] == "Yes"
        assert "french-reference-examples" not in overview_table["Asset key"].tolist()
        assert any(
            caption.value == "French examples: 1/2 active and ready — MISSING."
            for caption in app.caption
        )

        app.button(key="remove_french_example").click().run()

        assert not app.exception
        assert app.success[0].value == (
            "'French platform CV' version 1 was removed from active examples."
        )
        overview_table = app.dataframe[0].value
        assert example_key not in overview_table["Asset key"].tolist()
        missing = overview_table.loc[
            overview_table["Asset key"] == "french-reference-examples"
        ].iloc[0]
        assert missing["Status"] == "MISSING"
        stored_path = data_dir / "reference" / "examples" / f"{example_key}-v0001.docx"
        assert stored_path.exists()

        app = AppTest.from_file(
            str(APP_PATH),
            default_timeout=SETTINGS_APP_TIMEOUT,
        ).run()
        app.switch_page("pages/settings.py").run()
        app.button(key="restore_french_example").click().run()

        assert not app.exception
        assert app.success[0].value == ("'French platform CV' version 1 was restored.")
        overview_table = app.dataframe[0].value
        assert example_key in overview_table["Asset key"].tolist()
        assert stored_path.exists()
    finally:
        reset_logging()


def test_settings_page_displays_populated_asset_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()
    database = get_database(data_dir / "database" / "job_application_copilot.db")
    with database.session() as session:
        session.add(
            ReferenceAsset(
                asset_key="document-a",
                asset_type=ReferenceAssetType.DOCUMENT,
                name="Career evidence",
                version=1,
                file_path="document_a/document-a-v0001.docx",
                file_hash="hash-document-a",
                processing_status=ReferenceAssetProcessingStatus.READY,
                is_active=True,
                uploaded_at=datetime(2026, 7, 26, 11, 30, 45),
                updated_at=datetime(2026, 7, 26, 11, 30, 45),
            )
        )

    try:
        app.switch_page("pages/settings.py").run()

        assert not app.exception
        overview_table = app.dataframe[0].value
        document_a = overview_table.loc[overview_table["Asset key"] == "document-a"].iloc[0]
        assert document_a["Name"] == "Career evidence"
        assert document_a["Stored filename"] == "document-a-v0001.docx"
        assert document_a["Version / count"] == "v1"
        assert document_a["Uploaded"] == "2026-07-26 11:30:45 UTC"
        assert document_a["Status"] == "READY"
        assert document_a["Active"] == "Yes"
    finally:
        reset_logging()


def test_empty_jobs_dashboard_shows_add_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert app.info[0].value == "No jobs have been added yet."
        assert not app.dataframe
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
    finally:
        reset_logging()


def test_jobs_dashboard_displays_core_columns_and_tracks_selected_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        service.create(
            CreateJob(
                company="Older Ltd",
                job_title="Data Engineer",
                location=Location.FR,
                language=Language.FR,
                source="Company website",
                job_description="Build data systems.",
                date_added=date(2026, 7, 20),
            )
        )
        newer = _create_job_for_edit(service)
        app.run()

        assert not app.exception
        assert len(app.dataframe) == 1
        table = app.dataframe[0].value
        assert list(table.columns) == [
            "company",
            "job_title",
            "job_url",
            "location",
            "language",
            "source",
            "date_added",
            "updated_at",
        ]
        assert list(table["company"]) == ["Older Ltd", "Original Ltd"]
        assert table["job_url"].iloc[1] == "https://example.com/original"
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
        assert app.get("page_link")[-1].disabled

        app.session_state[JOBS_TABLE_KEY] = {"selection": {"rows": [1]}}
        app.run()

        assert app.session_state[SELECTED_JOB_IDS_KEY] == (newer.id,)
        assert app.caption[0].value == "1 job selected."
        open_selected_job = app.get("page_link")[-1]
        assert not open_selected_job.disabled
        assert open_selected_job.label == "Open selected job"
    finally:
        reset_logging()


def test_jobs_dashboard_combines_filters_clears_selection_and_resets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        service.create(
            CreateJob(
                company="Another Ltd",
                job_title="Data Engineer",
                location=Location.FR,
                language=Language.FR,
                source="Company website",
                job_description="Build data systems.",
                date_added=date(2026, 7, 20),
                application_status="Not applied",
            )
        )
        matching_job = _create_job_for_edit(service)
        app.run()

        assert app.selectbox(key=FILTER_SOURCE_KEY).options == [
            "All",
            "Company website",
            "LinkedIn",
        ]

        app.session_state[JOBS_TABLE_KEY] = {"selection": {"rows": [1]}}
        app.run()
        assert app.session_state[SELECTED_JOB_IDS_KEY] == (matching_job.id,)

        app.text_input(key=FILTER_TEXT_KEY).input(" original ").run()
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
        assert list(app.dataframe[0].value["company"]) == ["Original Ltd"]

        app.selectbox(key=FILTER_LOCATION_KEY).select(Location.UK).run()
        app.selectbox(key=FILTER_LANGUAGE_KEY).select(Language.EN).run()
        app.selectbox(key=FILTER_SOURCE_KEY).select("LinkedIn").run()
        app.selectbox(key=FILTER_USER_DECISION_KEY).select(UserDecision.PURSUE).run()
        app.text_input(key=FILTER_APPLICATION_STATUS_KEY).input("VIEW").run()

        assert not app.exception
        assert list(app.dataframe[0].value["company"]) == ["Original Ltd"]

        app.selectbox(key=FILTER_LOCATION_KEY).select(Location.FR).run()

        assert not app.dataframe
        assert app.info[0].value == "No jobs match the current filters."
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()

        app.button(key=CLEAR_FILTERS_KEY).click().run()

        assert app.text_input(key=FILTER_TEXT_KEY).value == ""
        assert app.selectbox(key=FILTER_LOCATION_KEY).value is None
        assert app.selectbox(key=FILTER_LANGUAGE_KEY).value is None
        assert app.selectbox(key=FILTER_SOURCE_KEY).value is None
        assert app.selectbox(key=FILTER_USER_DECISION_KEY).value is None
        assert app.text_input(key=FILTER_APPLICATION_STATUS_KEY).value == ""
        assert list(app.dataframe[0].value["company"]) == [
            "Another Ltd",
            "Original Ltd",
        ]
        assert len(service.list()) == 2
    finally:
        reset_logging()


def test_jobs_dashboard_database_failure_shows_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    def fail_list(self: JobService, filters: object = None) -> None:
        del self, filters
        from sqlalchemy.exc import OperationalError

        raise OperationalError("SELECT", {}, RuntimeError("private database detail"))

    monkeypatch.setattr(JobService, "list", fail_list)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.error[0].value == JOBS_LOAD_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
        assert app.session_state[SELECTED_JOB_IDS_KEY] == ()
    finally:
        reset_logging()


def test_add_job_form_uses_configured_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAC_DEFAULT_SOURCE", "Company website")
    monkeypatch.setenv("JAC_DEFAULT_LOCATION", "FR")
    monkeypatch.setenv("JAC_DEFAULT_LANGUAGE", "FR")
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        app.switch_page("pages/add_job.py").run()

        assert not app.exception
        assert app.title[0].value == "Add job"
        assert app.text_input(key="add_job_0_source").value == "Company website"
        assert app.selectbox(key="add_job_0_location").value == "FR"
        assert app.selectbox(key="add_job_0_language").value == "FR"
        assert app.selectbox(key="add_job_0_relevance_override").value is None
        assert app.date_input(key="add_job_0_date_added").value == date.today()
    finally:
        reset_logging()


def test_valid_add_job_submission_persists_and_returns_to_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        app.switch_page("pages/add_job.py").run()
        app.text_input(key="add_job_0_company").input("Example Ltd")
        app.text_input(key="add_job_0_job_title").input("Platform Engineer")
        app.text_input(key="add_job_0_job_url").input("https://example.com/job")
        app.text_area(key="add_job_0_job_description").input("Build and operate reliable systems.")
        app.text_area(key="add_job_0_general_notes").input("Initial note")
        app.selectbox(key="add_job_0_relevance_override").select(Relevance.HIGH)
        app.button(key="FormSubmitter:add_job_0_form-Save").click().run()

        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert app.success[0].value == "Saved Example Ltd — Platform Engineer."

        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        jobs = service.list()
        assert len(jobs) == 1
        assert jobs[0].company == "Example Ltd"
        assert jobs[0].job_title == "Platform Engineer"
        assert jobs[0].source == "LinkedIn"
        assert jobs[0].date_added == date.today()
        assert jobs[0].relevance_override is Relevance.HIGH
    finally:
        reset_logging()


def test_missing_required_add_job_fields_show_errors_without_saving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        app.switch_page("pages/add_job.py").run()
        app.button(key="FormSubmitter:add_job_0_form-Save").click().run()

        assert not app.exception
        assert [error.value for error in app.error] == [
            "Company is required.",
            "Job title is required.",
            "Full job description is required.",
        ]
        assert get_job_service(data_dir / "database" / "job_application_copilot.db").list() == []
    finally:
        reset_logging()


def test_duplicate_job_url_shows_useful_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        app.switch_page("pages/add_job.py").run()
        _fill_required_add_job_fields(app, company="First")
        app.text_input(key="add_job_0_job_url").input("https://example.com/job")
        app.button(key="FormSubmitter:add_job_0_form-Save and add another").click().run()

        _fill_required_add_job_fields(app, company="Duplicate", version=1)
        app.text_input(key="add_job_1_job_url").input("https://example.com/job")
        app.button(key="FormSubmitter:add_job_1_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == "Another job already uses this exact URL (job 1)."
        assert (
            len(get_job_service(data_dir / "database" / "job_application_copilot.db").list()) == 1
        )
    finally:
        reset_logging()


def test_cancel_add_job_returns_to_jobs_without_saving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    try:
        app.switch_page("pages/add_job.py").run()
        _fill_required_add_job_fields(app)
        app.button(key="FormSubmitter:add_job_0_form-Cancel").click().run()

        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert get_job_service(data_dir / "database" / "job_application_copilot.db").list() == []
    finally:
        reset_logging()


def test_database_failure_shows_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    def fail_create(self: JobService, command: object) -> None:
        del self, command
        from sqlalchemy.exc import OperationalError

        raise OperationalError("INSERT", {}, RuntimeError("private database detail"))

    try:
        app.switch_page("pages/add_job.py").run()
        _fill_required_add_job_fields(app)
        monkeypatch.setattr(JobService, "create", fail_create)
        app.button(key="FormSubmitter:add_job_0_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == SAVE_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
    finally:
        reset_logging()


def _fill_required_add_job_fields(
    app: AppTest,
    company: str = "Example Ltd",
    version: int = 0,
) -> None:
    app.text_input(key=f"add_job_{version}_company").input(company)
    app.text_input(key=f"add_job_{version}_job_title").input("Platform Engineer")
    app.text_area(key=f"add_job_{version}_job_description").input(
        "Build and operate reliable systems."
    )


def test_job_details_form_loads_existing_values_and_persists_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        job = _create_job_for_edit(service)
        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()

        assert not app.exception
        assert app.title[0].value == "Job details"
        assert app.subheader[0].value == "Edit job"
        assert app.text_input(key=f"edit_job_{job.id}_company").value == "Original Ltd"
        assert app.text_input(key=f"edit_job_{job.id}_job_title").value == "Original title"
        assert app.selectbox(key=f"edit_job_{job.id}_location").value == "UK"
        assert app.selectbox(key=f"edit_job_{job.id}_language").value == "EN"
        assert app.selectbox(key=f"edit_job_{job.id}_relevance_override").value is None
        assert app.text_input(key=f"edit_job_{job.id}_source").value == "LinkedIn"
        assert (
            app.text_input(key=f"edit_job_{job.id}_job_url").value == "https://example.com/original"
        )
        assert (
            app.text_area(key=f"edit_job_{job.id}_job_description").value == "Original description"
        )
        assert app.date_input(key=f"edit_job_{job.id}_date_added").value == date(2026, 7, 1)
        assert app.text_area(key=f"edit_job_{job.id}_general_notes").value == "Original notes"

        app.text_input(key=f"edit_job_{job.id}_company").input("Updated Ltd")
        app.text_input(key=f"edit_job_{job.id}_job_title").input("Updated title")
        app.selectbox(key=f"edit_job_{job.id}_location").select("FR")
        app.selectbox(key=f"edit_job_{job.id}_language").select("FR")
        app.selectbox(key=f"edit_job_{job.id}_relevance_override").select(Relevance.MEDIUM)
        app.text_input(key=f"edit_job_{job.id}_source").input("Company website")
        app.text_input(key=f"edit_job_{job.id}_job_url").input("https://example.com/updated")
        app.text_area(key=f"edit_job_{job.id}_job_description").input("Updated description")
        app.date_input(key=f"edit_job_{job.id}_date_added").set_value(date(2026, 7, 20))
        app.text_area(key=f"edit_job_{job.id}_general_notes").input("Updated notes")
        app.button(key=f"FormSubmitter:edit_job_{job.id}_form-Save").click().run()

        assert not app.exception
        assert app.title[0].value == "Jobs"
        assert app.success[0].value == "Saved Updated Ltd — Updated title."
        updated = service.get(job.id)
        assert updated is not None
        assert updated.company == "Updated Ltd"
        assert updated.job_title == "Updated title"
        assert updated.location is Location.FR
        assert updated.language is Language.FR
        assert updated.relevance_override is Relevance.MEDIUM
        assert updated.source == "Company website"
        assert updated.job_url == "https://example.com/updated"
        assert updated.job_description == "Updated description"
        assert updated.date_added == date(2026, 7, 20)
        assert updated.general_notes == "Updated notes"
        assert updated.user_decision is UserDecision.PURSUE
        assert updated.application_status == "Interview"
        assert updated.next_action == "Prepare interview"
    finally:
        reset_logging()


def test_cancel_job_edit_returns_to_jobs_without_updating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        job = _create_job_for_edit(service)
        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()
        app.text_input(key=f"edit_job_{job.id}_company").input("Must not persist")
        app.button(key=f"FormSubmitter:edit_job_{job.id}_form-Cancel").click().run()

        assert not app.exception
        assert app.title[0].value == "Jobs"
        stored = service.get(job.id)
        assert stored is not None
        assert stored.company == "Original Ltd"
    finally:
        reset_logging()


@pytest.mark.parametrize(
    ("job_id", "expected_message"),
    [
        (None, "A job ID is required."),
        ("abc", "The job ID must be a positive integer."),
        ("0", "The job ID must be a positive integer."),
        ("999", "Job 999 does not exist."),
    ],
)
def test_job_details_rejects_missing_invalid_or_unknown_job_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_id: str | None,
    expected_message: str,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        if job_id is not None:
            app.query_params["job_id"] = job_id
        app.switch_page("pages/job_details.py").run()

        assert not app.exception
        assert app.title[0].value == "Job details"
        assert app.error[0].value == expected_message
        assert not app.subheader
    finally:
        reset_logging()


def test_job_edit_rejects_another_jobs_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        first = _create_job_for_edit(service)
        second = service.create(
            CreateJob(
                company="Second Ltd",
                job_title="Second title",
                location=Location.FR,
                language=Language.FR,
                source="Company website",
                job_url="https://example.com/second",
                job_description="Second description",
                date_added=date(2026, 7, 2),
            )
        )
        app.query_params["job_id"] = str(second.id)
        app.switch_page("pages/job_details.py").run()
        app.text_input(key=f"edit_job_{second.id}_job_url").input(first.job_url or "")
        app.button(key=f"FormSubmitter:edit_job_{second.id}_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == f"Another job already uses this exact URL (job {first.id})."
        stored = service.get(second.id)
        assert stored is not None
        assert stored.job_url == "https://example.com/second"
    finally:
        reset_logging()


def test_job_load_database_failure_shows_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    def fail_get(self: JobService, job_id: int) -> None:
        del self, job_id
        from sqlalchemy.exc import OperationalError

        raise OperationalError("SELECT", {}, RuntimeError("private database detail"))

    try:
        monkeypatch.setattr(JobService, "get", fail_get)
        app.query_params["job_id"] = "1"
        app.switch_page("pages/job_details.py").run()

        assert not app.exception
        assert app.error[0].value == LOAD_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
    finally:
        reset_logging()


def test_job_deleted_before_save_rerun_shows_useful_load_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        job = _create_job_for_edit(service)
        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()
        service.delete(job.id)
        app.button(key=f"FormSubmitter:edit_job_{job.id}_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == f"Job {job.id} does not exist."
    finally:
        reset_logging()


def test_job_update_database_failure_shows_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH)).run()

    def fail_update(self: JobService, job_id: int, command: object) -> None:
        del self, job_id, command
        from sqlalchemy.exc import OperationalError

        raise OperationalError("UPDATE", {}, RuntimeError("private database detail"))

    try:
        service = get_job_service(data_dir / "database" / "job_application_copilot.db")
        job = _create_job_for_edit(service)
        app.query_params["job_id"] = str(job.id)
        app.switch_page("pages/job_details.py").run()
        monkeypatch.setattr(JobService, "update", fail_update)
        app.button(key=f"FormSubmitter:edit_job_{job.id}_form-Save").click().run()

        assert not app.exception
        assert app.error[0].value == SAVE_ERROR_MESSAGE
        assert "private database detail" not in app.error[0].value
    finally:
        reset_logging()


def _create_job_for_edit(service: JobService) -> Job:
    return service.create(
        CreateJob(
            company="Original Ltd",
            job_title="Original title",
            location=Location.UK,
            language=Language.EN,
            source="LinkedIn",
            job_url="https://example.com/original",
            job_description="Original description",
            date_added=date(2026, 7, 1),
            general_notes="Original notes",
            user_decision=UserDecision.PURSUE,
            application_status="Interview",
            application_date=date(2026, 7, 10),
            next_action="Prepare interview",
            next_action_date=date(2026, 7, 30),
            salary_expectation="GBP 150,000",
        )
    )


def test_invalid_settings_stop_before_page_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JAC_ASSESSMENT_WORKER_COUNT", "6")
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.error
        assert "less than or equal to 5" in app.error[0].value
        assert not app.title
    finally:
        reset_logging()


def test_unexpected_page_error_is_logged_and_hidden_from_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingPage:
        def run(self) -> None:
            raise RuntimeError("private failure detail")

    monkeypatch.setenv("JAC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(st, "navigation", lambda pages: FailingPage())
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(APP_PATH)).run()

    try:
        assert not app.exception
        assert app.error[0].value == UNEXPECTED_ERROR_MESSAGE
        assert "private failure detail" not in app.error[0].value
        log_contents = (tmp_path / "data" / "logs" / "ui.log").read_text(encoding="utf-8")
        assert "unexpected_page_error" in log_contents
        assert "RuntimeError" in log_contents
    finally:
        reset_logging()
