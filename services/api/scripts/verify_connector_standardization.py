"""Run the connector proof without loading deployment .env configuration.

Use an environment restored from the API lockfile. The default suite is offline.
--postgres-port opts into synthetic databases/roles in a dedicated localhost
PostgreSQL container already provisioned by the operator. It never starts Docker.
"""

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-port", type=int)
    args = parser.parse_args()
    if args.postgres_port is not None and not 1 <= args.postgres_port <= 65535:
        parser.error("The dedicated PostgreSQL port must be between 1 and 65535.")
    for name in tuple(os.environ):
        if name.startswith("AXIS_") or name == "LIMES_ISOLATED_POSTGRES_PORT":
            del os.environ[name]
    api = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(api / "src"))
    os.chdir(api)
    from axis_api.config import Settings

    Settings.model_config["env_file"] = None
    import psycopg
    import pytest

    if args.postgres_port is not None:
        os.environ["LIMES_ISOLATED_POSTGRES_PORT"] = str(args.postgres_port)
        names = ["controlled_proof", "raw_postgres", "schema_migration_postgres"]
        plugins = []
    else:
        names = [
            "live_sync_contract",
            "extraction_boundaries",
            "raw_durability",
            "schema_versions",
            "csv_snapshot_proof",
        ]

        class OfflineSources:
            @pytest.fixture(autouse=True)
            def source_network_guard(self, monkeypatch):
                def unavailable(*args, **kwargs):
                    raise psycopg.OperationalError("Offline proof: source network unavailable")

                monkeypatch.setattr(psycopg, "connect", unavailable)

        plugins = [OfflineSources()]
    return pytest.main(
        ["-q", "--tb=short", *[f"tests/test_connector_{name}.py" for name in names]],
        plugins=plugins,
    )


if __name__ == "__main__":
    raise SystemExit(main())
