"""Create version-bound Document B routing-set tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_create_document_b_routing_tables"
down_revision: str | None = "0008_add_job_relevance_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROUTING_STATUSES = ("DRAFT", "VALIDATED", "INVALID", "SUPERSEDED")
CV_LANES = (
    "APPLIED_AI_DEPLOYMENT_LEADERSHIP",
    "AI_DEPLOYMENT_SOLUTION_OWNER",
    "ZERO_TO_ONE_DATA_AI_SOLUTION_LEAD",
    "DATA_AI_VALUE_CREATION",
    "HEAD_OF_SOLUTIONS_ARCHITECTURE",
    "HEAD_OF_DATA_ANALYTICS_AI",
    "EXPERT_LED_COMMERCIAL_POST_SALES",
    "TECHNICAL_PRODUCT_AI_PRODUCT_BUILDER",
    "EXECUTION_FOCUSED_CTO_FIELD_CTO",
)


def upgrade() -> None:
    op.create_table(
        "document_b_routing_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reference_asset_id",
            sa.Integer(),
            sa.ForeignKey("reference_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("routing_config_version", sa.String(length=64), nullable=False),
        sa.Column("routing_config_sha256", sa.String(length=71), nullable=False),
        sa.Column("document_b_file_sha256", sa.String(length=71), nullable=False),
        sa.Column("extracted_section_catalog_sha256", sa.String(length=71), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*ROUTING_STATUSES, name="document_b_routing_set_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("is_current", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("validation_error", sa.Text()),
        sa.CheckConstraint(
            "length(trim(routing_config_version)) > 0",
            name="ck_document_b_routing_sets_config_version_not_blank",
        ),
    )
    op.create_index(
        "ix_document_b_routing_sets_reference_asset_id",
        "document_b_routing_sets",
        ["reference_asset_id"],
    )
    op.create_index(
        "uq_document_b_routing_sets_current_asset",
        "document_b_routing_sets",
        ["reference_asset_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )
    op.create_table(
        "document_b_lane_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "routing_set_id",
            sa.Integer(),
            sa.ForeignKey("document_b_routing_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lane_id",
            sa.Enum(*CV_LANES, name="cv_lane", native_enum=False),
            nullable=False,
        ),
        sa.Column("ordered_route_json", sa.Text(), nullable=False),
        sa.Column("secondary_lane_constraints_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "routing_set_id",
            "lane_id",
            name="uq_document_b_lane_routes_set_lane",
        ),
        sa.CheckConstraint(
            "length(trim(ordered_route_json)) > 0",
            name="ck_document_b_lane_routes_packet_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(secondary_lane_constraints_json)) > 0",
            name="ck_document_b_lane_routes_constraints_not_blank",
        ),
    )
    op.create_index(
        "ix_document_b_lane_routes_routing_set_id",
        "document_b_lane_routes",
        ["routing_set_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_b_lane_routes_routing_set_id",
        table_name="document_b_lane_routes",
    )
    op.drop_table("document_b_lane_routes")
    op.drop_index(
        "uq_document_b_routing_sets_current_asset",
        table_name="document_b_routing_sets",
    )
    op.drop_index(
        "ix_document_b_routing_sets_reference_asset_id",
        table_name="document_b_routing_sets",
    )
    op.drop_table("document_b_routing_sets")
