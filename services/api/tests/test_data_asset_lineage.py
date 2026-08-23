from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.data_asset_lineage import DataAssetLineageView, build_data_asset_lineage_view
from axis_api.data_assets import DataAssetNotInCatalog
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorOntologyPromotionCreate,
    ConnectorOntologyProposalCreate,
    DemoReferenceRecordCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"
CONNECTOR_ID = "file_csv_manufacturing_assets"
ASSET_A = "source:file_csv_manufacturing_assets:default"
UNKNOWN_ASSET = "source:not_a_real_asset:default"
PROPOSER = "plant-operations-owner-role"


def reference_registry_payload() -> dict:
    return {
        "tenant_id": TENANT_A,
        "plant_name": "Ravenna Works",
        "scenario": "Data Asset Lineage Fixture",
        "registry_status": "ready",
        "metrics": [
            {
                "label": "Persisted Connector Registry",
                "value": "1",
                "detail": "Loaded from demo_reference_records.",
                "status": "ready",
            }
        ],
        "connectors": [
            {
                "connector_status": "ready",
                "manifest": {
                    "connector_id": CONNECTOR_ID,
                    "display_name": "Manufacturing assets CSV",
                    "connector_type": "file_csv",
                    "version": "2026-08-21",
                    "source_type": "file",
                    "sync_modes": ["preview"],
                    "runtime_boundary": "axis-connector-sandbox",
                    "required_permissions": ["connectors:read"],
                    "credential_requirements": {
                        "storage": "none",
                        "required_secret_refs": [],
                        "notes": [],
                    },
                    "schema_fields": [
                        {
                            "source_column": "asset_id",
                            "target_field": "node_id",
                            "ontology_target": "manufacturing_asset",
                            "data_type": "string",
                            "required": True,
                            "description": "Asset identifier.",
                        },
                        {
                            "source_column": "station",
                            "target_field": "station",
                            "ontology_target": "manufacturing_station",
                            "data_type": "string",
                            "required": False,
                            "description": "Station.",
                        },
                    ],
                    "mapping_notes": [],
                },
                "runtime_policy": {
                    "allowed_operations": ["schema_validate", "metadata_preview"],
                    "blocked_operations": ["live_sync"],
                    "egress_policy": "no-external-egress",
                    "max_file_size_mb": 5,
                    "row_limit": 500,
                    "payload_policy": "metadata-only",
                },
            }
        ],
        "connector_notes": [],
    }


@pytest.fixture
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(
                tenant_id=TENANT_A,
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
        repository.create_tenant(
            TenantCreate(
                tenant_id=TENANT_B,
                display_name="Other Plant",
                description="Second tenant",
                created_by="test",
            )
        )
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=TENANT_A,
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-08-21",
                payload=reference_registry_payload(),
            )
        )
    yield factory
    engine.dispose()


def build_client(session_factory: sessionmaker) -> TestClient:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    return TestClient(app)


def seed_proposal(
    factory: sessionmaker,
    *,
    proposal_id: str,
    node_id: str,
    created_at: datetime,
    tenant_id: str = TENANT_A,
    status: str = "proposed_from_preview",
    graph_mutation_status: str = "not_applied",
    promoted_at: datetime | None = None,
) -> None:
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        proposal = repository.create_connector_ontology_proposal(
            ConnectorOntologyProposalCreate(
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                proposal_id=proposal_id,
                source_file_name="manufacturing-assets-demo.csv",
                mapping_profile="manufacturing_asset_v1",
                status=status,
                graph_mutation_status=graph_mutation_status,
                proposed_by=PROPOSER,
                node_id=node_id,
                node_type="asset",
                ontology_type="manufacturing_asset",
                field_summary={"asset_name": node_id},
                evidence_refs=["manufacturing-assets-demo.csv"],
            )
        )
        proposal.created_at = created_at
        if promoted_at is not None:
            proposal.promoted_at = promoted_at


def seed_promotion(
    factory: sessionmaker,
    *,
    promotion_id: str,
    proposal_id: str,
    created_at: datetime,
    status: str,
    promotion_mode: str = "approved_manual_import",
    graph_mutation_status: str = "type_db_mutation_applied",
) -> None:
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        promotion = repository.create_connector_ontology_promotion(
            ConnectorOntologyPromotionCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                promotion_id=promotion_id,
                idempotency_key=f"idempotency-{promotion_id}",
                proposal_id=proposal_id,
                manual_import_id=f"import_{promotion_id}",
                status=status,
                promotion_mode=promotion_mode,
                requested_by=PROPOSER,
                graph_mutation_status=graph_mutation_status,
            )
        )
        promotion.created_at = created_at


def build_view(
    factory: sessionmaker,
    *,
    tenant_id: str = TENANT_A,
    asset_id: str = ASSET_A,
) -> DataAssetLineageView:
    with session_scope(factory) as session:
        return build_data_asset_lineage_view(
            AxisPersistenceRepository(session),
            tenant_id=tenant_id,
            asset_id=asset_id,
        )


def test_asset_without_proposals_has_empty_lineage(
    session_factory: sessionmaker,
) -> None:
    view = build_view(session_factory)

    assert view.tenant_id == TENANT_A
    assert view.asset_id == ASSET_A
    assert view.proposals == []


def test_proposals_are_chronological_and_promoted_one_carries_nested_promotion(
    session_factory: sessionmaker,
) -> None:
    seed_proposal(
        session_factory,
        proposal_id="proposal_pending",
        node_id="asset_station_b",
        created_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    seed_promotion(
        session_factory,
        promotion_id="promote_line_2_packaging_001",
        proposal_id="proposal_promoted",
        created_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        status="promoted_to_graph",
        promotion_mode="approved_manual_import",
    )
    seed_proposal(
        session_factory,
        proposal_id="proposal_promoted",
        node_id="asset_line_2_packaging",
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
        status="promoted_to_graph",
        graph_mutation_status="type_db_mutation_applied",
        promoted_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
    )

    view = build_view(session_factory)

    assert [item.proposal_id for item in view.proposals] == [
        "proposal_promoted",
        "proposal_pending",
    ]
    promoted = view.proposals[0]
    assert promoted.status == "promoted_to_graph"
    assert promoted.graph_mutation_status == "type_db_mutation_applied"
    assert len(promoted.promotions) == 1
    attempt = promoted.promotions[0]
    assert attempt.promotion_id == "promote_line_2_packaging_001"
    assert attempt.status == "promoted_to_graph"
    assert attempt.promotion_mode == "approved_manual_import"
    assert attempt.requested_by == PROPOSER
    assert view.proposals[1].promotions == []


def test_deferred_promotion_attempt_still_shown_under_proposal(
    session_factory: sessionmaker,
) -> None:
    seed_proposal(
        session_factory,
        proposal_id="proposal_deferred",
        node_id="asset_line_3_labelling",
        created_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    seed_promotion(
        session_factory,
        promotion_id="promote_line_3_labelling_deferred",
        proposal_id="proposal_deferred",
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
        status="promotion_deferred",
        promotion_mode="deferred_review_window",
        graph_mutation_status="not_applied",
    )

    view = build_view(session_factory)

    assert [item.proposal_id for item in view.proposals] == ["proposal_deferred"]
    assert len(view.proposals[0].promotions) == 1
    attempt = view.proposals[0].promotions[0]
    assert attempt.status == "promotion_deferred"
    assert attempt.promotion_mode == "deferred_review_window"


def test_lineage_excludes_other_tenants_proposals(
    session_factory: sessionmaker,
) -> None:
    seed_proposal(
        session_factory,
        proposal_id="proposal_other_tenant",
        node_id="asset_other_plant",
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        tenant_id=TENANT_B,
    )
    seed_proposal(
        session_factory,
        proposal_id="proposal_own_tenant",
        node_id="asset_line_2_packaging",
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
    )

    view = build_view(session_factory)

    assert [item.proposal_id for item in view.proposals] == ["proposal_own_tenant"]


def test_unknown_asset_fails_closed_in_domain_layer(
    session_factory: sessionmaker,
) -> None:
    with pytest.raises(DataAssetNotInCatalog) as exc_info:
        build_view(session_factory, asset_id=UNKNOWN_ASSET)

    assert exc_info.value.tenant_id == TENANT_A
    assert exc_info.value.asset_id == UNKNOWN_ASSET


def test_lineage_route_returns_shape_and_unknown_asset_404s(
    session_factory: sessionmaker,
) -> None:
    seed_promotion(
        session_factory,
        promotion_id="promote_line_2_packaging_001",
        proposal_id="proposal_promoted",
        created_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        status="promoted_to_graph",
        promotion_mode="approved_manual_import",
    )
    seed_proposal(
        session_factory,
        proposal_id="proposal_promoted",
        node_id="asset_line_2_packaging",
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
        status="promoted_to_graph",
        graph_mutation_status="type_db_mutation_applied",
        promoted_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
    )
    client = build_client(session_factory)

    response = client.get(
        f"/data/assets/{ASSET_A}/lineage",
        params={"tenant_id": TENANT_A},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == TENANT_A
    assert body["asset_id"] == ASSET_A
    assert list(body["proposals"][0]) == [
        "proposal_id",
        "status",
        "graph_mutation_status",
        "node_id",
        "ontology_type",
        "proposed_by",
        "created_at",
        "promoted_at",
        "promotions",
    ]
    assert body["proposals"][0]["proposal_id"] == "proposal_promoted"
    assert body["proposals"][0]["promotions"] == [
        {
            "promotion_id": "promote_line_2_packaging_001",
            "status": "promoted_to_graph",
            "promotion_mode": "approved_manual_import",
            "requested_by": PROPOSER,
            "created_at": "2026-08-21T12:00:00",
        }
    ]

    unknown = client.get(
        f"/data/assets/{UNKNOWN_ASSET}/lineage",
        params={"tenant_id": TENANT_A},
    )

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["surface"] == "data"
