"""Read-only developer inspection command for Document B routing."""

from __future__ import annotations

import argparse

from job_application_copilot.config import load_settings
from job_application_copilot.config.document_b_routing import (
    load_document_b_routing_config,
)
from job_application_copilot.domain import DOCUMENT_B_KEY, CvLane
from job_application_copilot.repositories import Database, create_database
from job_application_copilot.repositories.reference_asset_repository import (
    ReferenceAssetRepository,
)
from job_application_copilot.services.document_b_routing import (
    DocumentBRoutingError,
    DocumentBRoutingManifestService,
)
from job_application_copilot.services.document_b_sections import DocumentBSectionService


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect validated Document B lane routing.")
    parser.add_argument("--document-b-version", type=int)
    parser.add_argument("--lane", choices=[lane.value for lane in CvLane])
    args = parser.parse_args()

    settings = load_settings()
    database = create_database(settings.database_path)
    try:
        version = args.document_b_version or _active_version(database)
        service = DocumentBRoutingManifestService(
            database,
            DocumentBSectionService(database, settings),
        )
        config = load_document_b_routing_config()
        print(f"Document B version: {version}")
        print("Supported canonical lanes:")
        for lane in CvLane:
            print(f"  {lane.value}")
        print("Incomplete primary lanes (not selectable as primary):")
        for route_name, route in config.supporting_routes.items():
            if route.category == "INCOMPLETE_PRIMARY_LANE":
                print(f"  {route_name}")
        print("Optional supporting-only content (not selectable as primary):")
        for route_name, route in config.supporting_routes.items():
            if route.category == "OPTIONAL_SUPPORTING_CONTENT":
                print(f"  {route_name}")

        if args.lane is None:
            all_resolved = service.list_current_routes(version)
            summary = all_resolved[0].summary
            print(
                f"Routing set: {summary.routing_set_id} "
                f"config={summary.routing_config_version} "
                f"status={summary.status.value} current={summary.is_current}"
            )
            return

        lane_resolution = service.resolve(version, CvLane(args.lane))
        summary = lane_resolution.summary
        print(
            f"Routing set: {summary.routing_set_id} "
            f"config={summary.routing_config_version} "
            f"status={summary.status.value} current={summary.is_current}"
        )
        print(f"Lane: {lane_resolution.packet.lane.value}")
        for position, entry in enumerate(lane_resolution.packet.entries, start=1):
            print(
                f"{position:02d} {entry.inclusion.value:<9} {entry.role.value:<28} "
                f"{entry.logical_id} -> {entry.section_id} [{entry.heading}]"
            )
            descendants = entry.expanded_section_ids[1:]
            if descendants:
                print(f"   descendants: {', '.join(descendants)}")
    except DocumentBRoutingError as error:
        raise SystemExit(f"Document B routing unavailable: {error}") from error
    finally:
        database.dispose()


def _active_version(database: Database) -> int:
    with database.session() as session:
        active = ReferenceAssetRepository(session).get_active(DOCUMENT_B_KEY)
        if active is None:
            raise DocumentBRoutingError("There is no active Document B version.")
        return active.version


if __name__ == "__main__":
    main()
