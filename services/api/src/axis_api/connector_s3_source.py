"""Bounded S3 object reads implementing connector authoring protocol 1.0.

The host supplies an authorized client and committed inventory. This adapter
proposes progress; it owns no credentials, database transaction or checkpoint
commit. Raw keys/bytes occur only in the payload batch, never its evidence.
"""

import base64
import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from axis_sdk.connector_authoring.contracts import (
    Checkpoint,
    ConnectorError,
    DiscoveredResource,
    DiscoveryRequest,
    DiscoveryResult,
    ErrorCode,
    HealthResult,
    OperationContext,
    ReadBatch,
    ReadRequest,
    ResourceSelection,
    SourceDescriptor,
    SourceField,
    batch_byte_size,
    negotiate_protocol,
)
from minio.error import MinioException
from urllib3.exceptions import HTTPError

from axis_api.connectors import csv_header_fingerprint
from axis_api.s3_source_profile import S3_SOURCE_CONNECTOR_ID, S3SourceProfile

OBJECT_FIELDS = (
    "object_id",
    "object_key",
    "kind",
    "content_sha256",
    "size_bytes",
    "content_base64",
)
OBJECT_SCHEMA_FINGERPRINT = csv_header_fingerprint(list(OBJECT_FIELDS))


@dataclass
class S3ReadProgress:
    """Attempt facts shared with the host, including reads that later fail."""

    source_dial_performed: bool = False
    extraction_performed: bool = False


def inventory_digest(inventory: dict) -> str:
    return hashlib.sha256(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validated_inventory(value: Any, *, maximum: int) -> dict:
    """Only bounded object identities, validators and digests may enter SQL state."""
    if not isinstance(value, dict) or len(value) > maximum:
        raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
    for key, item in value.items():
        if (
            not _digest(key)
            or not isinstance(item, dict)
            or set(item) != {"etag_sha256", "content_sha256", "size_bytes"}
            or not _digest(item["etag_sha256"])
            or not _digest(item["content_sha256"])
            or type(item["size_bytes"]) is not int
            or item["size_bytes"] < 0
        ):
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
    return deepcopy(value)


def _digest(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


class S3ObjectSource:
    descriptor = SourceDescriptor(
        connector_id=S3_SOURCE_CONNECTOR_ID,
        capabilities=frozenset({"discovery", "read", "health"}),
    )

    def __init__(
        self,
        profile: S3SourceProfile,
        client,
        *,
        inventory=None,
        clock=None,
        authorization_deadline=None,
        set_network_deadline=None,
    ):
        self.profile = profile
        self.client = client
        self.inventory = validated_inventory(
            {} if inventory is None else inventory, maximum=profile.max_objects
        )
        self.next_inventory: dict | None = None
        self.clock = clock or time.monotonic
        self.authorization_deadline = authorization_deadline
        self.set_network_deadline = set_network_deadline
        self.progress = S3ReadProgress()

    @property
    def selection(self) -> ResourceSelection:
        return ResourceSelection(
            resource_id=self.profile.resource_name,
            schema_fingerprint=OBJECT_SCHEMA_FINGERPRINT,
            source_revision=self.profile.revision,
        )

    def _context(self, context: OperationContext) -> None:
        if (
            context.protocol != negotiate_protocol(self.descriptor, required=frozenset({"read"}))
            or context.tenant_id != self.profile.tenant_id
            or context.connector_id != S3_SOURCE_CONNECTOR_ID
        ):
            raise ConnectorError(ErrorCode.CONTEXT_MISMATCH)

    def health(self, context: OperationContext) -> HealthResult:
        self._context(context)
        if self.authorization_deadline is not None:
            self._deadline(self.authorization_deadline)
        try:
            self.progress.source_dial_performed = True
            exists = self.client.bucket_exists(self.profile.bucket)
        except (MinioException, HTTPError, OSError):
            return HealthResult(status="unavailable", reason=ErrorCode.SOURCE_UNAVAILABLE)
        return (
            HealthResult(status="ready")
            if exists
            else HealthResult(
                status="unavailable",
                reason=ErrorCode.RESOURCE_MISMATCH,
            )
        )

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        self._context(request.context)
        health = self.health(request.context)
        if health.status != "ready":
            raise ConnectorError(health.reason)
        result = DiscoveryResult(
            resources=(
                DiscoveredResource(
                    **self.selection.model_dump(),
                    fields=tuple(
                        SourceField(
                            name=name,
                            value_type="integer" if name == "size_bytes" else "string",
                            nullable=name in {"object_key", "content_base64"},
                        )
                        for name in OBJECT_FIELDS
                    ),
                ),
            )
        )
        result.validate_for(request)
        return result

    def read(self, request: ReadRequest) -> ReadBatch:
        self.next_inventory = None
        self._context(request.context)
        if request.resource != self.selection:
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
        if request.checkpoint:
            if request.checkpoint.cursor.get_secret_value() != inventory_digest(self.inventory):
                raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
        elif self.inventory:
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
        deadline = self.clock() + request.limits.time_budget_seconds
        if self.authorization_deadline is not None:
            deadline = min(deadline, self.authorization_deadline)
        self._deadline(deadline)
        if self.set_network_deadline is not None:
            self.set_network_deadline(deadline)
        try:
            return self._read(request, deadline)
        except (MinioException, HTTPError, OSError):
            # Neither source messages nor chained exceptions are evidence.
            raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE) from None

    def _deadline(self, deadline: float) -> None:
        if self.clock() >= deadline:
            raise ConnectorError(ErrorCode.TIME_BUDGET_EXCEEDED)

    def _listed(self, deadline: float) -> dict:
        current = {}
        scanned = 0
        self.progress.source_dial_performed = True
        for item in self.client.list_objects(
            self.profile.bucket, prefix=self.profile.prefix, recursive=True
        ):
            self._deadline(deadline)
            scanned += 1
            if scanned > self.profile.max_objects:
                # A truncated enumeration can never justify absence/deletion.
                raise ConnectorError(ErrorCode.LIMIT_EXCEEDED)
            key = item.object_name
            if (
                not isinstance(key, str)
                or not key.startswith(self.profile.prefix)
                or len(key.encode()) > 1024
                or any(part in {".", ".."} for part in key.split("/"))
                or "\\" in key
                or any(ord(character) < 32 or ord(character) == 127 for character in key)
            ):
                raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
            if item.is_dir or not any(
                key.lower().endswith(suffix) for suffix in self.profile.allowed_suffixes
            ):
                continue
            if (
                type(item.size) is not int
                or item.size < 0
                or not isinstance(item.etag, str)
                or not 1 <= len(item.etag) <= 200
                or any(ord(c) < 33 or ord(c) > 126 or c in {'"', "\\"} for c in item.etag)
            ):
                raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE)
            identity = hashlib.sha256(key.encode()).hexdigest()
            if identity in current:
                raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE)
            current[identity] = item
        self._deadline(deadline)
        return current

    def _read(self, request: ReadRequest, deadline: float) -> ReadBatch:
        current = self._listed(deadline)
        inventory = deepcopy(self.inventory)
        records = []
        used_bytes = 2  # Canonical JSON array brackets; append costs include commas.
        more = False
        # Entire listing completed before any tombstone is even considered.
        work = [*sorted(set(inventory) - set(current)), *sorted(current)]
        for identity in work:
            self._deadline(deadline)
            item = current.get(identity)
            previous = inventory.get(identity)
            if item is None:
                record = {
                    "object_id": identity,
                    "object_key": None,
                    "kind": "observed_absent",
                    "content_sha256": previous["content_sha256"],
                    "size_bytes": 0,
                    "content_base64": None,
                }
                candidate = None
            else:
                validator = hashlib.sha256(item.etag.encode()).hexdigest()
                if (
                    previous
                    and previous["etag_sha256"] == validator
                    and previous["size_bytes"] == item.size
                ):
                    continue
                if item.size > self.profile.max_object_bytes:
                    raise ConnectorError(ErrorCode.RECORD_TOO_LARGE)
                # Bound emitted bytes before downloading an object that cannot fit.
                record = {
                    "object_id": identity,
                    "object_key": item.object_name,
                    "kind": "upsert",
                    "content_sha256": "0" * 64,
                    "size_bytes": item.size,
                    "content_base64": "",
                }
                encoded_size = 4 * ((item.size + 2) // 3)
                record_bytes = batch_byte_size((record,)) - 2 + encoded_size
                if record_bytes + 2 > request.limits.max_bytes:
                    raise ConnectorError(ErrorCode.RECORD_TOO_LARGE)
                if len(records) >= request.limits.max_records or (
                    used_bytes + (1 if records else 0) + record_bytes > request.limits.max_bytes
                ):
                    more = True
                    break
                content = self._object_bytes(item, deadline)
                digest = hashlib.sha256(content).hexdigest()
                candidate = {
                    "etag_sha256": validator,
                    "content_sha256": digest,
                    "size_bytes": len(content),
                }
                if previous and previous["content_sha256"] == digest:
                    # Changed transport validator with identical content is not a new payload.
                    inventory[identity] = candidate
                    continue
                record.update(
                    content_sha256=digest, content_base64=base64.b64encode(content).decode("ascii")
                )
            projected_bytes = used_bytes + (1 if records else 0) + batch_byte_size((record,)) - 2
            if (
                len(records) >= request.limits.max_records
                or projected_bytes > request.limits.max_bytes
            ):
                more = True
                break
            records.append(record)
            used_bytes = projected_bytes
            if candidate is None:
                del inventory[identity]
            else:
                inventory[identity] = candidate
        self._deadline(deadline)
        checkpoint = Checkpoint(
            tenant_id=request.context.tenant_id,
            connector_id=request.context.connector_id,
            protocol=request.context.protocol,
            resource=request.resource,
            cursor=inventory_digest(inventory),
        )
        batch = ReadBatch(
            records=tuple(records), completion="more" if more else "complete", checkpoint=checkpoint
        )
        batch.validate_for(request)
        self.next_inventory = inventory
        return batch

    def _object_bytes(self, item, deadline: float) -> bytes:
        self._deadline(deadline)
        self.progress.extraction_performed = True
        response = self.client.get_object(
            self.profile.bucket,
            item.object_name,
            request_headers={"If-Match": f'"{item.etag}"'},
        )
        try:
            if (
                response.status != 200
                or response.headers.get("ETag", "").strip('"') != item.etag
                or response.headers.get("Content-Length") != str(item.size)
            ):
                raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE)
            content = bytearray()
            while True:
                self._deadline(deadline)
                chunk = response.read(min(65_536, item.size + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > item.size:
                    raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE)
            if len(content) != item.size:
                raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE)
            return bytes(content)
        finally:
            response.close()
            response.release_conn()
