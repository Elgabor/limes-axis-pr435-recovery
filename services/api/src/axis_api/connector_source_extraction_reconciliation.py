"""Read-only reconciliation between the object store and batch metadata.

Extraction payloads and their metadata live in two stores that cannot commit
atomically. This service makes that boundary observable without touching
anything: it compares a deterministic set of tenant-scoped object-store keys —
derived from recorded request ids, never from a broad bucket scan — against
recorded batch metadata, and classifies every unit as ``clean_match``,
``digest_mismatch``, ``missing_object``, or ``orphaned_object``.

Dry-run is the ONLY mode. Deletion, mutation, repair, and network egress are
explicitly out of scope; a future repair action must be its own reviewed,
governed change.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, Field

from axis_api.persistence import AxisPersistenceRepository

RECONCILIATION_CLEAN = "clean_match"
RECONCILIATION_DIGEST_MISMATCH = "digest_mismatch"
RECONCILIATION_MISSING_OBJECT = "missing_object"
RECONCILIATION_ORPHANED_OBJECT = "orphaned_object"

# LocalObjectStore writes under `<root>/tenants/<tenant>/source-ingestion/…`
# with URI scheme `axis-local-object-store://<storage_key>`.
_LOCAL_URI_SCHEME = "axis-local-object-store://"


class ReconcilableObjectStore(Protocol):
    """The narrow read-only surface reconciliation needs."""

    def list_keys_under(self, prefixes: list[str]) -> set[str]:
        """Return stored keys strictly under the given explicit prefixes."""
        ...


class LocalReconcilableObjectStore:
    """Prefix-bounded listing over a local filesystem object store.

    Only files whose CANONICAL location sits inside ``root`` AND under one of
    the explicitly supplied prefixes are listed. Symlinks that resolve outside
    the root are silently skipped — an escaped link can never widen the scan.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def list_keys_under(self, prefixes: list[str]) -> set[str]:
        found: set[str] = set()
        for prefix in prefixes:
            clean = PurePosixPath(prefix)
            if clean.is_absolute() or any(
                part in {"", ".", ".."} for part in clean.parts
            ):
                raise ValueError(
                    "Reconciliation prefixes must be relative clean paths."
                )
            canonical_prefix = (self.root / clean).resolve()
            # Canonical containment: the prefix must live inside the root
            # after resolving every component.
            if (
                canonical_prefix != self.root
                and self.root not in canonical_prefix.parents
            ):
                raise ValueError("Reconciliation prefix escapes the store root.")
            if not canonical_prefix.exists():
                continue
            for path in canonical_prefix.rglob("*"):
                try:
                    canonical = path.resolve()
                except OSError:
                    continue  # unreadable entry: never follow into guessing
                if self.root not in canonical.parents and canonical != self.root:
                    continue  # symlink escape: skip, never report outside keys
                if canonical.is_file():
                    found.add(canonical.relative_to(self.root).as_posix())
        return found


class S3ListObjectsClient(Protocol):
    """Minimal paginated listing surface (mirrors the put-object protocol style)."""

    def list_objects_v2(
        self,
        bucket_name: str,
        prefix: str,
        *,
        continuation_token: str | None = None,
    ) -> dict[str, Any]:
        ...


class S3ReconcilableObjectStore:
    """Prefix-scoped, paginated listing over an S3-compatible store.

    Defence in depth: the request carries the prefix server-side AND every
    returned key must still start with one of the requested prefixes — a
    misbehaving or misconfigured client can never widen the scan. No network
    call happens unless the caller actually invokes :meth:`list_keys_under`.
    """

    def __init__(self, client: S3ListObjectsClient, bucket_name: str) -> None:
        self._client = client
        self._bucket_name = bucket_name

    def list_keys_under(self, prefixes: list[str]) -> set[str]:
        found: set[str] = set()
        for prefix in prefixes:
            if not prefix or prefix.startswith("/"):
                raise ValueError("S3 reconciliation prefixes must be relative.")
            token: str | None = None
            while True:
                response = (
                    self._client.list_objects_v2(self._bucket_name, prefix)
                    if token is None
                    else self._client.list_objects_v2(
                        self._bucket_name, prefix, continuation_token=token
                    )
                )
                # Response shape mirrors boto3: Contents[].Key + continuation.
                contents = response.get("Contents") or []
                for entry in contents:
                    key = entry.get("Key") if isinstance(entry, dict) else None
                    if isinstance(key, str) and key.startswith(prefix):
                        found.add(key)
                token = response.get("NextContinuationToken")
                if not token:
                    break
        return found

def local_store_key_from_uri(storage_uri: str) -> str | None:
    """Map an opaque local-store URI back to its storage key."""

    if storage_uri.startswith(_LOCAL_URI_SCHEME):
        return storage_uri[len(_LOCAL_URI_SCHEME):]
    return None


@dataclass(frozen=True)
class _RecordedBatch:
    batch_key: str
    digest_sha256: str
    stored_size_bytes: int


class SourceExtractionReconciliationFinding(BaseModel):
    classification: str = Field(
        pattern="^(clean_match|digest_mismatch|missing_object|orphaned_object)$"
    )
    batch_key: str | None = None
    storage_key: str | None = None


class SourceExtractionReconciliationReport(BaseModel):
    """Public-safe dry-run report; no row contents or secrets anywhere."""

    tenant_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    dry_run: bool = True
    clean_matches: int = Field(ge=0)
    digest_mismatches: int = Field(ge=0)
    missing_objects: int = Field(ge=0)
    orphaned_objects: int = Field(ge=0)
    findings: list[SourceExtractionReconciliationFinding] = Field(default_factory=list)


def _request_prefixes(tenant_id: str, request_id: str) -> list[str]:
    """The only key namespaces reconciliation is ever allowed to look at."""
    return [f"tenants/{tenant_id}/source-ingestion/{request_id}/"]


def reconcile_request_batches(
    repository: AxisPersistenceRepository,
    *,
    store: ReconcilableObjectStore,
    local_root: Path | None,
    tenant_id: str,
    request_id: str,
) -> SourceExtractionReconciliationReport | None:
    """Classify store-vs-DB truth for one request's extraction batches.

    Returns ``None`` when the ingestion request does not exist for this
    tenant. A recorded batch whose bytes hash to the recorded digest at the
    recorded size is a ``clean_match``; anything else is reported precisely.
    """
    request_row = repository.get_connector_source_ingestion_request(tenant_id, request_id)
    if request_row is None:
        return None

    recorded: dict[str, _RecordedBatch] = {}
    unmappable: list[str] = []
    for row in repository.get_connector_source_ingestion_request_batches(
        tenant_id,
        request_id,
        limit=10_000,
    ):
        key = local_store_key_from_uri(row.storage_uri)
        if key is None:
            # A batch written through another adapter cannot be verified here;
            # report it as missing rather than silently dropping durable truth.
            unmappable.append(row.batch_key)
            continue
        recorded[key] = _RecordedBatch(
            batch_key=row.batch_key,
            digest_sha256=row.digest_sha256,
            stored_size_bytes=row.stored_size_bytes,
        )

    stored_keys = store.list_keys_under(_request_prefixes(tenant_id, request_id))

    findings: list[SourceExtractionReconciliationFinding] = []
    clean = mismatches = missing = 0

    for batch_key in sorted(unmappable):
        missing += 1
        findings.append(
            SourceExtractionReconciliationFinding(
                classification=RECONCILIATION_MISSING_OBJECT,
                batch_key=batch_key,
                storage_key=None,
            )
        )

    for key in sorted(recorded):
        record = recorded[key]
        if key not in stored_keys:
            missing += 1
            findings.append(
                SourceExtractionReconciliationFinding(
                    classification=RECONCILIATION_MISSING_OBJECT,
                    batch_key=record.batch_key,
                    storage_key=key,
                )
            )
            continue
        path = local_root / key if local_root is not None else None
        matches = False
        if path is not None and path.is_file():
            encoded = path.read_bytes()
            # The runtime's envelope digest and the store's write-time checksum
            # are the same SHA-256 over the same canonical encoding, so the DB
            # row's digest plus size fully determine integrity here.
            matches = (
                len(encoded) == record.stored_size_bytes
                and hashlib.sha256(encoded).hexdigest() == record.digest_sha256
            )
        if matches:
            clean += 1
            findings.append(
                SourceExtractionReconciliationFinding(
                    classification=RECONCILIATION_CLEAN,
                    batch_key=record.batch_key,
                    storage_key=key,
                )
            )
        else:
            mismatches += 1
            findings.append(
                SourceExtractionReconciliationFinding(
                    classification=RECONCILIATION_DIGEST_MISMATCH,
                    batch_key=record.batch_key,
                    storage_key=key,
                )
            )

    orphaned = 0
    for key in sorted(stored_keys - set(recorded)):
        orphaned += 1
        findings.append(
            SourceExtractionReconciliationFinding(
                classification=RECONCILIATION_ORPHANED_OBJECT,
                storage_key=key,
            )
        )

    return SourceExtractionReconciliationReport(
        tenant_id=tenant_id,
        request_id=request_id,
        dry_run=True,
        clean_matches=clean,
        digest_mismatches=mismatches,
        missing_objects=missing,
        orphaned_objects=orphaned,
        findings=findings,
    )
