"""Create section-scoped Document B vector provenance and retrieval traces."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_create_document_b_retrieval_tables"
down_revision: str | None = "0009_create_document_b_routing_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_b_vector_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reference_asset_id",
            sa.Integer(),
            sa.ForeignKey("reference_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_id", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("openai_file_id", sa.String(length=255), nullable=False),
        sa.Column("vector_store_id", sa.String(length=255), nullable=False),
        sa.Column(
            "indexed_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
        sa.UniqueConstraint(
            "reference_asset_id", "section_id", name="uq_document_b_vector_record_section"
        ),
        sa.UniqueConstraint("openai_file_id", name="uq_document_b_vector_record_openai_file"),
    )
    op.create_index(
        "ix_document_b_vector_records_reference_asset_id",
        "document_b_vector_records",
        ["reference_asset_id"],
    )
    op.create_table(
        "document_b_retrieval_traces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reference_asset_id",
            sa.Integer(),
            sa.ForeignKey("reference_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "routing_set_id",
            sa.Integer(),
            sa.ForeignKey("document_b_routing_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("routing_config_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False
        ),
    )
    op.create_index(
        "ix_document_b_retrieval_traces_reference_asset_id",
        "document_b_retrieval_traces",
        ["reference_asset_id"],
    )
    op.create_index(
        "ix_document_b_retrieval_traces_routing_set_id",
        "document_b_retrieval_traces",
        ["routing_set_id"],
    )
    op.create_table(
        "document_b_retrieval_trace_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "trace_id",
            sa.Integer(),
            sa.ForeignKey("document_b_retrieval_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vector_record_id",
            sa.Integer(),
            sa.ForeignKey("document_b_vector_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("passage_id", sa.String(length=71), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passage_text", sa.Text(), nullable=False),
        sa.Column("source_metadata_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("trace_id", "passage_id", name="uq_document_b_trace_passage"),
    )
    op.create_index(
        "ix_document_b_retrieval_trace_results_trace_id",
        "document_b_retrieval_trace_results",
        ["trace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_b_retrieval_trace_results_trace_id",
        table_name="document_b_retrieval_trace_results",
    )
    op.drop_table("document_b_retrieval_trace_results")
    op.drop_index(
        "ix_document_b_retrieval_traces_routing_set_id", table_name="document_b_retrieval_traces"
    )
    op.drop_index(
        "ix_document_b_retrieval_traces_reference_asset_id",
        table_name="document_b_retrieval_traces",
    )
    op.drop_table("document_b_retrieval_traces")
    op.drop_index(
        "ix_document_b_vector_records_reference_asset_id", table_name="document_b_vector_records"
    )
    op.drop_table("document_b_vector_records")
