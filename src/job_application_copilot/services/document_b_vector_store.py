"""Create, validate, and activate one vector store per Document B version."""

from __future__ import annotations

import hashlib

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    DOCUMENT_B_KEY,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.errors import ApplicationValidationError, ExternalServiceError
from job_application_copilot.llm import (
    OpenAIClientError,
    OpenAIReferenceClient,
    OpenAIVectorStore,
    OpenAIVectorStoreFile,
    OpenAIVectorStoreFileStatus,
    OpenAIVectorStoreSearchResult,
)
from job_application_copilot.observability import get_logger
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.document_b_retrieval_repository import (
    DocumentBRetrievalRepository,
)
from job_application_copilot.repositories.models import ReferenceAsset
from job_application_copilot.repositories.models.document_b_retrieval import (
    DocumentBVectorRecord,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.document_b_routing import (
    DocumentBRoutingError,
    DocumentBRoutingManifestService,
)
from job_application_copilot.services.document_b_sections import (
    DocumentBSectionError,
    DocumentBSectionRecord,
    DocumentBSectionService,
)

logger = get_logger(__name__)
DOCUMENT_B_VALIDATION_QUERY = "CV generation and positioning guidance"


class DocumentBVectorStoreError(ExternalServiceError):
    """Raised when Document B vector-store processing cannot complete."""


class DocumentBVectorStoreNotAllowedError(ApplicationValidationError):
    """Raised when an asset is not eligible for Document B indexing."""


class DocumentBVectorStoreService:
    """Coordinate OpenAI indexing with atomic local Document B activation."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        client: OpenAIReferenceClient,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client

    def process(self, asset_key: str, version: int) -> ReferenceAsset:
        """Index and activate one uploaded Document B candidate."""

        if asset_key != DOCUMENT_B_KEY:
            raise DocumentBVectorStoreNotAllowedError(
                "Only canonical Document B versions may be indexed in this vector store."
            )
        try:
            section_service = DocumentBSectionService(
                self.database,
                self.settings,
            )
            section_service.extract_and_store(version)
            DocumentBRoutingManifestService(
                self.database,
                section_service,
            ).generate(version)
        except (DocumentBSectionError, DocumentBRoutingError) as error:
            self._record_failure(asset_key, version, str(error))
            raise DocumentBVectorStoreError(str(error)) from error

        prepared = self._prepare(asset_key, version)
        if prepared.is_active:
            return prepared

        if prepared.openai_file_id is None:
            raise DocumentBVectorStoreNotAllowedError(
                f"Document B version {version} must be uploaded to OpenAI before indexing."
            )
        vector_store_id = prepared.openai_vector_store_id
        if vector_store_id is None:
            vector_store_id = self._create_and_record_store(prepared)

        try:
            usage_bytes = self._index_sections(version, prepared.id, vector_store_id)
            results = self.client.search_vector_store(
                vector_store_id=vector_store_id,
                query=DOCUMENT_B_VALIDATION_QUERY,
                filters={
                    "type": "eq",
                    "key": "document_b_version",
                    "value": str(version),
                },
            )
            self._validate_search_results(results, version)
            return self._activate(
                asset_key,
                version,
                vector_store_id=vector_store_id,
                usage_bytes=usage_bytes,
            )
        except (OpenAIClientError, DocumentBVectorStoreError) as error:
            self._record_failure(asset_key, version, str(error))
            if isinstance(error, DocumentBVectorStoreError):
                raise
            raise DocumentBVectorStoreError(str(error)) from error
        except Exception as error:
            message = "The validated Document B vector store could not be activated locally."
            self._record_failure(asset_key, version, message)
            raise DocumentBVectorStoreError(message) from error

    def _prepare(self, asset_key: str, version: int) -> ReferenceAsset:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(asset_key, version)
            self._validate_target(asset)

            if (
                asset.processing_status is ReferenceAssetProcessingStatus.READY
                and asset.is_active
                and asset.openai_vector_store_id is not None
            ):
                return asset
            if asset.processing_status is ReferenceAssetProcessingStatus.READY:
                raise DocumentBVectorStoreNotAllowedError(
                    f"Document B version {version} is already READY and cannot be reprocessed."
                )
            if asset.openai_file_id is None:
                raise DocumentBVectorStoreNotAllowedError(
                    f"Document B version {version} must be uploaded to OpenAI before indexing."
                )

            # A persisted store ID resumes polling that store. PROCESSING without one
            # resumes store creation after an interrupted local application process.
            asset.processing_status = ReferenceAssetProcessingStatus.PROCESSING
            asset.processing_error = None
            asset.is_active = False
            session.flush()
            return asset

    @staticmethod
    def _validate_target(asset: ReferenceAsset) -> None:
        if asset.asset_key != DOCUMENT_B_KEY or asset.asset_type is not ReferenceAssetType.DOCUMENT:
            raise DocumentBVectorStoreNotAllowedError(
                "Only canonical Document B versions may be indexed in this vector store."
            )

    def _create_and_record_store(self, asset: ReferenceAsset) -> str:
        try:
            created = self.client.create_vector_store(name=_vector_store_name(asset.version))
        except OpenAIClientError as error:
            self._record_failure(asset.asset_key, asset.version, str(error))
            raise DocumentBVectorStoreError(str(error)) from error

        try:
            self._record_vector_store_id(asset.asset_key, asset.version, created)
        except Exception as error:
            self._compensate_created_store(created.vector_store_id)
            message = "The OpenAI vector-store ID could not be saved locally."
            self._record_failure(asset.asset_key, asset.version, message)
            raise DocumentBVectorStoreError(message) from error
        return created.vector_store_id

    def _record_vector_store_id(
        self,
        asset_key: str,
        version: int,
        created: OpenAIVectorStore,
    ) -> None:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(asset_key, version)
            if (
                asset.openai_vector_store_id is not None
                and asset.openai_vector_store_id != created.vector_store_id
            ):
                raise DocumentBVectorStoreError(
                    f"Document B version {version} already has a different vector-store ID."
                )
            asset.openai_vector_store_id = created.vector_store_id
            asset.processing_error = None
            session.flush()

    @staticmethod
    def _require_completed(indexed_file: OpenAIVectorStoreFile) -> None:
        if indexed_file.status is OpenAIVectorStoreFileStatus.COMPLETED:
            return
        detail = (
            f" with error code '{indexed_file.error_code}'"
            if indexed_file.error_code is not None
            else ""
        )
        raise DocumentBVectorStoreError(
            "OpenAI did not complete Document B indexing: "
            f"status '{indexed_file.status.value}'{detail}."
        )

    def _index_sections(self, version: int, reference_asset_id: int, vector_store_id: str) -> int:
        """Upload and attach every extracted section; never attach the full DOCX."""

        total_usage = 0
        for section in DocumentBSectionService(self.database, self.settings).list_sections(version):
            if section.heading_level == 0:
                continue
            with self.database.session() as session:
                existing = DocumentBRetrievalRepository(session).get_vector_record(
                    reference_asset_id, section.section_id
                )
            if existing is not None:
                if existing.vector_store_id != vector_store_id:
                    raise DocumentBVectorStoreError(
                        f"Document B section '{section.section_id}' belongs to another vector store."
                    )
                continue
            content = _section_source(section).encode()
            uploaded = self.client.upload_text(
                filename=_section_filename(version, section.section_id), content=content
            )
            self.client.attach_vector_store_file(
                vector_store_id=vector_store_id,
                file_id=uploaded.file_id,
                attributes={
                    "document_b_version": str(version),
                    "section_id": section.section_id,
                },
            )
            indexed_file = self.client.wait_for_vector_store_file(
                vector_store_id=vector_store_id,
                file_id=uploaded.file_id,
                timeout_seconds=self.settings.openai_vector_store_timeout_seconds,
            )
            self._require_completed(indexed_file)
            total_usage += indexed_file.usage_bytes
            with self.database.session() as session:
                DocumentBRetrievalRepository(session).add_vector_record(
                    DocumentBVectorRecord(
                        reference_asset_id=reference_asset_id,
                        section_id=section.section_id,
                        content_hash="sha256:" + hashlib.sha256(content).hexdigest(),
                        openai_file_id=uploaded.file_id,
                        vector_store_id=vector_store_id,
                    )
                )
        return total_usage

    @staticmethod
    def _validate_search_results(
        results: tuple[OpenAIVectorStoreSearchResult, ...],
        expected_version: int,
    ) -> None:
        if any(
            result.text.strip()
            and result.attributes.get("document_b_version") == str(expected_version)
            and result.attributes.get("section_id")
            for result in results
        ):
            return
        raise DocumentBVectorStoreError(
            "OpenAI completed indexing but validation search returned no Document B content."
        )

    def _activate(
        self,
        asset_key: str,
        version: int,
        *,
        vector_store_id: str,
        usage_bytes: int,
    ) -> ReferenceAsset:
        with self.database.session() as session:
            repository = ReferenceAssetRepository(session)
            candidate = repository.require_version(asset_key, version)
            if candidate.is_active:
                return candidate
            if candidate.openai_vector_store_id != vector_store_id:
                raise DocumentBVectorStoreError(
                    f"Document B version {version} no longer references the validated vector store."
                )

            # Resolution is deliberately checked again at the activation boundary.
            routes = DocumentBRoutingManifestService(
                self.database,
                DocumentBSectionService(self.database, self.settings),
            ).list_current_routes(version)
            if not routes:
                raise DocumentBVectorStoreError(
                    f"Document B version {version} has no configured CV lanes."
                )

            previous = repository.get_active(DOCUMENT_B_KEY)
            if previous is not None and previous.id != candidate.id:
                previous.is_active = False
                session.flush()

            candidate.processing_status = ReferenceAssetProcessingStatus.READY
            candidate.processing_error = None
            candidate.openai_vector_store_usage_bytes = usage_bytes
            candidate.is_active = True
            session.flush()
            return candidate

    def _record_failure(self, asset_key: str, version: int, message: str) -> None:
        try:
            with self.database.session() as session:
                asset = ReferenceAssetRepository(session).require_version(asset_key, version)
                if not asset.is_active:
                    asset.processing_status = ReferenceAssetProcessingStatus.FAILED
                    asset.processing_error = message[:2048]
                    session.flush()
        except Exception:
            logger.exception(
                "document_b_vector_store_failure_status_not_saved asset_key=%s version=%s",
                asset_key,
                version,
            )

    def _compensate_created_store(self, vector_store_id: str) -> None:
        try:
            self.client.delete_vector_store(vector_store_id)
        except OpenAIClientError:
            logger.exception(
                "document_b_vector_store_compensation_failed vector_store_id=%s",
                vector_store_id,
            )


def _vector_store_name(version: int) -> str:
    return f"job-application-copilot-document-b-v{version:04d}"


def _section_filename(version: int, section_id: str) -> str:
    digest = hashlib.sha256(section_id.encode()).hexdigest()[:16]
    return f"document-b-v{version:04d}-section-{digest}.txt"


def _section_source(section: DocumentBSectionRecord) -> str:
    heading = section.heading_title
    text = section.section_text
    return f"{heading}\n\n{text}".strip()
