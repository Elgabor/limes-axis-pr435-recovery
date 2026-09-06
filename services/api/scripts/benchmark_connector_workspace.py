"""Start a local-only connector UI fixture with 60 synthetic reference entries.

Run from services/api, using an unused port:
PYTHONPATH=src:scripts uv run uvicorn benchmark_connector_workspace:create_benchmark_app \
    --factory --host 127.0.0.1 --port 8364

Each process creates its own temporary SQLite database. No network data sources,
shared database, secrets, or external connector runtimes are configured here.
"""

from copy import deepcopy
from pathlib import Path
from runpy import run_path
from tempfile import mkdtemp

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import AxisPersistenceRepository, DemoReferenceRecordCreate, TenantCreate


def create_benchmark_app():
    directory = Path(mkdtemp(prefix="axis-connector-workspace-"))
    app = create_app(
        Settings(
            _env_file=None,
            environment="development",
            postgres_dsn=f"sqlite+pysqlite:///{directory / 'fixture.sqlite'}",
            oidc_auth_required=False,
            workflow_signals_enabled=False,
            api_rate_limit_enabled=False,
            cors_origins=["http://127.0.0.1:3364"],
        )
    )
    factory = app.state.session_factory
    Base.metadata.create_all(factory.kw["bind"])
    payload = deepcopy(
        run_path(
            str(
                Path(__file__).resolve().parents[1]
                / "migrations/versions/0023_connector_registry_reference.py"
            )
        )["CONNECTOR_REGISTRY_PAYLOAD"]
    )
    for index in range(58):
        connector = deepcopy(payload["connectors"][0])
        connector["manifest"]["connector_id"] = f"benchmark_csv_{index:03}"
        connector["manifest"]["display_name"] = f"Benchmark CSV {index:03}"
        payload["connectors"].append(connector)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(
                tenant_id=payload["tenant_id"],
                display_name="Ravenna Works",
                description="Isolated issue 364 benchmark",
                created_by="local-benchmark",
            )
        )
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=payload["tenant_id"],
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="local-benchmark",
                version="2026-09-06",
                payload=payload,
            )
        )
    return app
