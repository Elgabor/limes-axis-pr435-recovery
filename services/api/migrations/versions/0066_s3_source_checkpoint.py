"""Binding-scoped checkpoints for governed incremental object ingestion.

Revision ID: 0066_s3_source_checkpoint
Revises: 0065_data_asset_observation_tenant_asset_index
"""

import sqlalchemy as sa
from alembic import op

revision = "0066_s3_source_checkpoint"
down_revision = "0065_data_asset_observation_tenant_asset_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connector_source_bindings",
        sa.Column(
            "source_checkpoint_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "connector_source_bindings", sa.Column("source_checkpoint", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("connector_source_bindings", "source_checkpoint")
    op.drop_column("connector_source_bindings", "source_checkpoint_revision")
