"""Process-local dependencies shared by Streamlit pages."""

from pathlib import Path

import streamlit as st

from job_application_copilot.config import AppSettings
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.services import (
    AssessmentBatchService,
    BackgroundRunService,
    CvFileOpener,
    CvGenerationBatchService,
    CvSelectionService,
    CvService,
    CvTemplateManifestService,
    CvUploadService,
    DashboardKpiService,
    DocumentAProcessingService,
    DocumentBProcessingService,
    DocumentBRoutingConfigurationService,
    JobService,
    PromptService,
    ReferenceAssetOverviewService,
    ReferenceAssetRemoteCleanupService,
    ReferenceAssetStorageService,
)


def _dispose_database(database: Database) -> None:
    database.dispose()


@st.cache_resource(show_spinner=False, on_release=_dispose_database)
def get_database(database_path: Path) -> Database:
    """Return one database facade per configured path for this UI process."""

    return create_database(database_path)


def get_job_service(database_path: Path) -> JobService:
    """Build a job service using the UI process's shared database facade."""

    return JobService(get_database(database_path))


def get_assessment_batch_service(database_path: Path) -> AssessmentBatchService:
    """Build assessment batching over the UI process's shared database facade."""

    return AssessmentBatchService(get_database(database_path))


def get_cv_selection_service(database_path: Path) -> CvSelectionService:
    """Build CV selection over the UI process's shared database facade."""

    return CvSelectionService(get_database(database_path))


def get_cv_generation_batch_service(database_path: Path) -> CvGenerationBatchService:
    """Build CV-generation batching over the UI process's shared database facade."""

    return CvGenerationBatchService(get_database(database_path))


def get_cv_service(settings: AppSettings) -> CvService:
    return CvService(get_database(settings.database_path), settings)


def get_cv_upload_service(settings: AppSettings) -> CvUploadService:
    return CvUploadService(get_database(settings.database_path), settings)


def get_cv_file_opener(settings: AppSettings) -> CvFileOpener:
    return CvFileOpener(settings)


def get_dashboard_kpi_service(database_path: Path) -> DashboardKpiService:
    """Build global Jobs dashboard KPI aggregation over the shared database."""

    return DashboardKpiService(get_database(database_path))


def get_background_run_service(database_path: Path) -> BackgroundRunService:
    """Build background-run monitoring over the UI process database."""

    return BackgroundRunService(get_database(database_path))


def get_prompt_service(settings: AppSettings) -> PromptService:
    """Build a prompt service using shared database and configured private storage."""

    return PromptService(get_database(settings.database_path), settings)


def get_document_a_processing_service(
    settings: AppSettings,
) -> DocumentAProcessingService:
    """Build the synchronous Document A Settings workflow."""

    return DocumentAProcessingService(
        get_database(settings.database_path),
        settings,
    )


def get_document_b_processing_service(
    settings: AppSettings,
) -> DocumentBProcessingService:
    """Build the synchronous Settings workflow over shared local persistence."""

    return DocumentBProcessingService(
        get_database(settings.database_path),
        settings,
    )


def get_document_b_routing_configuration_service(
    settings: AppSettings,
) -> DocumentBRoutingConfigurationService:
    """Build the local, no-OpenAI Document B route-authoring workflow."""

    return DocumentBRoutingConfigurationService(
        get_database(settings.database_path),
        settings,
    )


def get_reference_asset_overview_service(
    settings: AppSettings,
) -> ReferenceAssetOverviewService:
    """Build the read-only Settings overview over shared process dependencies."""

    database = get_database(settings.database_path)
    return ReferenceAssetOverviewService(
        database,
        PromptService(database, settings),
        settings.minimum_french_reference_examples,
    )


def get_reference_asset_remote_cleanup_service(
    settings: AppSettings,
) -> ReferenceAssetRemoteCleanupService:
    """Build explicit inactive OpenAI cleanup over shared local persistence."""

    return ReferenceAssetRemoteCleanupService(
        get_database(settings.database_path),
        settings,
    )


def get_reference_asset_storage_service(
    settings: AppSettings,
) -> ReferenceAssetStorageService:
    """Build validated DOCX storage over the shared Settings database."""

    return ReferenceAssetStorageService(
        get_database(settings.database_path),
        settings,
    )


def get_cv_template_manifest_service(settings: AppSettings) -> CvTemplateManifestService:
    return CvTemplateManifestService(get_database(settings.database_path), settings)
