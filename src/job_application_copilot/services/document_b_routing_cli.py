"""Read-only developer inspection command for Document B routing."""

from __future__ import annotations

import argparse

from job_application_copilot.config import load_settings
from job_application_copilot.config.document_b_routing import (
    load_document_b_routing_config,
)
from job_application_copilot.domain import DOCUMENT_B_KEY
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
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Inspect validated Document B lane routing.")
    parser.add_argument("--document-b-version", type=int)
    parser.add_argument("--lane")
    parser.add_argument(
        "--headings",
        action="store_true",
        help="Print the exact heading catalogue without changing data.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the current private YAML against the selected Document B without changing data.",
    )
    args = parser.parse_args()
    if args.headings and (args.lane or args.validate):
        parser.error("--headings cannot be combined with --lane or --validate")

    database = create_database(settings.database_path)
    try:
        version = args.document_b_version or _active_version(database)
        section_service = DocumentBSectionService(database, settings)
        if args.headings:
            print(f"Document B version: {version}")
            print("Exact heading catalogue:")
            for section in section_service.extract(version):
                if section.heading_level > 0:
                    print(f"{'  ' * (section.heading_level - 1)}- {section.heading_title}")
            return

        config = load_document_b_routing_config(settings.document_b_routing_config_path)
        if args.lane is not None and args.lane not in config.lanes:
            parser.error(f"--lane must be one of: {', '.join(sorted(config.lanes))}")
        service = DocumentBRoutingManifestService(
            database,
            section_service,
            config_path=settings.document_b_routing_config_path,
        )
        print(f"Document B version: {version}")
        print("Supported canonical lanes:")
        for lane in config.lanes:
            print(f"  {lane}")
        print("Incomplete primary lanes (not selectable as primary):")
        for route_name, route in config.supporting_routes.items():
            if route.category == "INCOMPLETE_PRIMARY_LANE":
                print(f"  {route_name}")
        print("Optional supporting-only content (not selectable as primary):")
        for route_name, route in config.supporting_routes.items():
            if route.category == "OPTIONAL_SUPPORTING_CONTENT":
                print(f"  {route_name}")

        if args.validate:
            service.validate_config(version, config)
            print("Routing YAML validates against this Document B version.")
            return

        if args.lane is None:
            all_resolved = service.list_current_routes(version)
            summary = all_resolved[0].summary
            print(
                f"Routing set: {summary.routing_set_id} "
                f"config={summary.routing_config_version} "
                f"status={summary.status.value} current={summary.is_current}"
            )
            return

        lane_resolution = service.resolve(version, args.lane)
        summary = lane_resolution.summary
        print(
            f"Routing set: {summary.routing_set_id} "
            f"config={summary.routing_config_version} "
            f"status={summary.status.value} current={summary.is_current}"
        )
        print(f"Lane: {lane_resolution.packet.lane}")
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
