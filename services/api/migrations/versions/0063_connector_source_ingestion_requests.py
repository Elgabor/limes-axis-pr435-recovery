"""connector source ingestion requests (and extraction batch metadata)

Revision ID: 0063_connector_source_ingestion_requests
Revises: 0062_connector_source_bindings
Create Date: 2026-08-23

Edit boundary: this revision was extended in place during Batch 10 (stage +
cancellation columns, extraction-batch table) BEFORE its first application
anywhere — it had never been committed nor applied when edited. Once applied
in any environment, this file is immutable and further changes require new
forward-only revisions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063_connector_source_ingestion_requests"
down_revision: str | None = "0062_connector_source_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table_name = "connector_source_ingestion_requests"
    op.create_table(
        table_name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=False),
        sa.Column("connector_id", sa.String(length=160), nullable=False),
        sa.Column("request_id", sa.String(length=180), nullable=False),
        sa.Column("requested_by", sa.String(length=160), nullable=False),
        sa.Column("reason", sa.String(length=600), nullable=False),
        sa.Column(
            "stage",
            sa.String(length=20),
            nullable=False,
            server_default="validate",
        ),
        sa.Column("selections", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.String(length=160), nullable=True),
        sa.Column("cancel_reason", sa.String(length=200), nullable=True),
        sa.Column("requeued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requeued_by", sa.String(length=160), nullable=True),
        sa.Column("requeue_reason", sa.String(length=600), nullable=True),
        sa.Column(
            "requeue_idempotency_key", sa.String(length=180), nullable=True
        ),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_type", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'dispatching', 'completed', 'failed', 'cancelled')",
            name="ck_connector_source_ingestion_requests_status",
        ),
        sa.CheckConstraint(
            "stage IN ('validate', 'extract')",
            name="ck_connector_source_ingestion_requests_stage",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "request_id",
            name="uq_connector_source_ingestion_requests_tenant_request",
        ),
    )
    op.create_index(
        "ix_connector_source_ingestion_requests_dispatch",
        table_name,
        ["status", "available_at", "id"],
    )
    op.create_index(
        "ix_connector_source_ingestion_requests_stale_claim",
        table_name,
        ["status", "lease_expires_at", "id"],
    )
    op.create_index(
        "ix_connector_source_ingestion_requests_status",
        table_name,
        ["status"],
    )
    op.create_index(
        "ix_connector_source_ingestion_requests_tenant_connector",
        table_name,
        ["tenant_id", "connector_id"],
    )

    batches_table = "connector_source_extraction_batches"
    op.create_table(
        batches_table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=False),
        sa.Column("connector_id", sa.String(length=160), nullable=False),
        sa.Column("request_id", sa.String(length=180), nullable=False),
        sa.Column("batch_key", sa.String(240), nullable=False),
        sa.Column("binding_id", sa.String(length=180), nullable=False),
        sa.Column("resource_name", sa.String(length=240), nullable=False),
        sa.Column("pinned_schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("observed_schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("ordering_mode", sa.String(length=20), nullable=False),
        sa.Column("cursor_watermark", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("limit_reason", sa.String(length=60), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("limits_applied", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("digest_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_adapter", sa.String(length=80), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("storage_uri", sa.String(length=700), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("stored_size_bytes", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column("executed_by", sa.String(length=160), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_type", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "ordering_mode IN ('primary_key', 'none')",
            name="ck_connector_source_extraction_batches_ordering_mode",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "batch_key",
            name="uq_connector_source_extraction_batches_tenant_batch_key",
        ),
    )
    op.create_index(
        "ix_connector_source_extraction_batches_tenant_request",
        batches_table,
        ["tenant_id", "request_id"],
    )
    op.create_index(
        "ix_connector_source_extraction_batches_binding",
        batches_table,
        ["tenant_id", "connector_id", "binding_id"],
    )


def downgrade() -> None:
    batches_table = "connector_source_extraction_batches"
    op.drop_index(
        "ix_connector_source_extraction_batches_binding",
        table_name=batches_table,
    )
    op.drop_index(
        "ix_connector_source_extraction_batches_tenant_request",
        table_name=batches_table,
    )
    op.drop_table(batches_table)

    table_name = "connector_source_ingestion_requests"
    op.drop_index(
        "ix_connector_source_ingestion_requests_tenant_connector",
        table_name=table_name,
    )
    op.drop_index(
        "ix_connector_source_ingestion_requests_status",
        table_name=table_name,
    )
    op.drop_index(
        "ix_connector_source_ingestion_requests_stale_claim",
        table_name=table_name,
    )
    op.drop_index(
        "ix_connector_source_ingestion_requests_dispatch",
        table_name=table_name,
    )
    op.drop_table(table_name)
