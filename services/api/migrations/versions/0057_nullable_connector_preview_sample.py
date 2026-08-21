"""nullable connector preview sample

Revision ID: 0057_nullable_connector_preview_sample
Revises: 0056_connector_manifest_revisions
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_nullable_connector_preview_sample"
down_revision: str | None = "0056_connector_manifest_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "connector_manifests",
        "preview_sample",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE connector_manifests SET preview_sample = '{}'::jsonb "
            "WHERE preview_sample IS NULL"
        )
    )
    op.alter_column(
        "connector_manifests",
        "preview_sample",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )
