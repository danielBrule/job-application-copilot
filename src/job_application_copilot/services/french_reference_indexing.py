"""Index and retrieve French CV style references without making factual claims."""

from __future__ import annotations

import hashlib

from job_application_copilot.config import AppSettings
from job_application_copilot.documents import extract_french_reference_text
from job_application_copilot.domain import (
    FrenchReferencePassage,
    FrenchReferenceRetrievalRequest,
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.errors import ExternalServiceError
from job_application_copilot.llm import (
    OpenAIClient,
    OpenAIClientError,
    OpenAIReferenceClient,
    OpenAIVectorStoreFileStatus,
    OpenAIVectorStoreOperations,
)
from job_application_copilot.repositories import Database
from job_application_copilot.repositories.french_reference_retrieval_repository import (
    FrenchReferenceRetrievalRepository,
)
from job_application_copilot.repositories.models import FrenchReferenceVectorSource, ReferenceAsset
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
    ReferenceAssetVersionNotFoundError,
)
from job_application_copilot.services.reference_asset_storage import ReferenceAssetStorageService
from job_application_copilot.services.remote_reference_operation import (
    OpenAIClientFactory,
    remote_reference_operation,
)


class FrenchReferenceIndexingError(ExternalServiceError):
    """Safe failure while making a French example searchable."""


class FrenchReferenceRetrievalError(ExternalServiceError):
    """Safe failure while querying the French style-reference collection."""


class FrenchReferenceProcessingService:
    """Store and index a French example in one explicit user-triggered workflow."""

    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        *,
        client_factory: OpenAIClientFactory = OpenAIClient.from_settings,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client_factory = client_factory

    def replace_and_process(self, *, filename: str, content: bytes, name: str) -> ReferenceAsset:
        with remote_reference_operation(
            self.settings, self.client_factory, FrenchReferenceIndexingError
        ) as operation:
            asset = ReferenceAssetStorageService(
                self.database, self.settings
            ).replace_french_example(filename=filename, content=content, name=name)
            FrenchReferenceIndexingService(self.database, self.settings, operation.client).process(
                asset.asset_key, asset.version
            )
            with self.database.session() as session:
                return ReferenceAssetRepository(session).require_version(
                    asset.asset_key, asset.version
                )


class FrenchReferenceIndexingService:
    """Create verified sources in one shared vector store and activate them on success."""

    def __init__(
        self, database: Database, settings: AppSettings, client: OpenAIReferenceClient
    ) -> None:
        self.database = database
        self.settings = settings
        self.client = client

    def process(self, asset_key: str, version: int) -> None:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(asset_key, version)
            self._validate_target(asset.asset_type, asset.language_code)
            if asset.is_active and asset.processing_status is ReferenceAssetProcessingStatus.READY:
                return
            if asset.file_path is None:
                raise FrenchReferenceIndexingError("The French reference has no local DOCX file.")
            content = (self.settings.reference_folder / asset.file_path).read_bytes()
            asset.processing_status = ReferenceAssetProcessingStatus.PROCESSING
            asset.processing_error = None
            asset_id = asset.id

        try:
            source_text = extract_french_reference_text(content)
            store_id = self._ensure_store()
            with self.database.session() as session:
                existing = FrenchReferenceRetrievalRepository(session).get_source(asset_id)
            if existing is None:
                uploaded = self.client.upload_text(
                    filename=f"{asset_key}-v{version:04d}-style-reference.txt",
                    content=source_text.encode(),
                )
                self.client.attach_vector_store_file(
                    vector_store_id=store_id,
                    file_id=uploaded.file_id,
                    attributes={
                        "asset_key": asset_key,
                        "reference_version": str(version),
                        "style_reference_only": "true",
                    },
                )
                indexed = self.client.wait_for_vector_store_file(
                    vector_store_id=store_id,
                    file_id=uploaded.file_id,
                    timeout_seconds=self.settings.openai_vector_store_timeout_seconds,
                )
                if indexed.status is not OpenAIVectorStoreFileStatus.COMPLETED:
                    raise FrenchReferenceIndexingError(
                        f"OpenAI did not complete French-reference indexing: {indexed.status.value}."
                    )
                with self.database.session() as session:
                    FrenchReferenceRetrievalRepository(session).add_source(
                        FrenchReferenceVectorSource(
                            reference_asset_id=asset_id,
                            vector_store_id=store_id,
                            openai_file_id=uploaded.file_id,
                            content_hash="sha256:"
                            + hashlib.sha256(source_text.encode()).hexdigest(),
                        )
                    )
            self._activate(asset_key, version)
        except (OSError, ValueError, OpenAIClientError, FrenchReferenceIndexingError) as error:
            self._fail(asset_key, version, str(error))
            if isinstance(error, FrenchReferenceIndexingError):
                raise
            raise FrenchReferenceIndexingError(str(error)) from error

    @staticmethod
    def _validate_target(asset_type: ReferenceAssetType, language_code: str | None) -> None:
        if asset_type is not ReferenceAssetType.REFERENCE_EXAMPLE or language_code != "fr":
            raise FrenchReferenceIndexingError("Only French reference examples may be indexed.")

    def _ensure_store(self) -> str:
        with self.database.session() as session:
            repository = FrenchReferenceRetrievalRepository(session)
            if store := repository.get_store():
                return store.vector_store_id
        created = self.client.create_vector_store(
            name="job-application-copilot-french-style-references"
        )
        with self.database.session() as session:
            repository = FrenchReferenceRetrievalRepository(session)
            if store := repository.get_store():
                return store.vector_store_id
            return repository.add_store(created.vector_store_id).vector_store_id

    def _activate(self, asset_key: str, version: int) -> None:
        with self.database.session() as session:
            repository = ReferenceAssetRepository(session)
            asset = repository.require_version(asset_key, version)
            previous = repository.get_active(asset_key)
            if previous is not None and previous.id != asset.id:
                previous.is_active = False
            asset.processing_status = ReferenceAssetProcessingStatus.READY
            asset.processing_error = None
            asset.is_active = True

    def _fail(self, asset_key: str, version: int, detail: str) -> None:
        with self.database.session() as session:
            asset = ReferenceAssetRepository(session).require_version(asset_key, version)
            if not asset.is_active:
                asset.processing_status = ReferenceAssetProcessingStatus.FAILED
                asset.processing_error = detail[:2048]


class FrenchReferenceRetrievalService:
    """Return only locally verified, active French style-reference passages."""

    def __init__(self, database: Database, client: OpenAIVectorStoreOperations) -> None:
        self.database = database
        self.client = client

    def retrieve(
        self, request: FrenchReferenceRetrievalRequest
    ) -> tuple[FrenchReferencePassage, ...]:
        with self.database.session() as session:
            store = FrenchReferenceRetrievalRepository(session).get_store()
        if store is None:
            return ()
        try:
            results = self.client.search_vector_store(
                vector_store_id=store.vector_store_id,
                query=request.query,
                max_num_results=request.result_limit,
                filters={"type": "eq", "key": "style_reference_only", "value": "true"},
            )
        except OpenAIClientError as error:
            raise FrenchReferenceRetrievalError(str(error)) from error
        verified: list[FrenchReferencePassage] = []
        with self.database.session() as session:
            sources = FrenchReferenceRetrievalRepository(session)
            assets = ReferenceAssetRepository(session)
            for result in results:
                key = str(result.attributes.get("asset_key", ""))
                version_text = str(result.attributes.get("reference_version", ""))
                if result.attributes.get("style_reference_only") not in ("true", True):
                    continue
                try:
                    asset = assets.require_version(key, int(version_text))
                except (ValueError, ReferenceAssetVersionNotFoundError):
                    continue
                source = sources.get_source(asset.id)
                if (
                    source is None
                    or source.openai_file_id != result.file_id
                    or source.vector_store_id != store.vector_store_id
                    or not asset.is_active
                    or asset.processing_status is not ReferenceAssetProcessingStatus.READY
                ):
                    continue
                text = result.text.strip()
                if text:
                    verified.append(
                        FrenchReferencePassage(
                            text=text,
                            score=result.score,
                            reference_asset_id=asset.id,
                            asset_key=asset.asset_key,
                            version=asset.version,
                            name=asset.name,
                            source_metadata={str(k): str(v) for k, v in result.attributes.items()},
                        )
                    )
        return tuple(verified[: request.result_limit])
