from datetime import datetime
from pathlib import Path

import pytest
from conftest import install_document_b_routing_config
from streamlit.testing.v1 import AppTest

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.observability import reset_logging
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DocumentAProcessingError,
    DocumentAProcessingService,
    DocumentBProcessingError,
    DocumentBProcessingService,
    FrenchReferenceProcessingService,
    PromptService,
    ReferenceAssetRemoteCleanupResult,
    ReferenceAssetRemoteCleanupService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.document_b_progress import DocumentBProcessingProgress
from job_application_copilot.ui.components.document_b_processing import (
    DOCUMENT_B_PROCESSING_BUTTON_KEY,
    DOCUMENT_B_PROCESSING_IN_PROGRESS_KEY,
    DOCUMENT_B_PROCESSING_PROGRESS_KEY,
)
from job_application_copilot.ui.components.reference_asset_remote_cleanup import (
    REMOTE_CLEANUP_BUTTON_KEY,
    REMOTE_RESTORE_BUTTON_KEY,
)
from job_application_copilot.ui.dependencies import get_database
from tests.app_test_support import APP_PATH, SETTINGS_APP_TIMEOUT, make_docx


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
        assert overview_table["Status"].tolist() == [
            "MISSING",
            "MISSING",
            "MISSING",
            "MISSING",
            "MISSING",
            "READY",
            "READY",
            "MISSING",
        ]
        labels = [expander.label for expander in app.expander]
        assert labels[:7] == [
            "Upload or replace Document A",
            "Upload or replace Document B",
            "Upload or replace French CV template",
            "Manage French CV examples",
            "Upload or replace English CV template",
            "Inactive OpenAI resources",
            "Retained local document versions",
        ]
        assert [label.split()[0] for label in labels[7:]] == ["1.", "1.", "2.", "3.", "1.", "2."]
        assert len(labels) == 13
        assert not app.expander[5].proto.expanded
        assert not app.expander[6].proto.expanded
        assert [uploader.proto.max_upload_size_mb for uploader in app.file_uploader] == [
            5,
            5,
            5,
            5,
            200,
        ]
    finally:
        reset_logging()


def test_settings_page_offers_routing_review_for_retained_document_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    settings = AppSettings(_env_file=None, data_dir=data_dir)
    install_document_b_routing_config(settings)
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = get_database(settings.database_path)
    ReferenceAssetStorageService(database, settings).store(
        filename="document-b.docx",
        content=make_docx("Document B"),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    )

    try:
        app = AppTest.from_file(
            str(APP_PATH),
            default_timeout=SETTINGS_APP_TIMEOUT,
        ).run()
        app.switch_page("pages/settings.py").run()

        assert not app.exception
        assert "Document B routing" in [item.value for item in app.subheader]
        assert "Review routing for Document B v1" in [item.label for item in app.expander]
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
        assert app.expander[7].label.startswith("1. Assessment prompt")
        database = get_database(data_dir / "database" / "job_application_copilot.db")
        assert PromptService(database).get_active_text("assessment") == "Assessment instructions.\n"
        assert not (data_dir / "reference" / "prompts").exists()
    finally:
        reset_logging()


def test_settings_page_confirms_valid_english_template_mapping(
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
        app.file_uploader[4].upload(
            "english-template.docx",
            make_docx("[OPENING_TITLE]"),
        )
        app.button(
            key="FormSubmitter:upload_english_template-Upload and scan placeholders"
        ).click().run()
        next(
            button
            for button in app.button
            if button.label == "Confirm template mapping and activate"
        ).click().run()

        assert not app.exception
        overview_table = app.dataframe[0].value
        template = overview_table.loc[overview_table["Asset key"] == "cv-template-en"].iloc[0]
        assert template["Version / count"] == "v1"
        assert template["Status"] == "READY"
        assert template["Active"] == "Yes"
        assert (data_dir / "reference" / "templates" / "cv-template-en-v0001.docx").exists()
    finally:
        reset_logging()


def test_settings_page_accepts_french_template_only_after_matching_english_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP_PATH), default_timeout=SETTINGS_APP_TIMEOUT).run()

    try:
        app.switch_page("pages/settings.py").run()
        app.file_uploader[2].upload("french-template.docx", make_docx("[OPENING_TITLE]"))
        app.button(key="FormSubmitter:upload_french_template-Validate and store").click().run()
        assert app.error[0].value.startswith("A confirmed active English CV template is required")

        app.file_uploader[4].upload("english-template.docx", make_docx("[OPENING_TITLE]"))
        app.button(
            key="FormSubmitter:upload_english_template-Upload and scan placeholders"
        ).click().run()
        next(
            button
            for button in app.button
            if button.label == "Confirm template mapping and activate"
        ).click().run()

        app = AppTest.from_file(str(APP_PATH), default_timeout=SETTINGS_APP_TIMEOUT).run()
        app.switch_page("pages/settings.py").run()
        app.file_uploader[2].upload("french-template.docx", make_docx("[OPENING_TITLE]"))
        app.button(key="FormSubmitter:upload_french_template-Validate and store").click().run()

        assert not app.exception
        overview_table = app.dataframe[0].value
        template = overview_table.loc[overview_table["Asset key"] == "cv-template-fr"].iloc[0]
        assert template["Version / count"] == "v1"
        assert template["Status"] == "READY"
        assert template["Active"] == "Yes"
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
        *,
        progress: object = None,
    ) -> ReferenceAsset:
        del progress
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
        *,
        progress: object = None,
    ) -> ReferenceAsset:
        del service, version, progress
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


def test_settings_page_disables_document_b_recovery_while_session_is_processing(
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
                processing_status=ReferenceAssetProcessingStatus.PROCESSING,
            )
        )

    try:
        app.session_state[DOCUMENT_B_PROCESSING_IN_PROGRESS_KEY] = True
        app.session_state[DOCUMENT_B_PROCESSING_PROGRESS_KEY] = DocumentBProcessingProgress(
            stage="indexing",
            message="Indexed Document B section 67 of 252.",
            completed_sections=67,
            total_sections=252,
        )
        app.switch_page("pages/settings.py").run()

        assert app.button(key=DOCUMENT_B_PROCESSING_BUTTON_KEY).disabled
        assert any("already running" in message.value for message in app.info)
        assert any(
            caption.value == "Indexed Document B section 67 of 252." for caption in app.caption
        )
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

    def replace_and_process(
        service: FrenchReferenceProcessingService, *, filename: str, content: bytes, name: str
    ) -> ReferenceAsset:
        asset = ReferenceAssetStorageService(
            service.database, service.settings
        ).replace_french_example(filename=filename, content=content, name=name)
        with service.database.session() as session:
            stored = ReferenceAssetRepository(session).require_version(
                asset.asset_key, asset.version
            )
            stored.processing_status = ReferenceAssetProcessingStatus.READY
            stored.is_active = True
            return stored

    monkeypatch.setattr(
        FrenchReferenceProcessingService, "replace_and_process", replace_and_process
    )

    app = AppTest.from_file(
        str(APP_PATH),
        default_timeout=SETTINGS_APP_TIMEOUT,
    ).run()

    try:
        app.switch_page("pages/settings.py").run()
        app.text_input[0].input("French platform CV")
        app.file_uploader[3].upload(
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
