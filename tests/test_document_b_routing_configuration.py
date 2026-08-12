"""Tests for local authoring validation of Document B routing YAML."""

from pathlib import Path

import pytest
import yaml
from conftest import install_document_b_routing_config, make_routable_document_b

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import ReferenceAssetType
from job_application_copilot.repositories import create_database
from job_application_copilot.services import (
    DocumentBRoutingConfigurationError,
    DocumentBRoutingConfigurationService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database


@pytest.fixture
def routing_context(
    tmp_path: Path,
) -> tuple[DocumentBRoutingConfigurationService, AppSettings, int]:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    install_document_b_routing_config(settings)
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    storage = ReferenceAssetStorageService(database, settings)
    version = storage.store(
        filename="document-b.docx",
        content=make_routable_document_b(),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    ).version
    try:
        yield DocumentBRoutingConfigurationService(database, settings), settings, version
    finally:
        database.dispose()


def test_validates_and_saves_routes_against_retained_candidate(
    routing_context: tuple[DocumentBRoutingConfigurationService, AppSettings, int],
) -> None:
    service, settings, version = routing_context
    content = service.load_text().replace(
        "routing_config_version: 1.0.0", "routing_config_version: 2.0.0"
    )

    service.validate_and_save(version, content)

    assert settings.document_b_routing_config_path.read_text(encoding="utf-8") == content
    assert service.headings(version)[0].heading_title == "CV generation workflow and rules"


def test_rejects_invalid_heading_without_replacing_current_yaml(
    routing_context: tuple[DocumentBRoutingConfigurationService, AppSettings, int],
) -> None:
    service, settings, version = routing_context
    original = service.load_text()
    invalid = yaml.safe_load(original)
    invalid["section_catalog"]["guardrails.talk_to_data_mvp"]["heading_path"][-1] = "Missing"

    with pytest.raises(
        DocumentBRoutingConfigurationError, match="cannot resolve exact heading path"
    ):
        service.validate_and_save(version, yaml.safe_dump(invalid, sort_keys=False))

    assert settings.document_b_routing_config_path.read_text(encoding="utf-8") == original
