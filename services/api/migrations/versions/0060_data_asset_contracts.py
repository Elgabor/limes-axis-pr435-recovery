"""data asset contracts

Revision ID: 0060_data_asset_contracts
Revises: 0059_data_asset_resource_observations
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060_data_asset_contracts"
down_revision: str | None = "0059_data_asset_resource_observations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_asset_contracts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=False),
        sa.Column("asset_id", sa.String(length=220), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("expected_resource_name", sa.String(length=240), nullable=False),
        sa.Column("expected_schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("freshness_warn_hours", sa.Integer(), nullable=True),
        sa.Column("freshness_fail_hours", sa.Integer(), nullable=True),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("declared_by", sa.String(length=160), nullable=False),
        sa.Column("audit_event_type", sa.String(length=120), nullable=False),
        sa.Column("revises_revision_number", sa.Integer(), nullable=True),
        sa.Column("replaced_by_revision_number", sa.Integer(), nullable=True),
        sa.Column("revision_idempotency_key", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "freshness_warn_hours IS NULL OR freshness_warn_hours >= 1",
            name="ck_data_asset_contracts_warn_hours",
        ),
        sa.CheckConstraint(
            "freshness_fail_hours IS NULL OR freshness_fail_hours >= 1",
            name="ck_data_asset_contracts_fail_hours",
        ),
        sa.CheckConstraint(
            "freshness_warn_hours IS NULL OR freshness_fail_hours IS NULL "
            "OR freshness_warn_hours <= freshness_fail_hours",
            name="ck_data_asset_contracts_freshness_ordering",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "asset_id",
            "revision_number",
            name="uq_data_asset_contracts_tenant_asset_revision",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "revision_idempotency_key",
            name="uq_data_asset_contracts_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_data_asset_contracts_tenant_id",
        "data_asset_contracts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_data_asset_contracts_asset_id",
        "data_asset_contracts",
        ["asset_id"],
    )
    op.create_index(
        "ix_data_asset_contracts_declared_by",
        "data_asset_contracts",
        ["declared_by"],
    )
    op.create_index(
        "ix_data_asset_contracts_revision_idempotency_key",
        "data_asset_contracts",
        ["revision_idempotency_key"],
    )


def downgrade() -> None:
    op.drop_table("data_asset_contracts")
