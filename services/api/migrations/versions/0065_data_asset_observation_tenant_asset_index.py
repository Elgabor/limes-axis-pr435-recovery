"""composite tenant/asset index for data asset resource observations

Revision ID: 0065_data_asset_observation_tenant_asset_index
Revises: 0064_connector_source_batch_exports
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0065_data_asset_observation_tenant_asset_index"
down_revision: str | None = "0064_connector_source_batch_exports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_data_asset_resource_observations_tenant_asset"
TABLE_NAME = "data_asset_resource_observations"


def upgrade() -> None:
    # The catalog read counts observations for a named set of assets. With only
    # the single-column tenant_id and asset_id indexes the planner combines both
    # and touches index entries for every other tenant holding the same asset
    # ids, so one tenant's read cost grows with unrelated tenants' data.
    # Observations already contain live ingestion data. Follow migration 0053:
    # PostgreSQL must build this index outside a transaction without blocking
    # inserts, updates and deletes for the duration of the table scan.
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX_NAME,
            TABLE_NAME,
            ["tenant_id", "asset_id"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME, postgresql_concurrently=True)
