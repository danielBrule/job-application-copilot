"""Opt-in integration test for a real OpenAI file upload."""

import os
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import ReferenceAssetType
from job_application_copilot.llm import OpenAIFileClient
from job_application_copilot.repositories import create_database
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    OpenAIFileUploadService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database

pytestmark = [
    pytest.mark.openai_integration,
    pytest.mark.skipif(
        os.getenv("JAC_RUN_OPENAI_INTEGRATION") != "1",
        reason="Set JAC_RUN_OPENAI_INTEGRATION=1 to contact the OpenAI Files API.",
    ),
]


def make_docx() -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph("Temporary Job Application Copilot integration test.")
    document.save(buffer)
    return buffer.getvalue()


def test_uploads_persists_and_deletes_real_openai_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = AppSettings(
        _env_file=".env",
        data_dir=data_dir,
        database_path=data_dir / "database" / "integration.db",
        reference_folder=data_dir / "reference",
    )
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    client = OpenAIFileClient.from_settings(settings)
    remote_file_id: str | None = None

    try:
        candidate = ReferenceAssetStorageService(database, settings).replace(
            filename="integration-document-b.docx",
            content=make_docx(),
            asset_key="document-b",
            asset_type=ReferenceAssetType.DOCUMENT,
            name="Document B integration test",
        )
        uploaded = OpenAIFileUploadService(database, settings, client).upload(
            candidate.asset_key,
            candidate.version,
        )
        remote_file_id = uploaded.openai_file_id

        assert remote_file_id is not None
        assert remote_file_id.startswith("file-")
        with database.session() as session:
            stored = ReferenceAssetRepository(session).require_version(
                candidate.asset_key,
                candidate.version,
            )
            assert stored.openai_file_id == remote_file_id
    finally:
        if remote_file_id is not None:
            client.delete(remote_file_id)
        client.close()
        database.dispose()
