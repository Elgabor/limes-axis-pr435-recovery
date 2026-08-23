"""connector source bindings

Revision ID: 0062_connector_source_bindings
Revises: 0061_connector_lifecycle_events
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062_connector_source_bindings"
down_revision: str | None = "0061_connector_lifecycle_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table_name = "connector_source_bindings"
    op.create_table(
        table_name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=False),
        sa.Column("connector_id", sa.String(length=160), nullable=False),
        sa.Column("asset_id", sa.String(length=220), nullable=False),
        sa.Column("binding_id", sa.String(length=180), nullable=False),
        sa.Column("connection_profile_id", sa.String(length=180), nullable=False),
        sa.Column("resource_name", sa.String(length=240), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("credential_lease_id", sa.String(length=180), nullable=False),
        sa.Column("egress_policy_id", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("ingestion_status", sa.String(length=60), nullable=False),
        sa.Column("activated_by", sa.String(length=160), nullable=False),
        sa.Column("activation_reason", sa.String(length=600), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_type", sa.String(length=120), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('active')",
            name="ck_connector_source_bindings_status",
        ),
        sa.CheckConstraint(
            "ingestion_status IN ('pending_ingestion')",
            name="ck_connector_source_bindings_ingestion_status",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "binding_id",
            name="uq_connector_source_bindings_tenant_binding",
        ),
    )
    op.create_index(
        "uq_connector_source_bindings_active_resource",
        table_name,
        ["tenant_id", "connector_id", "resource_name"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_connector_source_bindings_tenant_connector",
        table_name,
        ["tenant_id", "connector_id"],
    )


def downgrade() -> None:
    table_name = "connector_source_bindings"
    op.drop_index(
        "ix_connector_source_bindings_tenant_connector",
        table_name=table_name,
    )
    op.drop_index(
        "uq_connector_source_bindings_active_resource",
        table_name=table_name,
    )
    op.drop_table(table_name)
