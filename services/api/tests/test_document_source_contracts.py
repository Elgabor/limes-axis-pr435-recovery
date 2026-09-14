from datetime import UTC, datetime, timedelta

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from axis_api.document_source_contracts import (
    DocumentChange,
    DocumentChangeError,
    DocumentIdentity,
    classify_document_change,
    parse_document_change,
)

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


@pytest.fixture
def change_data():
    return {
        "identity": {
            "tenant_id": "tenant-a", "connector_id": "documents-a",
            "provider": "microsoft_graph", "account_id": "source-account",
            "container_id": "shared-drive-a", "item_id": "file-a",
        },
        "event_id": "event-1",
        "kind": "observed",
        "change_reason": "content",
        "snapshot": {
            "kind": "file", "display_name": "private-filename-sentinel",
            "parent_item_id": "folder-a", "source_revision": "opaque-etag-z",
            "content_revision": "content-1", "media_type": "text/plain",
            "payload": {
                "artifact_id": "11111111-1111-4111-8111-111111111111",
                "sha256": "a" * 64, "byte_size": 19,
            },
            "handling_refs": ["handling-policy-a"],
            "acl": {
                "revision": "acl-1", "observed_at": NOW.isoformat(),
                "valid_until": (NOW + timedelta(minutes=5)).isoformat(),
                "completeness": "complete",
                "grants": [{
                    "source_account_id": "source-account", "principal_kind": "group",
                    "principal_id": "private-principal-sentinel", "mapping_ref": "mapping-a",
                    "inherited_from_item_id": "folder-a",
                }],
            },
        },
    }


@pytest.fixture
def change(change_data):
    return parse_document_change(change_data)


def successor(change, **updates):
    data = change.model_dump(mode="json") | {
        "event_id": "event-next", "supersedes_digest": change.digest(),
    } | updates
    return parse_document_change(data)


def remove(change, reason="access_lost", basis="access_denied"):
    return successor(
        change, kind="removed", snapshot=None, change_reason=None,
        removal={"reason": reason, "basis": basis},
    )


@pytest.mark.parametrize("provider", ["microsoft_graph", "google_drive"])
def test_file_and_inherited_group_observation_round_trip(change_data, provider):
    change_data["identity"]["provider"] = provider
    change = parse_document_change(change_data)
    restored = DocumentChange.model_validate_json(change.model_dump_json())
    assert restored == change
    assert restored.digest() == change.digest()
    assert restored.snapshot.acl.grants[0].inherited_from_item_id == "folder-a"
    assert restored.snapshot.handling_refs == ("handling-policy-a",)
    assert restored.ready_for_authorization(NOW)
    assert classify_document_change(None, restored) == "new"
    Draft202012Validator(DocumentChange.model_json_schema()).validate(
        restored.model_dump(mode="json")
    )


def test_folder_has_no_payload_and_move_preserves_identity(change_data):
    change_data["snapshot"].update(
        kind="folder", content_revision=None, media_type=None, payload=None,
    )
    folder = parse_document_change(change_data)
    snapshot = folder.snapshot.model_dump(mode="json") | {"parent_item_id": "folder-b"}
    moved = successor(folder, change_reason="metadata", snapshot=snapshot)
    assert classify_document_change(folder, moved) == "new"
    assert moved.identity.key() == folder.identity.key()
    assert moved.snapshot.payload is None
    assert moved.snapshot.parent_item_id == "folder-b"


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant-b"), ("connector_id", "documents-b"),
    ("provider", "google_drive"), ("account_id", "another-account"),
    ("container_id", "shared-drive-b"), ("item_id", "file-b"),
])
def test_document_keys_keep_every_namespace(change, field, value):
    identity = DocumentIdentity.model_validate(change.identity.model_dump() | {field: value})
    assert identity.key() != change.identity.key()


@pytest.mark.parametrize("status", ["partial", "unavailable"])
def test_incomplete_permissions_are_not_read_eligible(change_data, status):
    change_data["snapshot"]["acl"].update(completeness=status, grants=[])
    assert not parse_document_change(change_data).ready_for_authorization(NOW)


@pytest.mark.parametrize("kind,mapping", [
    ("user", None), ("group", None), ("domain", "mapping-a"), ("link", "mapping-a"),
])
def test_unresolved_and_unsupported_principals_remain_ineligible(change_data, kind, mapping):
    grant = change_data["snapshot"]["acl"]["grants"][0]
    grant.update(principal_kind=kind, mapping_ref=mapping)
    assert not parse_document_change(change_data).ready_for_authorization(NOW)


def test_empty_acl_is_not_public(change_data):
    change_data["snapshot"]["acl"]["grants"] = []
    assert not parse_document_change(change_data).ready_for_authorization(NOW)


def test_direct_user_mapping_is_evidence_not_an_authorization_result(change_data):
    change_data["snapshot"]["acl"]["grants"][0].update(
        principal_kind="user", inherited_from_item_id=None,
    )
    change = parse_document_change(change_data)
    assert change.ready_for_authorization(NOW)
    assert "authorized" not in change.model_dump()
    assert "allowed" not in change.evidence().model_dump()


@pytest.mark.parametrize("instant,expected", [
    (NOW - timedelta(microseconds=1), False), (NOW, True),
    (NOW + timedelta(minutes=5) - timedelta(microseconds=1), True),
    (NOW + timedelta(minutes=5), False),
])
def test_acl_validity_is_half_open_and_rejects_future_observations(change, instant, expected):
    assert change.ready_for_authorization(instant) is expected


def test_timezone_equivalence_preserves_digest_and_naive_clock_is_rejected(change_data):
    change = parse_document_change(change_data)
    change_data["snapshot"]["acl"].update(
        observed_at="2026-09-14T14:00:00+02:00", valid_until="2026-09-14T14:05:00+02:00",
    )
    assert parse_document_change(change_data).digest() == change.digest()
    with pytest.raises(ValueError, match="aware time"):
        change.ready_for_authorization(NOW.replace(tzinfo=None))


@pytest.mark.parametrize("reason,basis", [
    ("deleted", "explicit_source_delete"), ("access_lost", "access_denied"),
    ("out_of_scope", "scope_removed"),
])
def test_removal_keeps_source_deletion_separate_from_access_loss(change, reason, basis):
    removed = remove(change, reason, basis)
    assert classify_document_change(change, removed) == "new"
    assert removed.removal.reason == reason
    assert not removed.ready_for_authorization(NOW)
    assert removed.snapshot is None
    assert change.snapshot.payload.sha256 == "a" * 64


def test_incomplete_scan_cannot_be_used_as_deletion_evidence(change):
    with pytest.raises(DocumentChangeError, match="^invalid_document_change$"):
        remove(change, "deleted", "missing_from_partial_scan")
    with pytest.raises(DocumentChangeError, match="^invalid_document_change$"):
        remove(change, "deleted", "access_denied")


def test_exact_replay_is_idempotent_and_changed_duplicate_is_a_conflict(change):
    assert classify_document_change(change, change) == "duplicate"
    altered = DocumentChange.model_validate(
        change.model_dump(mode="json") | {"change_reason": "permissions"}
    )
    with pytest.raises(DocumentChangeError, match="^duplicate_conflict$"):
        classify_document_change(change, altered)


def test_stale_content_cannot_undo_permission_revocation(change):
    revoked_snapshot = change.snapshot.model_dump(mode="json")
    revoked_snapshot["acl"].update(revision="acl-2", grants=[])
    revoked = successor(change, snapshot=revoked_snapshot, change_reason="permissions")
    assert classify_document_change(change, revoked) == "new"
    assert not revoked.ready_for_authorization(NOW)
    stale_content = successor(change, event_id="stale-content")
    with pytest.raises(DocumentChangeError, match="^revision_conflict$"):
        classify_document_change(revoked, stale_content)


def test_tombstone_requires_explicit_restore_even_with_current_predecessor(change):
    removed = remove(change)
    observed = successor(change, supersedes_digest=removed.digest(), event_id="late-content")
    with pytest.raises(DocumentChangeError, match="^explicit_restore_required$"):
        classify_document_change(removed, observed)
    restored = successor(
        change, kind="restored", event_id="restore-1", supersedes_digest=removed.digest(),
        restoration_evidence_ref="host-revalidation-a",
    )
    assert classify_document_change(removed, restored) == "new"
    assert classify_document_change(restored, restored) == "duplicate"
    with pytest.raises(DocumentChangeError, match="^revision_conflict$"):
        classify_document_change(None, restored)


def test_restore_cannot_replace_a_live_observation(change):
    restored = successor(change, kind="restored", restoration_evidence_ref="revalidation")
    with pytest.raises(DocumentChangeError, match="^revision_conflict$"):
        classify_document_change(change, restored)


def test_cross_tenant_transition_is_rejected(change_data, change):
    change_data["identity"]["tenant_id"] = "tenant-b"
    other = parse_document_change(change_data)
    with pytest.raises(DocumentChangeError, match="^context_mismatch$"):
        classify_document_change(change, other)


def test_source_versions_are_opaque_not_lexically_ordered(change):
    snapshot = change.snapshot.model_dump(mode="json") | {
        "source_revision": "opaque-etag-a", "content_revision": "content-2",
    }
    edited = successor(change, snapshot=snapshot)
    assert classify_document_change(change, edited) == "new"
    assert edited.snapshot.source_revision < change.snapshot.source_revision


def test_error_and_evidence_do_not_contain_source_metadata(change_data, change):
    with pytest.raises(DocumentChangeError) as error:
        parse_document_change(change_data | {"private-field-sentinel": "secret-value"})
    assert str(error.value) == "invalid_document_change"
    assert error.value.__suppress_context__
    evidence = change.evidence().model_dump_json()
    for hidden in ["private-filename-sentinel", "private-principal-sentinel", "source-account"]:
        assert hidden not in evidence
    assert change.evidence().payload_present
    assert change.evidence().change_digest == change.digest()


@pytest.mark.parametrize("path,value", [
    (("version",), "2.0"),
    (("snapshot", "acl", "grants", 0, "source_account_id"), "another-account"),
    (("snapshot", "payload", "artifact_id"), "https://signed.invalid/token"),
    (("snapshot", "payload", "bytes"), "private-content"),
    (("snapshot", "parent_item_id"), "file-a"),
    (("snapshot", "kind"), "folder"),
    (("snapshot", "content_revision"), None),
    (("snapshot", "acl", "valid_until"), NOW.isoformat()),
    (("snapshot", "acl", "observed_at"), "2026-09-14T12:00:00"),
    (("snapshot", "acl", "completeness"), "unavailable"),
    (("kind",), "restored"),
    (("snapshot", "payload", "byte_size"), -1),
    (("snapshot",), None),
    (("kind",), "removed"),
])
def test_invalid_structures_fail_closed(change_data, path, value):
    target = change_data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(DocumentChangeError, match="^invalid_document_change$"):
        parse_document_change(change_data)


def test_permission_evidence_has_a_bounded_grant_count(change_data):
    change_data["snapshot"]["acl"]["grants"] *= 1_025
    with pytest.raises(DocumentChangeError, match="^invalid_document_change$"):
        parse_document_change(change_data)


def test_observations_are_immutable(change):
    with pytest.raises(ValidationError):
        change.snapshot.acl.completeness = "partial"
    with pytest.raises(ValidationError):
        change.snapshot.acl.grants[0].mapping_ref = "other-mapping"
