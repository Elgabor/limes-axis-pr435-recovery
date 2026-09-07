"""Version source schema selections and preserve superseded binding history."""

import sqlalchemy as sa
from alembic import op

revision = "0067_source_schema_versions"
down_revision = "0066_s3_source_checkpoint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("connector_source_bindings", "data_asset_resource_observations"):
        op.add_column(
            table,
            sa.Column(
                "schema_fingerprint_version",
                sa.String(40),
                nullable=False,
                server_default="column_names_v1",
            ),
        )
    with op.batch_alter_table("connector_source_bindings") as batch:
        batch.add_column(sa.Column("supersedes_binding_id", sa.String(180), nullable=True))
        batch.drop_constraint("ck_connector_source_bindings_status", type_="check")
        batch.create_check_constraint(
            "ck_connector_source_bindings_status",
            "status IN ('active', 'superseded')",
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("connector_source_bindings", "data_asset_resource_observations"):
        if connection.scalar(
            sa.text(
                f"SELECT count(*) FROM {table} "
                "WHERE schema_fingerprint_version <> 'column_names_v1'"
            )
        ):
            raise RuntimeError("Cannot downgrade while versioned schema selections exist.")
    if connection.scalar(
        sa.text("SELECT count(*) FROM connector_source_bindings WHERE status = 'superseded'")
    ):
        raise RuntimeError("Cannot downgrade while superseded binding history exists.")
    with op.batch_alter_table("connector_source_bindings") as batch:
        batch.drop_constraint("ck_connector_source_bindings_status", type_="check")
        batch.create_check_constraint("ck_connector_source_bindings_status", "status IN ('active')")
        batch.drop_column("supersedes_binding_id")
        batch.drop_column("schema_fingerprint_version")
    op.drop_column("data_asset_resource_observations", "schema_fingerprint_version")
