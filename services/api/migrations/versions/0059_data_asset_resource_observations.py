"""data asset resource observations

Revision ID: 0059_data_asset_resource_observations
Revises: 0058_data_asset_stewardship
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059_data_asset_resource_observations"
down_revision: str | None = "0058_data_asset_stewardship"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_asset_resource_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(length=80), nullable=False),
        sa.Column("connector_id", sa.String(length=160), nullable=False),
        sa.Column("asset_id", sa.String(length=220), nullable=False),
        sa.Column("resource_name", sa.String(length=240), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("previous_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("drift_state", sa.String(length=20), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_source_kind", sa.String(length=40), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("observed_by", sa.String(length=160), nullable=False),
        sa.Column("audit_event_type", sa.String(length=120), nullable=False),
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
            "drift_state IN ('added', 'changed', 'unchanged')",
            name="ck_data_asset_resource_observations_drift",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "connector_id",
            "resource_name",
            name="uq_data_asset_res_obs_tenant_connector_resource",
        ),
    )
    op.create_index(
        "ix_data_asset_resource_observations_tenant_id",
        "data_asset_resource_observations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_data_asset_resource_observations_connector_id",
        "data_asset_resource_observations",
        ["connector_id"],
    )
    op.create_index(
        "ix_data_asset_resource_observations_asset_id",
        "data_asset_resource_observations",
        ["asset_id"],
    )
    op.create_index(
        "ix_data_asset_resource_observations_drift_state",
        "data_asset_resource_observations",
        ["drift_state"],
    )


def downgrade() -> None:
    op.drop_table("data_asset_resource_observations")
