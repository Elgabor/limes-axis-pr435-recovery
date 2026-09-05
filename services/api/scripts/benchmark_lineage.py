"""Measure the complete lineage read against an ephemeral SQLite database.

Run from services/api: uv run python scripts/benchmark_lineage.py
Fixture construction, imports and warmup are excluded. Each read uses a fresh
Session, so the identity map cannot hide ORM loading work. This measures local
CPU/query overhead, not PostgreSQL latency or hosted capacity.
"""

import argparse
import json
import statistics
from datetime import UTC, datetime, timedelta
from time import perf_counter

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    record_demo_connector_manifest,
)
from axis_api.data_asset_lineage import build_data_asset_lineage_view
from axis_api.data_assets import data_asset_id_for_connector
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorOntologyPromotionCreate,
    ConnectorOntologyProposalCreate,
    TenantCreate,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", type=int, choices=range(1, 201), default=200)
    parser.add_argument("--promotions", type=int, choices=range(0, 101), default=5)
    parser.add_argument("--repeat", type=int, choices=range(3, 101), default=15)
    args = parser.parse_args()
    tenant_id = "tenant_demo_manufacturing"
    connector_id = "benchmark_csv"
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(TenantCreate(
            tenant_id=tenant_id, display_name="Benchmark", created_by="benchmark",
        ))
        record_demo_connector_manifest(repository, ConnectorManifestCreateRequest(
            tenant_id=tenant_id,
            registered_by="benchmark",
            manifest={
                "connector_id": connector_id,
                "display_name": "Benchmark CSV",
                "connector_type": "file_csv",
                "version": "1",
                "source_type": "file",
                "sync_modes": ["preview"],
                "runtime_boundary": "axis-connector-sandbox",
                "required_permissions": ["connectors:read"],
                "credential_requirements": {"storage": "none", "required_secret_refs": []},
                "schema_fields": [],
            },
            runtime_policy={
                "allowed_operations": ["metadata_preview"],
                "blocked_operations": ["live_sync"],
                "egress_policy": "no-external-egress",
                "max_file_size_mb": 5,
                "row_limit": 500,
                "payload_policy": "metadata-only",
            },
        ))
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(args.proposals):
            proposal_id = f"proposal-{index:03}"
            proposal = repository.create_connector_ontology_proposal(
                ConnectorOntologyProposalCreate(
                    tenant_id=tenant_id, connector_id=connector_id, proposal_id=proposal_id,
                    source_file_name="benchmark.csv", mapping_profile="benchmark",
                    proposed_by="benchmark", node_id=proposal_id, node_type="asset",
                    ontology_type="manufacturing_asset",
                )
            )
            proposal.created_at = timestamp + timedelta(seconds=index)
            for attempt in range(args.promotions):
                promotion_id = f"promotion-{index:03}-{attempt:03}"
                promotion = repository.create_connector_ontology_promotion(
                    ConnectorOntologyPromotionCreate(
                        tenant_id=tenant_id, connector_id=connector_id,
                        proposal_id=proposal_id, promotion_id=promotion_id,
                        idempotency_key=promotion_id, manual_import_id=promotion_id,
                        status="promotion_deferred", promotion_mode="approved_manual_import",
                        requested_by="benchmark", graph_mutation_status="not_applied",
                        ontology_mutation={}, permission_decision={},
                    )
                )
                promotion.created_at = timestamp + timedelta(seconds=attempt)
        session.commit()

    statements = 0

    @event.listens_for(engine, "before_cursor_execute")
    def count_statement(*_args) -> None:
        nonlocal statements
        statements += 1

    samples = []
    counts = []
    for iteration in range(args.repeat + 3):
        statements = 0
        start = perf_counter()
        with Session(engine) as session:
            view = build_data_asset_lineage_view(
                AxisPersistenceRepository(session), tenant_id=tenant_id,
                asset_id=data_asset_id_for_connector(connector_id),
            )
        elapsed = (perf_counter() - start) * 1000
        assert len(view.proposals) == args.proposals
        assert all(len(p.promotions) == min(args.promotions, 50) for p in view.proposals)
        if iteration >= 3:
            samples.append(elapsed)
            counts.append(statements)
    print(json.dumps({
        "database": "ephemeral SQLite", "proposals": args.proposals,
        "promotions_per_proposal": args.promotions, "warmup": 3,
        "samples": len(samples), "statements_per_read": sorted(set(counts)),
        "median_ms": round(statistics.median(samples), 3),
        "min_ms": round(min(samples), 3), "max_ms": round(max(samples), 3),
    }, indent=2))
    engine.dispose()


if __name__ == "__main__":
    main()
