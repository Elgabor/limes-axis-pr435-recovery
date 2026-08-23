"""connector source batch envelope export requests

Revision ID: 0064_connector_source_batch_exports
Revises: 0063_connector_source_ingestion_requests
Create Date: 2026-08-23

Approval-gated export of METADATA-ONLY extraction batch envelopes (counts,
digests, presence-only watermarks, storage references) for one governed
ingestion request. Raw row payloads and watermark values never enter this
table, its audit payloads, or any exported artifact.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064_connector_source_batch_exports"
down_revision: str | None = "0063_connector_source_ingestion_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table_name = "connector_source_batch_export_requests"
    op.create_table(
        table_name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=False),
        sa.Column("connector_id", sa.String(length=160), nullable=False),
        sa.Column("request_id", sa.String(length=180), nullable=False),
        sa.Column("export_request_id", sa.String(length=180), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("requested_by", sa.String(length=160), nullable=False),
        sa.Column("owner_role", sa.String(length=160), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("approval_id", sa.String(length=160), nullable=False),
        sa.Column("workflow_id", sa.String(length=160), nullable=False),
        sa.Column("export_reason", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("export_status", sa.String(length=80), nullable=False),
        sa.Column("storage_status", sa.String(length=80), nullable=False),
        sa.Column("batch_count", sa.Integer(), nullable=False),
        sa.Column("total_row_count", sa.Integer(), nullable=False),
        sa.Column("envelope_checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("redaction_policy", sa.String(length=120), nullable=False),
        sa.Column("controls", sa.JSON(), nullable=False),
        sa.Column("permission_decision", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=True),
        sa.Column("decision_actor_id", sa.String(length=160), nullable=True),
        sa.Column("decision_note", sa.String(length=600), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "materialization_id", sa.String(length=180), nullable=True
        ),
        sa.Column(
            "materialization_idempotency_key",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column("materialized_by", sa.String(length=160), nullable=True),
        sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("materialization_reason", sa.String(length=240), nullable=True),
        sa.Column("storage_adapter", sa.String(length=80), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("storage_uri", sa.String(length=700), nullable=True),
        sa.Column("artifact_checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=True),
        sa.Column("artifact_content_type", sa.String(length=120), nullable=True),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column("audit_event_type", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('approval_required', 'approval_approved', "
            "'approval_rejected', 'changes_requested', 'materialized')",
            name="ck_connector_source_batch_export_requests_status",
        ),
        sa.CheckConstraint(
            "storage_status IN ('not_written', 'written_local_object_store')",
            name="ck_connector_source_batch_export_requests_storage_status",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "export_request_id",
            name="uq_connector_source_batch_export_requests_tenant_request",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_connector_source_batch_export_requests_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_connector_source_batch_export_requests_tenant_ingestion",
        table_name,
        ["tenant_id", "connector_id", "request_id"],
    )
    op.create_index(
        "ix_connector_source_batch_export_requests_status",
        table_name,
        ["status"],
    )


def downgrade() -> None:
    table_name = "connector_source_batch_export_requests"
    op.drop_index(
        "ix_connector_source_batch_export_requests_status",
        table_name=table_name,
    )
    op.drop_index(
        "ix_connector_source_batch_export_requests_tenant_ingestion",
        table_name=table_name,
    )
    op.drop_table(table_name)
