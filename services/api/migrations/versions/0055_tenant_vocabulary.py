"""tenant vocabulary

Revision ID: 0055_tenant_vocabulary
Revises: 0054_approval_decision_outbox
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_tenant_vocabulary"
down_revision: str | None = "0054_approval_decision_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "vocabulary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "vocabulary")
