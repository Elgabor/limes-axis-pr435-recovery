"""connector lifecycle events

Revision ID: 0061_connector_lifecycle_events
Revises: 0060_data_asset_contracts
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061_connector_lifecycle_events"
down_revision: str | None = "0060_data_asset_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table_name = "connector_lifecycle_events"
    op.create_table(
        table_name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=False),
        sa.Column("connector_id", sa.String(length=160), nullable=False),
        sa.Column("from_status", sa.String(length=80), nullable=False),
        sa.Column("target_status", sa.String(length=80), nullable=False),
        sa.Column("transitioned_by", sa.String(length=160), nullable=False),
        sa.Column("transition_reason", sa.String(length=600), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_type", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connector_lifecycle_events_tenant_connector_created",
        table_name,
        ["tenant_id", "connector_id", "created_at"],
    )


def downgrade() -> None:
    table_name = "connector_lifecycle_events"
    op.drop_index(
        "ix_connector_lifecycle_events_tenant_connector_created",
        table_name=table_name,
    )
    op.drop_table(table_name)
