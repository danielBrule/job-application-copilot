"""French CV examples are searchable style references, never evidence sources."""

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from docx import Document

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    FrenchReferenceRetrievalRequest,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.llm import (
    OpenAIVectorStore,
    OpenAIVectorStoreFile,
    OpenAIVectorStoreFileStatus,
    OpenAIVectorStoreSearchResult,
    UploadedOpenAIFile,
)
from job_application_copilot.repositories import create_database
from job_application_copilot.repositories.models import FrenchReferenceVectorSource
from job_application_copilot.services import (
    FrenchReferenceIndexingService,
    FrenchReferenceRetrievalService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


def make_docx(*paragraphs: str) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_indexes_and_returns_verified_style_only_passages(tmp_path: Path) -> None:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        asset = ReferenceAssetStorageService(database, settings).store(
            filename="reference.docx",
            content=make_docx(
                "Profil : architecte de solutions.", "Formation : Master en informatique."
            ),
            asset_key="french-example-platform-cv",
            asset_type=ReferenceAssetType.REFERENCE_EXAMPLE,
            name="French platform CV",
            language_code="fr",
        )
        client = Mock()
        client.create_vector_store.return_value = OpenAIVectorStore(
            vector_store_id="vs_french", status="completed", usage_bytes=0, request_id="req_store"
        )
        client.upload_text.return_value = UploadedOpenAIFile(
            file_id="file_french", filename="reference.txt", size_bytes=100, request_id="req_file"
        )
        client.wait_for_vector_store_file.return_value = OpenAIVectorStoreFile(
            file_id="file_french",
            vector_store_id="vs_french",
            status=OpenAIVectorStoreFileStatus.COMPLETED,
            usage_bytes=100,
            error_code=None,
            request_id="req_poll",
        )

        FrenchReferenceIndexingService(database, settings, client).process(
            asset.asset_key, asset.version
        )

        client.attach_vector_store_file.assert_called_once_with(
            vector_store_id="vs_french",
            file_id="file_french",
            attributes={
                "asset_key": asset.asset_key,
                "reference_version": "1",
                "style_reference_only": "true",
            },
        )
        with database.session() as session:
            stored = session.get(type(asset), asset.id)
            assert stored is not None and stored.is_active
            assert stored.processing_status is ReferenceAssetProcessingStatus.READY
            source = session.query(FrenchReferenceVectorSource).one()
            assert source.openai_file_id == "file_french"

        client.search_vector_store.return_value = (
            OpenAIVectorStoreSearchResult(
                file_id="file_french",
                filename="reference.txt",
                score=0.9,
                text="Formation : Master en informatique.",
                attributes={
                    "asset_key": asset.asset_key,
                    "reference_version": "1",
                    "style_reference_only": "true",
                },
            ),
            OpenAIVectorStoreSearchResult(
                file_id="file_unknown",
                filename="other.txt",
                score=1.0,
                text="This must not be returned.",
                attributes={
                    "asset_key": asset.asset_key,
                    "reference_version": "1",
                    "style_reference_only": "true",
                },
            ),
        )

        passages = FrenchReferenceRetrievalService(database, client).retrieve(
            FrenchReferenceRetrievalRequest(query="formation")
        )

        assert [passage.text for passage in passages] == ["Formation : Master en informatique."]
        assert passages[0].style_reference_only
        assert passages[0].source_metadata["style_reference_only"] == "true"
        assert client.search_vector_store.call_args.kwargs["filters"] == {
            "type": "eq",
            "key": "style_reference_only",
            "value": "true",
        }
    finally:
        database.dispose()
