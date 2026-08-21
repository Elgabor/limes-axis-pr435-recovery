"""data asset stewardship records

Revision ID: 0058_data_asset_stewardship
Revises: 0057_nullable_connector_preview_sample
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058_data_asset_stewardship"
down_revision: str | None = "0057_nullable_connector_preview_sample"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_asset_stewardship_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=False),
        sa.Column("asset_id", sa.String(length=220), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column("residency", sa.String(length=80), nullable=False),
        sa.Column("retention", sa.String(length=80), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("declared_by", sa.String(length=160), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
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
            "classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="ck_data_asset_stewardship_classification",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "asset_id",
            "revision_number",
            name="uq_data_asset_stewardship_tenant_asset_revision",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "revision_idempotency_key",
            name="uq_data_asset_stewardship_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_data_asset_stewardship_records_tenant_id",
        "data_asset_stewardship_records",
        ["tenant_id"],
    )
    op.create_index(
        "ix_data_asset_stewardship_records_asset_id",
        "data_asset_stewardship_records",
        ["asset_id"],
    )
    op.create_index(
        "ix_data_asset_stewardship_records_classification",
        "data_asset_stewardship_records",
        ["classification"],
    )
    op.create_index(
        "ix_data_asset_stewardship_records_declared_by",
        "data_asset_stewardship_records",
        ["declared_by"],
    )
    op.create_index(
        "ix_data_asset_stewardship_records_audit_event_type",
        "data_asset_stewardship_records",
        ["audit_event_type"],
    )
    op.create_index(
        "ix_data_asset_stewardship_records_revision_idempotency_key",
        "data_asset_stewardship_records",
        ["revision_idempotency_key"],
    )


def downgrade() -> None:
    op.drop_table("data_asset_stewardship_records")
