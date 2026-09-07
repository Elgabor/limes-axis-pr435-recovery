"""Disposable ingestion workloads, never registered as production connectors.

REST uses an in-process HTTP transport; database uses a read-only SQLite cursor;
documents use UTF-8 files. Objects exercise the actual S3ObjectSource against a
file-backed provider double. None of these fixtures can dial an external source.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Literal

import httpx
from axis_sdk.connector_authoring import (
    Checkpoint,
    ConnectorError,
    ErrorCode,
    OperationContext,
    ReadBatch,
    ReadLimits,
    ReadRequest,
    ResourceSelection,
)
from axis_sdk.connector_authoring.contracts import batch_byte_size
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from axis_api.connector_s3_source import S3ObjectSource
from axis_api.s3_source_profile import S3SourceProfile

KINDS = ("rest", "database", "object", "document")
SourceKind = Literal["rest", "database", "object", "document"]
PROVENANCE = {
    "rest": "httpx MockTransport; paginated JSON fixture; no REST production adapter",
    "database": "SQLite read-only keyset cursor; not PostgreSQL driver or capacity",
    "object": "production S3ObjectSource; file-backed provider double; not S3/MinIO transport",
    "document": "UTF-8 file fixture; no Microsoft 365 or Google Workspace adapter",
}


def canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class Workload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    records: int = Field(default=128, ge=1, le=1000)
    text_bytes: int = Field(default=2048, ge=32, le=16_384)
    page_records: int = Field(default=16, ge=1, le=100)
    page_bytes: int = Field(default=131_072, ge=1024, le=1_048_576)
    job_bytes: int = Field(default=5_000_000, ge=1024, le=5_000_000)
    max_pages: int = Field(default=100, ge=1, le=1000)
    request_seconds: int = Field(default=30, ge=1, le=30)
    source_delay_ms: int = Field(default=2, ge=0, le=20)
    sink_delay_ms: int = Field(default=2, ge=0, le=20)
    # The heavy tenant is offered first to expose head-of-line waiting.
    heavy_jobs: int = Field(default=12, ge=1, le=32)
    light_jobs: int = Field(default=3, ge=1, le=16)
    queue_capacity: int = Field(default=24, ge=1, le=64)
    tenant_queue_capacity: int = Field(default=12, ge=1, le=32)
    workers: int = Field(default=4, ge=1, le=8)

    @model_validator(mode="after")
    def complete_fixture_fits(self):
        if self.page_records > self.records:
            raise ValueError("page_records must fit the fixture")
        # Include S3's base64 expansion and metadata, which is the widest shape.
        largest_row = 4 * ((self.text_bytes + 128 + 2) // 3) + 1024
        if largest_row * self.page_records + 2 > self.page_bytes:
            raise ValueError("page_bytes must fit the declared fixture page")
        if self.max_pages * self.page_records < self.records:
            raise ValueError("max_pages must permit the complete fixture")
        if largest_row * self.records > self.job_bytes:
            raise ValueError("job_bytes must fit the complete fixture")
        return self


@dataclass(frozen=True)
class Position:
    checkpoint: Checkpoint | None = None
    inventory: dict | None = None


class ObjectBody(BytesIO):
    def __init__(self, content: bytes, etag: str):
        super().__init__(content)
        self.status = 200
        self.headers = {"ETag": etag, "Content-Length": str(len(content))}

    def release_conn(self):
        pass  # BytesIO owns no pooled connection.


class FileObjectProvider:
    def __init__(self, root: Path, metadata: tuple):
        self.root = root
        self.metadata = metadata
        self.by_key = {item.object_name: item for item in metadata}

    def list_objects(self, _bucket, *, prefix, recursive):
        assert recursive and prefix == "approved/"
        yield from self.metadata

    def get_object(self, _bucket, key, *, request_headers):
        # Keys are fixture-generated and allowlisted, not arbitrary input paths.
        item = self.by_key[key]
        if request_headers != {"If-Match": f'"{item.etag}"'}:
            raise ValueError("fixture precondition failed")
        return ObjectBody((self.root / key).read_bytes(), item.etag)


class Corpus:
    def __init__(self, root: Path, workload: Workload):
        self.root, self.workload = root, workload
        self.revision = digest(workload.model_dump())
        self.metadata = {}
        self.expected = {}
        database = sqlite3.connect(root / "source.sqlite")
        try:
            database.execute(
                "CREATE TABLE records (tenant TEXT, id INTEGER, text TEXT, "
                "PRIMARY KEY (tenant, id))"
            )
            for tenant in ("heavy", "light-a", "light-b"):
                directory = root / tenant
                (directory / "approved").mkdir(parents=True)
                metadata = []
                object_rows = {}
                hashes = {kind: hashlib.sha256() for kind in KINDS}
                for index in range(workload.records):
                    # Include multibyte text; byte accounting cannot use string length.
                    payload = ("é" * (workload.text_bytes // 2)) + "x" * (workload.text_bytes % 2)
                    row = {"id": index, "tenant": tenant, "text": payload}
                    encoded = canonical(row)
                    (directory / f"{index:06d}.json").write_bytes(encoded)
                    (directory / f"{index:06d}.txt").write_text(payload, encoding="utf-8")
                    key = f"approved/{index:06d}.json"
                    (directory / key).write_bytes(encoded)
                    etag = hashlib.sha256(encoded).hexdigest()
                    metadata.append(
                        SimpleNamespace(
                            object_name=key,
                            etag=etag,
                            size=len(encoded),
                            is_dir=False,
                        )
                    )
                    database.execute(
                        "INSERT INTO records VALUES (?, ?, ?)", (tenant, index, payload)
                    )
                    expected = {
                        "rest": row,
                        "database": row,
                        "document": {"document_id": str(index), "tenant": tenant, "text": payload},
                        "object": {
                            "object_id": hashlib.sha256(key.encode()).hexdigest(),
                            "object_key": key,
                            "kind": "upsert",
                            "content_sha256": etag,
                            "size_bytes": len(encoded),
                            "content_base64": base64.b64encode(encoded).decode(),
                        },
                    }
                    for kind, value in expected.items():
                        if kind == "object":
                            object_rows[value["object_id"]] = value
                        else:
                            hashes[kind].update(canonical(value) + b"\n")
                for identity in sorted(object_rows):
                    hashes["object"].update(canonical(object_rows[identity]) + b"\n")
                self.metadata[tenant] = tuple(metadata)
                for kind in KINDS:
                    self.expected[kind, tenant] = hashes[kind].hexdigest()
            database.commit()
        finally:
            database.close()

    @contextmanager
    def source(self, kind: SourceKind, tenant: str):
        if kind not in KINDS or tenant not in self.metadata:
            raise ValueError("unknown fixture source or tenant")
        source = FixtureSource(self, kind, tenant)
        try:
            yield source
        finally:
            source.close()


@contextmanager
def corpus(workload: Workload):
    with TemporaryDirectory(prefix="axis-ingestion-fixture-") as directory:
        yield Corpus(Path(directory), workload)


class FixtureSource:
    def __init__(self, corpus: Corpus, kind: SourceKind, tenant: str):
        self.corpus, self.kind, self.tenant = corpus, kind, tenant
        self.workload = corpus.workload
        self.context = OperationContext(
            tenant_id=tenant,
            connector_id=f"benchmark_{kind}",
            actor_id="fixture",
            operation_id="read",
        )
        self.resource = ResourceSelection(
            resource_id="fixture",
            schema_fingerprint=digest({"kind": kind}),
            source_revision=corpus.revision,
        )
        self.limits = ReadLimits(
            max_records=self.workload.page_records,
            max_bytes=self.workload.page_bytes,
            time_budget_seconds=self.workload.request_seconds,
        )
        self.connection = None
        self.client = None
        if kind == "database":
            self.connection = sqlite3.connect(
                (corpus.root / "source.sqlite").as_uri() + "?mode=ro", uri=True
            )
        elif kind == "rest":
            self.client = httpx.Client(
                transport=httpx.MockTransport(self._rest),
                base_url="https://fixture.invalid",
                trust_env=False,
                follow_redirects=False,
            )
        elif kind == "object":
            self.profile = S3SourceProfile(
                tenant_id=tenant,
                profile_id="benchmark",
                endpoint="https://fixture.invalid",
                bucket="fixture",
                prefix="approved/",
                credential_secret_ref="env://NOT_RESOLVED",
                private_endpoint_ref="fixture",
                max_objects=1000,
                max_object_bytes=32_768,
            )
            self.provider = FileObjectProvider(corpus.root / tenant, corpus.metadata[tenant])
            source = S3ObjectSource(self.profile, self.provider)
            self.resource = source.selection
            self.context = self.context.model_copy(
                update={"connector_id": source.descriptor.connector_id}
            )

    def close(self):
        if self.connection is not None:
            self.connection.close()
        if self.client is not None:
            self.client.close()

    def _rest(self, request):
        # The HTTP encoder/decoder and status handling execute; no socket is opened.
        if request.url.host != "fixture.invalid" or request.url.path != "/records":
            return httpx.Response(404)
        offset = int(request.url.params["offset"])
        rows = [
            json.loads((self.corpus.root / self.tenant / f"{index:06d}.json").read_bytes())
            for index in range(offset, min(offset + self.limits.max_records, self.workload.records))
        ]
        return httpx.Response(200, content=canonical(rows))

    def read(self, position: Position) -> tuple[ReadBatch, Position]:
        request = ReadRequest(
            context=self.context,
            resource=self.resource,
            limits=self.limits,
            checkpoint=position.checkpoint,
        )
        deadline = monotonic() + self.limits.time_budget_seconds
        sleep(self.workload.source_delay_ms / 1000)
        if self.kind == "object":
            source = S3ObjectSource(self.profile, self.provider, inventory=position.inventory)
            batch = source.read(request)
            if monotonic() >= deadline:
                raise ConnectorError(ErrorCode.TIME_BUDGET_EXCEEDED)
            return batch, Position(batch.checkpoint, source.next_inventory)
        offset = 0
        if position.checkpoint:
            token = position.checkpoint.cursor.get_secret_value()
            if not token.isascii() or not token.isdecimal() or len(token) > 4:
                raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
            offset = int(token)
            if str(offset) != token or offset > self.workload.records:
                raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
        stop = min(offset + self.limits.max_records, self.workload.records)
        if self.kind == "database":
            cursor = self.connection.execute(
                "SELECT id, tenant, text FROM records WHERE tenant = ? AND id >= ? "
                "ORDER BY id LIMIT ?",
                (self.tenant, offset, self.limits.max_records),
            )
            try:
                rows = [dict(zip(("id", "tenant", "text"), row, strict=True)) for row in cursor]
            finally:
                cursor.close()
        elif self.kind == "rest":
            response = self.client.get("/records", params={"offset": offset})
            response.raise_for_status()
            if len(response.content) > self.limits.max_bytes:
                raise ConnectorError(ErrorCode.LIMIT_EXCEEDED)
            rows = response.json()
        else:
            rows = [
                {
                    "document_id": str(index),
                    "tenant": self.tenant,
                    "text": (self.corpus.root / self.tenant / f"{index:06d}.txt").read_text(
                        encoding="utf-8"
                    ),
                }
                for index in range(offset, stop)
            ]
        if monotonic() >= deadline:
            raise ConnectorError(ErrorCode.TIME_BUDGET_EXCEEDED)
        if len(rows) != stop - offset or batch_byte_size(tuple(rows)) > self.limits.max_bytes:
            raise ConnectorError(ErrorCode.LIMIT_EXCEEDED)
        batch = ReadBatch(
            records=tuple(rows),
            completion="complete" if stop == self.workload.records else "more",
            checkpoint=Checkpoint(
                tenant_id=self.tenant,
                connector_id=self.context.connector_id,
                protocol=self.context.protocol,
                resource=self.resource,
                cursor=SecretStr(str(stop)),
            ),
        )
        batch.validate_for(request)
        return batch, Position(batch.checkpoint)
