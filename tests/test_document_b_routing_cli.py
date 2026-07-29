"""Tests for the read-only Document B routing developer command."""

import sys
from pathlib import Path

from conftest import install_document_b_routing_config, make_routable_document_b

from job_application_copilot.config import AppSettings
from job_application_copilot.domain import (
    ReferenceAssetProcessingStatus,
    ReferenceAssetType,
)
from job_application_copilot.repositories import create_database
from job_application_copilot.repositories.document_b_routing_repository import (
    DocumentBRoutingRepository,
)
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services import (
    DocumentBRoutingManifestService,
    DocumentBSectionService,
    ReferenceAssetStorageService,
)
from job_application_copilot.services.database_bootstrap import initialize_database
from job_application_copilot.services.document_b_routing_cli import main


def test_cli_resolves_lane_without_changing_routing_data(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    install_document_b_routing_config(settings)
    settings.database_path.parent.mkdir(parents=True)
    initialize_database(settings.database_path)
    database = create_database(settings.database_path)
    stored = ReferenceAssetStorageService(database, settings).store(
        filename="document-b.docx",
        content=make_routable_document_b(),
        asset_key="document-b",
        asset_type=ReferenceAssetType.DOCUMENT,
        name="Document B",
    )
    service = DocumentBRoutingManifestService(
        database,
        DocumentBSectionService(database, settings),
    )
    service.generate(stored.version)
    with database.session() as session:
        asset = ReferenceAssetRepository(session).require_version("document-b", stored.version)
        asset.processing_status = ReferenceAssetProcessingStatus.READY
        asset.is_active = True
    with database.session() as session:
        before = len(DocumentBRoutingRepository(session).list_for_asset(stored.id))
    database.dispose()

    monkeypatch.setenv("JAC_DATA_DIR", str(settings.data_dir))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "document-b-routing",
            "--document-b-version",
            str(stored.version),
            "--lane",
            "HEAD_OF_SOLUTIONS_ARCHITECTURE",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "Incomplete primary lanes (not selectable as primary):" in output
    assert "HEAD_OF_DATA_PLATFORMS_TECHNOLOGY" in output
    assert "Optional supporting-only content (not selectable as primary):" in output
    assert "Lane: HEAD_OF_SOLUTIONS_ARCHITECTURE" in output
    assert "SUMMARY" in output
    assert "OPTIONAL" in output

    database = create_database(settings.database_path)
    try:
        with database.session() as session:
            after = len(DocumentBRoutingRepository(session).list_for_asset(stored.id))
        assert after == before
    finally:
        database.dispose()
