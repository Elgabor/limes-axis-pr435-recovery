"""Document observations for future source adapters; no storage or access authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from axis_sdk.connector_authoring.contracts import ContractModel, Digest, Identifier
from pydantic import AwareDatetime, Field, ValidationError, field_validator, model_validator

Provider = Literal["microsoft_graph", "google_drive"]


def _digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class DocumentIdentity(ContractModel):
    tenant_id: Identifier
    connector_id: Identifier
    provider: Provider
    account_id: Identifier
    container_id: Identifier
    item_id: Identifier

    def key(self) -> str:
        """Account and container are namespaces, not user-facing display names."""
        return _digest(self.model_dump(mode="json"))


class DocumentPayloadReference(ContractModel):
    artifact_id: UUID
    sha256: Digest
    byte_size: int = Field(ge=0, strict=True)


class DocumentGrant(ContractModel):
    source_account_id: Identifier
    principal_kind: Literal["user", "group", "domain", "link"]
    principal_id: Identifier = Field(repr=False)
    mapping_ref: Identifier | None = Field(default=None, repr=False)
    inherited_from_item_id: Identifier | None = None


class DocumentACLObservation(ContractModel):
    revision: Identifier
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    completeness: Literal["complete", "partial", "unavailable"]
    grants: tuple[DocumentGrant, ...] = Field(default=(), max_length=1_024, repr=False)

    @field_validator("observed_at", "valid_until")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        try:
            return value.astimezone(UTC)
        except OverflowError:
            raise ValueError("Observation time is outside the supported range") from None

    @model_validator(mode="after")
    def coherent_observation(self) -> DocumentACLObservation:
        if self.valid_until <= self.observed_at:
            raise ValueError("Observation validity must follow capture time")
        if self.completeness == "unavailable" and self.grants:
            raise ValueError("Unavailable permission evidence cannot contain grants")
        return self

    def ready_for_authorization(self, now: datetime) -> bool:
        """Necessary evidence only; the current trust layer must still authorize each read."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Authorization evaluation requires an aware time")
        return (
            self.completeness == "complete"
            and self.observed_at <= now < self.valid_until
            and bool(self.grants)
            and all(
                grant.mapping_ref is not None and grant.principal_kind in {"user", "group"}
                for grant in self.grants
            )
        )


class DocumentSnapshot(ContractModel):
    kind: Literal["file", "folder"]
    display_name: str = Field(min_length=1, max_length=512, repr=False)
    parent_item_id: Identifier | None = None
    source_revision: Identifier
    content_revision: Identifier | None = None
    media_type: str | None = Field(default=None, min_length=3, max_length=128)
    payload: DocumentPayloadReference | None = None
    acl: DocumentACLObservation
    handling_refs: tuple[Identifier, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def content_boundary(self) -> DocumentSnapshot:
        if self.kind == "folder" and (
            self.content_revision is not None
            or self.media_type is not None
            or self.payload is not None
        ):
            raise ValueError("Folders cannot carry file content")
        if self.kind == "file" and (self.content_revision is None or self.media_type is None):
            raise ValueError("Files require a content revision and media type")
        return self


class DocumentRemoval(ContractModel):
    reason: Literal["deleted", "access_lost", "out_of_scope"]
    basis: Literal["explicit_source_delete", "access_denied", "scope_removed"]

    @model_validator(mode="after")
    def explicit_evidence(self) -> DocumentRemoval:
        expected = {
            "deleted": "explicit_source_delete",
            "access_lost": "access_denied",
            "out_of_scope": "scope_removed",
        }
        if self.basis != expected[self.reason]:
            raise ValueError("Removal reason does not match its observation basis")
        return self


class DocumentChange(ContractModel):
    """Full observation candidate; source revisions are opaque and are never sorted."""

    version: Literal["1.0"] = "1.0"
    identity: DocumentIdentity
    event_id: Identifier = Field(repr=False)
    supersedes_digest: Digest | None = None
    kind: Literal["observed", "removed", "restored"]
    change_reason: Literal["content", "metadata", "permissions"] | None = None
    snapshot: DocumentSnapshot | None = Field(default=None, repr=False)
    removal: DocumentRemoval | None = None
    restoration_evidence_ref: Identifier | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def coherent_change(self) -> DocumentChange:
        if self.kind == "removed":
            if self.removal is None or self.snapshot is not None or self.change_reason is not None:
                raise ValueError("Removal requires a tombstone, not document content")
        elif self.snapshot is None or self.removal is not None or self.change_reason is None:
            raise ValueError("Document observations require a snapshot and change reason")
        if (self.kind == "restored") != (self.restoration_evidence_ref is not None):
            raise ValueError("Only explicit restoration carries revalidation evidence")
        if self.snapshot is not None:
            if self.snapshot.parent_item_id == self.identity.item_id:
                raise ValueError("An item cannot be its own parent")
            if any(
                grant.source_account_id != self.identity.account_id
                for grant in self.snapshot.acl.grants
            ):
                raise ValueError("Permission principals must use the source account namespace")
        return self

    def digest(self) -> str:
        return _digest(self.model_dump(mode="json"))

    def evidence(self) -> DocumentChangeEvidence:
        """No names, grants, source IDs, bearer URLs or document bytes in ordinary audit."""
        return DocumentChangeEvidence(
            document_key=self.identity.key(),
            change_digest=self.digest(),
            kind=self.kind,
            payload_present=self.snapshot is not None and self.snapshot.payload is not None,
        )

    def ready_for_authorization(self, now: datetime) -> bool:
        return self.snapshot is not None and self.snapshot.acl.ready_for_authorization(now)


class DocumentChangeEvidence(ContractModel):
    document_key: Digest
    change_digest: Digest
    kind: Literal["observed", "removed", "restored"]
    payload_present: bool


class DocumentChangeError(ValueError):
    """Fixed codes only; source metadata and validation details are not public errors."""

    def __init__(
        self,
        code: Literal[
            "invalid_document_change", "context_mismatch", "revision_conflict",
            "duplicate_conflict", "explicit_restore_required",
        ],
    ) -> None:
        self.code = code
        super().__init__(code)


def parse_document_change(value: object) -> DocumentChange:
    try:
        return DocumentChange.model_validate(value)
    except ValidationError:
        raise DocumentChangeError("invalid_document_change") from None


def classify_document_change(
    previous: DocumentChange | None,
    incoming: DocumentChange,
) -> Literal["new", "duplicate"]:
    """Optimistic precondition only; the existing host must fence and persist atomically."""
    if previous is None:
        if incoming.supersedes_digest is not None or incoming.kind == "restored":
            raise DocumentChangeError("revision_conflict")
        return "new"
    if previous.identity != incoming.identity:
        raise DocumentChangeError("context_mismatch")
    if previous.event_id == incoming.event_id:
        if previous.digest() != incoming.digest():
            raise DocumentChangeError("duplicate_conflict")
        return "duplicate"
    if incoming.supersedes_digest != previous.digest():
        raise DocumentChangeError("revision_conflict")
    if previous.kind == "removed" and incoming.kind == "observed":
        raise DocumentChangeError("explicit_restore_required")
    if incoming.kind == "restored" and previous.kind != "removed":
        raise DocumentChangeError("revision_conflict")
    return "new"
