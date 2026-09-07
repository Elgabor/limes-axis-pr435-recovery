import pytest

from axis_api.connector_source_schema import postgres_schema_fingerprint


@pytest.mark.parametrize(
    "changed",
    [
        ("renamed", "integer", True, True, "", ""),
        ("id", "bigint", True, True, "", ""),
        ("id", "integer", False, True, "", ""),
        ("id", "integer", True, False, "", ""),
    ],
)
def test_schema_v2_distinguishes_incompatible_changes(changed):
    original = [("id", "integer", True, True, "", "")]
    assert postgres_schema_fingerprint(original) != postgres_schema_fingerprint([changed])


@pytest.fixture
def session_factory():
    from test_connector_source_activation import session_factory as fixture

    yield from fixture.__wrapped__()


def test_governed_replacement_preserves_predecessor_and_replays(session_factory):
    from test_connector_source_activation import (
        ACTIVATION_SCOPE,
        CONNECTOR_ID,
        FINGERPRINT_A,
        FINGERPRINT_B,
        RESOURCE_1,
        TENANT_A,
        activation_request,
        seed_observation,
        selection,
    )

    from axis_api.connector_source_activation import record_connector_source_activation
    from axis_api.db import session_scope
    from axis_api.persistence import AxisPersistenceRepository

    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    with session_scope(session_factory) as session:
        record_connector_source_activation(
            AxisPersistenceRepository(session),
            request=activation_request(),
            principal_scopes=[ACTIVATION_SCOPE],
            max_selections=10,
        )
    with session_scope(session_factory) as session:
        repo = AxisPersistenceRepository(session)
        observation = repo.get_data_resource_observation(TENANT_A, CONNECTOR_ID, RESOURCE_1)
        observation.schema_fingerprint = FINGERPRINT_B
    request = activation_request(
        selections=[
            {
                **selection("binding_revision_002", RESOURCE_1, FINGERPRINT_B),
                "supersedes_binding_id": "binding_unit_001",
            }
        ]
    )
    for expected in ["activated", "replayed"]:
        with session_scope(session_factory) as session:
            repo = AxisPersistenceRepository(session)
            result = record_connector_source_activation(
                repo, request=request, principal_scopes=[ACTIVATION_SCOPE], max_selections=10
            )
            assert result.bindings[0].outcome == expected
            old = repo.get_connector_source_binding(TENANT_A, "binding_unit_001")
            assert old.status == "superseded" and old.schema_fingerprint == FINGERPRINT_A
            assert result.bindings[0].supersedes_binding_id == old.binding_id


@pytest.fixture
def extraction_factory():
    from test_connector_source_extraction import session_factory as fixture

    yield from fixture.__wrapped__()


@pytest.mark.parametrize("change", ["none", "name", "type", "key", "version"])
def test_live_schema_is_checked_before_any_source_row(extraction_factory, monkeypatch, change):
    from test_connector_extraction_boundaries import SourceDriver
    from test_connector_source_extraction import (
        CONNECTOR_ID,
        RESOURCE,
        TENANT_A,
        make_runtime,
        seed_binding_and_observation,
    )

    from axis_api.db import session_scope
    from axis_api.persistence import AxisPersistenceRepository

    columns = [("id", "integer", True, True, "", "")]
    fingerprint = postgres_schema_fingerprint(columns)
    seed_binding_and_observation(extraction_factory, fingerprint=fingerprint)
    with session_scope(extraction_factory) as session:
        repo = AxisPersistenceRepository(session)
        binding = repo.get_connector_source_binding(TENANT_A, "binding_extract_001")
        observation = repo.get_data_resource_observation(TENANT_A, CONNECTOR_ID, RESOURCE)
        binding.schema_fingerprint_version = (
            "future_v3" if change == "version" else "postgres_schema_v2"
        )
        observation.schema_fingerprint_version = binding.schema_fingerprint_version

    class Driver(SourceDriver):
        def execute(self, query, params=None):
            super().execute(query, params)
            if "pg_catalog.pg_attribute" in self.statements[-1]:
                self.pending = [
                    {
                        "name": [("changed", "integer", True, True, "", "")],
                        "type": [("id", "bigint", True, True, "", "")],
                        "key": [("id", "integer", True, False, "", "")],
                    }.get(change, columns)
                ][0]

    driver = Driver([(1,)], True)
    dials = []

    def connect(*args, **kwargs):
        dials.append(1)
        return driver

    monkeypatch.setattr("psycopg.connect", connect)
    runtime = make_runtime(extraction_factory)
    with session_scope(extraction_factory) as session:
        outcome = runtime.extract_selection(
            repository=AxisPersistenceRepository(session),
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
            request_id="schema_request",
            batch_key="schema_batch",
            binding_id="binding_extract_001",
            resource_name=RESOURCE,
            pinned_schema_fingerprint=fingerprint,
            executed_by="synthetic_test",
        )
    assert outcome.ok == (change == "none")
    assert outcome.source_dial_performed == (change != "version")
    assert outcome.extraction_performed == (change == "none")
    if change != "none":
        assert outcome.reason == (
            "schema_version_incompatible" if change == "version" else "source_schema_drift"
        )
        assert not any(q.startswith("SELECT *") for q in driver.statements)
        assert outcome.payload_envelope is None


@pytest.mark.parametrize(
    "refusal", ["stale", "predecessor", "version", "scope", "second_selection"]
)
def test_replacement_refusal_keeps_predecessor_active(session_factory, refusal):
    import test_connector_source_activation as f

    from axis_api.connector_source_activation import (
        ConnectorSourceActivationConflict,
        ConnectorSourceActivationError,
        SourceActivationScopeDenied,
        record_connector_source_activation,
    )
    from axis_api.db import session_scope
    from axis_api.persistence import AxisPersistenceRepository

    f.seed_observation(session_factory, f.RESOURCE_1, f.FINGERPRINT_A)
    with session_scope(session_factory) as session:
        record_connector_source_activation(
            AxisPersistenceRepository(session),
            request=f.activation_request(),
            principal_scopes=[f.ACTIVATION_SCOPE],
            max_selections=10,
        )
    selection = {
        **f.selection("binding_new", f.RESOURCE_1, f.FINGERPRINT_A),
        "supersedes_binding_id": "binding_unit_001",
    }
    if refusal == "stale":
        selection["expected_schema_fingerprint"] = f.FINGERPRINT_B
    if refusal == "predecessor":
        selection["supersedes_binding_id"] = "foreign_predecessor"
    if refusal == "version":
        selection["expected_schema_fingerprint_version"] = "postgres_schema_v2"
    selections = [selection]
    if refusal == "second_selection":
        selections.append(f.selection("binding_missing", f.RESOURCE_2, f.FINGERPRINT_A))
    with (
        pytest.raises(
            (
                ConnectorSourceActivationError,
                ConnectorSourceActivationConflict,
                SourceActivationScopeDenied,
            )
        ),
        session_scope(session_factory) as session,
    ):
        record_connector_source_activation(
            AxisPersistenceRepository(session),
            request=f.activation_request(selections=selections),
            principal_scopes=[] if refusal == "scope" else [f.ACTIVATION_SCOPE],
            max_selections=10,
        )
    with session_scope(session_factory) as session:
        repo = AxisPersistenceRepository(session)
        assert repo.get_connector_source_binding(f.TENANT_A, "binding_unit_001").status == "active"
        assert repo.get_connector_source_binding(f.TENANT_A, "binding_new") is None
        assert (
            len(
                repo.list_audit_events(f.TENANT_A, event_type="connector.source.bindings.activated")
            )
            == 1
        )
