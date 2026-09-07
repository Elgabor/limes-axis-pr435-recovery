"""Deployment-owned S3 input scopes; credentials remain lease-scoped references."""

import hashlib
import json
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

S3_SOURCE_CONNECTOR_ID = "s3_object_storage"


class S3SourceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    tenant_id: str = Field(min_length=1, max_length=80)
    profile_id: str = Field(min_length=1, max_length=180)
    endpoint: str = Field(min_length=1, max_length=300)
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    prefix: str = Field(min_length=1, max_length=500)
    allowed_suffixes: list[str] = Field(default_factory=lambda: [".json", ".jsonl", ".csv"])
    credential_secret_ref: str = Field(pattern=r"^env://[A-Z][A-Z0-9_]*$")
    private_endpoint_ref: str = Field(min_length=1, max_length=200)
    region: str = Field(default="us-east-1", min_length=1, max_length=80)
    max_objects: int = Field(default=1_000, ge=1, le=10_000)
    max_object_bytes: int = Field(default=262_144, ge=1, le=1_048_576)
    allow_insecure_local: bool = False

    @model_validator(mode="after")
    def bounded_scope(self):
        target = urlsplit(self.endpoint)
        if (
            target.scheme not in {"https", "http"}
            or not target.hostname
            or target.username is not None
            or target.password is not None
            or target.path not in {"", "/"}
            or target.query
            or target.fragment
        ):
            raise ValueError("S3 endpoint must be an HTTP(S) origin without credentials")
        _ = target.port  # Reject invalid ports before client construction.
        if target.scheme != "https" and not (
            self.allow_insecure_local and target.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("S3 input requires TLS except for explicit loopback fixtures")
        if not self.prefix.endswith("/") or self.prefix.startswith("/"):
            raise ValueError("S3 input requires an explicit relative directory prefix")
        if any(part in {"", ".", ".."} for part in self.prefix[:-1].split("/")):
            raise ValueError("S3 prefix must use clean path segments")
        if (
            not self.allowed_suffixes
            or len(set(self.allowed_suffixes)) != len(self.allowed_suffixes)
            or any(
                suffix not in {".json", ".jsonl", ".csv", ".txt"}
                for suffix in self.allowed_suffixes
            )
        ):
            raise ValueError("S3 file types must be a nonempty subset of json, jsonl, csv and txt")
        return self

    @property
    def revision(self) -> str:
        encoded = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @property
    def resource_name(self) -> str:
        # A scope change requires rediscovery and a new explicit activation.
        return f"s3.objects_{self.revision}"

    @property
    def endpoint_target_sha256(self) -> str:
        target = urlsplit(self.endpoint)
        port = target.port or (443 if target.scheme == "https" else 80)
        return hashlib.sha256(f"{target.hostname.lower()}:{port}".encode()).hexdigest()
