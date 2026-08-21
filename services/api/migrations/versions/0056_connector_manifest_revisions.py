"""connector manifest revisions

Revision ID: 0056_connector_manifest_revisions
Revises: 0055_tenant_vocabulary
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056_connector_manifest_revisions"
down_revision: str | None = "0055_tenant_vocabulary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table_name = "connector_manifests"
    op.add_column(
        table_name,
        sa.Column("revision_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("revises_revision_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("replaced_by_revision_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("revision_idempotency_key", sa.String(length=200), nullable=True),
    )
    op.execute(sa.text("UPDATE connector_manifests SET revision_number = 1"))
    op.alter_column(table_name, "revision_number", nullable=False)
    op.drop_constraint(
        "uq_connector_manifests_tenant_connector",
        table_name,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_connector_manifests_tenant_connector_revision",
        table_name,
        ["tenant_id", "connector_id", "revision_number"],
    )
    op.create_unique_constraint(
        "uq_connector_manifests_tenant_revision_idempotency",
        table_name,
        ["tenant_id", "revision_idempotency_key"],
    )
    op.create_index(
        "ix_connector_manifests_revision_idempotency_key",
        table_name,
        ["revision_idempotency_key"],
    )


def downgrade() -> None:
    table_name = "connector_manifests"
    op.execute(
        sa.text(
            "DELETE FROM connector_manifests "
            "WHERE replaced_by_revision_number IS NOT NULL"
        )
    )
    op.drop_index(
        "ix_connector_manifests_revision_idempotency_key",
        table_name=table_name,
    )
    op.drop_constraint(
        "uq_connector_manifests_tenant_revision_idempotency",
        table_name,
        type_="unique",
    )
    op.drop_constraint(
        "uq_connector_manifests_tenant_connector_revision",
        table_name,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_connector_manifests_tenant_connector",
        table_name,
        ["tenant_id", "connector_id"],
    )
    op.drop_column(table_name, "revision_idempotency_key")
    op.drop_column(table_name, "replaced_by_revision_number")
    op.drop_column(table_name, "revises_revision_number")
    op.drop_column(table_name, "revision_number")
