import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Any, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from axis_api.config import Settings

S3_COMPATIBLE_ADAPTER = "s3_compatible"
LOCAL_FILESYSTEM_ADAPTER = "local_filesystem"
SUPPORTED_RETENTION_MODES = {"GOVERNANCE", "COMPLIANCE"}
COMPLIANCE_RETENTION_MODE = "COMPLIANCE"
GOVERNANCE_RETENTION_MODE = "GOVERNANCE"
VERIFIED_OBJECT_LOCK_REQUIREMENT = "verified object-lock bucket"


class ObjectStoreConfigurationError(ValueError):
    pass


class ObjectStoreWormEnforcementError(RuntimeError):
    """Raised when a COMPLIANCE object store cannot actually enforce WORM.

    This is a fail-closed signal: the backing bucket does not have S3
    object-lock enabled at creation time (or the probe failed), so any
    COMPLIANCE retention passed on ``put_object`` would silently no-op.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StoredObjectMetadata(BaseModel):
    storage_adapter: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)


def _verify_stream(stream, checksum: str, size: int) -> bool:
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = stream.read(min(65536, remaining))
        if not chunk:
            return False
        remaining -= len(chunk)
        digest.update(chunk)
    return not stream.read(1) and digest.hexdigest() == checksum


class ObjectStore(Protocol):
    adapter_name: str

    def put_json(self, key: str, payload: dict) -> StoredObjectMetadata:
        ...

    def verify_json(self, key: str, checksum: str, size: int) -> bool:
        ...


class S3PutObjectClient(Protocol):
    def get_object(self, bucket_name: str, object_name: str) -> Any: ...

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BytesIO,
        length: int,
        content_type: str,
        **kwargs: Any,
    ) -> object:
        ...

    def get_object_lock_config(self, bucket_name: str) -> object:
        ...

    def enable_object_legal_hold(
        self,
        bucket_name: str,
        object_name: str,
        version_id: str | None = ...,
    ) -> object:
        ...

    def disable_object_legal_hold(
        self,
        bucket_name: str,
        object_name: str,
        version_id: str | None = ...,
    ) -> object:
        ...

    def is_object_legal_hold_enabled(
        self,
        bucket_name: str,
        object_name: str,
        version_id: str | None = ...,
    ) -> bool:
        ...


class ObjectLockCapability(BaseModel):
    """The verified WORM capability of a backing object store.

    ``checked`` records whether a live probe of the bucket object-lock
    configuration was actually performed. ``bucket_object_lock_enabled`` is the
    result of that probe. ``compliance_enforceable`` is the fail-closed answer
    to "can this store genuinely enforce COMPLIANCE-mode WORM retention?".
    """

    adapter: str = Field(min_length=1)
    checked: bool
    bucket_object_lock_enabled: bool
    default_retention_mode: str | None = None
    compliance_enforceable: bool
    reason: str = Field(min_length=1)


class ObjectStoreReadiness(BaseModel):
    adapter: str = Field(min_length=1)
    production_ready: bool
    bucket_configured: bool
    endpoint_configured: bool
    credentials_configured: bool
    secure_transport: bool
    object_lock_enabled: bool
    worm_retention_enabled: bool
    retention_mode: str = Field(min_length=1)
    retention_days: int = Field(ge=0)
    legal_hold_enabled: bool
    object_lock_bucket_verified: bool = False
    compliance_enforceable: bool = False
    object_lock_probe_reason: str = Field(default="not_probed", min_length=1)
    missing_requirements: list[str] = Field(default_factory=list)


class LocalObjectStore:
    adapter_name = LOCAL_FILESYSTEM_ADAPTER
    uri_scheme = "axis-local-object-store"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def put_json(self, key: str, payload: dict) -> StoredObjectMetadata:
        safe_key = self._safe_key(key)
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        destination = self.root / safe_key
        missing_directories = []
        directory = destination.parent
        while not directory.exists():
            missing_directories.append(directory)
            directory = directory.parent
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            dir=destination.parent, prefix=".axis-write-", delete=False,
        ) as staged:
            staged_path = Path(staged.name)
            try:
                staged.write(encoded)
                staged.flush()
                os.fsync(staged.fileno())
                os.replace(staged_path, destination)
                for directory in [destination.parent, *(p.parent for p in missing_directories)]:
                    directory_fd = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            finally:
                staged_path.unlink(missing_ok=True)
        checksum = hashlib.sha256(encoded).hexdigest()
        return StoredObjectMetadata(
            storage_adapter=self.adapter_name,
            storage_key=safe_key,
            storage_uri=f"{self.uri_scheme}://{safe_key}",
            content_type="application/json",
            checksum_sha256=checksum,
            size_bytes=len(encoded),
        )

    def verify_json(self, key: str, checksum: str, size: int) -> bool:
        with (self.root / self._safe_key(key)).open("rb") as stream:
            return _verify_stream(stream, checksum, size)

    def object_lock_capability(self) -> ObjectLockCapability:
        return ObjectLockCapability(
            adapter=self.adapter_name,
            checked=True,
            bucket_object_lock_enabled=False,
            default_retention_mode=None,
            compliance_enforceable=False,
            reason=(
                "local_filesystem_store_cannot_provide_worm: the local object "
                "store has no S3 object-lock and cannot enforce COMPLIANCE "
                "retention or legal holds."
            ),
        )

    @staticmethod
    def _safe_key(key: str) -> str:
        path = PurePosixPath(key)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("Object storage keys must be relative clean paths.")
        return str(path)


class S3CompatibleObjectStore:
    adapter_name = S3_COMPATIBLE_ADAPTER

    def __init__(
        self,
        *,
        client: S3PutObjectClient,
        bucket_name: str,
        retention_mode: str,
        retention_days: int,
        legal_hold_enabled: bool,
        clock: Callable[[], datetime] | None = None,
        retention_factory: Callable[[str, datetime], object] | None = None,
    ) -> None:
        normalized_retention_mode = retention_mode.strip().upper()
        if normalized_retention_mode not in SUPPORTED_RETENTION_MODES:
            raise ObjectStoreConfigurationError(
                "S3-compatible object storage retention mode must be GOVERNANCE or COMPLIANCE."
            )
        if retention_days <= 0:
            raise ObjectStoreConfigurationError(
                "S3-compatible object storage retention days must be greater than zero."
            )

        self.client = client
        self.bucket_name = bucket_name
        self.retention_mode = normalized_retention_mode
        self.retention_days = retention_days
        self.legal_hold_enabled = legal_hold_enabled
        self.clock = clock or (lambda: datetime.now(UTC))
        self.retention_factory = retention_factory or _minio_retention

    @property
    def is_compliance_mode(self) -> bool:
        return self.retention_mode == COMPLIANCE_RETENTION_MODE

    def retention_until(self, *, now: datetime | None = None) -> datetime:
        """Explicit RetainUntilDate derived from the configured retention days."""

        reference = now or self.clock()
        return reference + timedelta(days=self.retention_days)

    def object_lock_capability(self) -> ObjectLockCapability:
        """Probe the backing bucket's S3 object-lock configuration.

        S3/MinIO only returns an object-lock configuration when the bucket was
        created with object-lock enabled. A missing configuration (or any
        access failure) is treated as fail-closed: the store cannot enforce
        COMPLIANCE-mode WORM.
        """

        try:
            config = self.client.get_object_lock_config(self.bucket_name)
        except Exception as exc:  # noqa: BLE001 - fail-closed on any probe failure
            return ObjectLockCapability(
                adapter=self.adapter_name,
                checked=True,
                bucket_object_lock_enabled=False,
                default_retention_mode=None,
                compliance_enforceable=False,
                reason=(
                    "bucket_object_lock_probe_failed: could not read the "
                    f"object-lock configuration for bucket {self.bucket_name!r} "
                    f"({type(exc).__name__}); the bucket was likely created "
                    "without object-lock enabled."
                ),
            )

        default_mode = _object_lock_config_mode(config)
        return ObjectLockCapability(
            adapter=self.adapter_name,
            checked=True,
            bucket_object_lock_enabled=True,
            default_retention_mode=default_mode,
            compliance_enforceable=True,
            reason=(
                "bucket_object_lock_enabled: object-lock is enabled on bucket "
                f"{self.bucket_name!r}"
                + (f" with default retention mode {default_mode}." if default_mode else ".")
            ),
        )

    def _ensure_compliance_enforceable(self) -> None:
        capability = self.object_lock_capability()
        if not capability.compliance_enforceable:
            raise ObjectStoreWormEnforcementError(capability.reason)

    def put_json(self, key: str, payload: dict) -> StoredObjectMetadata:
        safe_key = LocalObjectStore._safe_key(key)
        if self.is_compliance_mode:
            # Fail closed before writing: a COMPLIANCE retention on a bucket
            # without object-lock silently no-ops, defeating WORM.
            self._ensure_compliance_enforceable()
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        retain_until = self.retention_until()
        retention = self.retention_factory(self.retention_mode, retain_until)
        self.client.put_object(
            self.bucket_name,
            safe_key,
            BytesIO(encoded),
            len(encoded),
            "application/json",
            retention=retention,
            legal_hold=self.legal_hold_enabled,
        )
        checksum = hashlib.sha256(encoded).hexdigest()
        return StoredObjectMetadata(
            storage_adapter=self.adapter_name,
            storage_key=safe_key,
            storage_uri=f"s3://{self.bucket_name}/{safe_key}",
            content_type="application/json",
            checksum_sha256=checksum,
            size_bytes=len(encoded),
        )

    def verify_json(self, key: str, checksum: str, size: int) -> bool:
        stream = self.client.get_object(self.bucket_name, LocalObjectStore._safe_key(key))
        try:
            return _verify_stream(stream, checksum, size)
        finally:
            stream.close()
            stream.release_conn()

    def apply_legal_hold(self, key: str) -> None:
        """Place an S3 object-level legal hold on a stored export object."""

        safe_key = LocalObjectStore._safe_key(key)
        self.client.enable_object_legal_hold(self.bucket_name, safe_key)

    def release_legal_hold(self, key: str) -> None:
        """Release an S3 object-level legal hold on a stored export object."""

        safe_key = LocalObjectStore._safe_key(key)
        self.client.disable_object_legal_hold(self.bucket_name, safe_key)

    def legal_hold_status(self, key: str) -> bool:
        safe_key = LocalObjectStore._safe_key(key)
        return bool(self.client.is_object_legal_hold_enabled(self.bucket_name, safe_key))


def _object_lock_config_mode(config: object) -> str | None:
    mode = getattr(config, "mode", None)
    if mode is None:
        return None
    normalized = str(mode).strip().upper()
    return normalized or None


def _minio_retention(mode: str, retain_until: datetime) -> object:
    from minio.commonconfig import COMPLIANCE, GOVERNANCE
    from minio.retention import Retention

    minio_mode = GOVERNANCE if mode == "GOVERNANCE" else COMPLIANCE
    return Retention(minio_mode, retain_until)


def _normalize_s3_endpoint(raw_endpoint: str, secure_transport: bool) -> tuple[str, bool]:
    endpoint = raw_endpoint.strip()
    if not endpoint:
        raise ObjectStoreConfigurationError("S3-compatible object storage endpoint is required.")

    parsed = urlparse(endpoint)
    if parsed.scheme in {"http", "https"}:
        if not parsed.netloc or parsed.path not in {"", "/"}:
            raise ObjectStoreConfigurationError(
                "S3-compatible object storage endpoint must not include a path."
            )
        return parsed.netloc, parsed.scheme == "https"
    if "://" in endpoint:
        raise ObjectStoreConfigurationError(
            "S3-compatible object storage endpoint must use http or https when a scheme is set."
        )
    return endpoint, secure_transport


def _s3_client_factory(**kwargs: Any) -> S3PutObjectClient:
    from minio import Minio

    return Minio(**kwargs)


def build_object_store_readiness(
    settings: Settings,
    *,
    object_lock_capability: ObjectLockCapability | None = None,
) -> ObjectStoreReadiness:
    """Build the object-store readiness report.

    By default this is a config-level report (no network calls). When an
    ``object_lock_capability`` is supplied (typically produced by
    :func:`probe_object_lock_capability` at bootstrap), the live bucket
    object-lock verification is folded in. For COMPLIANCE retention mode the
    bucket object-lock verification is a *required* gate: without it the report
    is not production-ready and the compliance export path fails closed.
    """

    adapter = settings.connector_export_object_store_adapter.strip().casefold()
    retention_mode = settings.connector_export_s3_retention_mode.strip().upper()
    bucket_configured = bool(settings.connector_export_s3_bucket)
    endpoint_configured = bool(settings.connector_export_s3_endpoint)
    effective_secure_transport = settings.connector_export_s3_secure_transport
    if settings.connector_export_s3_endpoint:
        try:
            _, effective_secure_transport = _normalize_s3_endpoint(
                settings.connector_export_s3_endpoint,
                settings.connector_export_s3_secure_transport,
            )
        except ObjectStoreConfigurationError:
            endpoint_configured = False
            effective_secure_transport = False
    access_key_configured = bool(settings.connector_export_s3_access_key)
    secret_key_configured = bool(settings.connector_export_s3_secret_key)
    credentials_configured = access_key_configured and secret_key_configured
    retention_mode_supported = retention_mode in SUPPORTED_RETENTION_MODES
    retention_days_configured = settings.connector_export_s3_retention_days > 0
    object_lock_enabled = settings.connector_export_s3_object_lock_enabled
    worm_retention_enabled = (
        object_lock_enabled and retention_mode_supported and retention_days_configured
    )
    compliance_configured = retention_mode == COMPLIANCE_RETENTION_MODE

    if adapter == LOCAL_FILESYSTEM_ADAPTER and object_lock_capability is None:
        object_lock_capability = LocalObjectStore(
            settings.connector_export_object_store_root
        ).object_lock_capability()

    object_lock_bucket_verified = bool(
        object_lock_capability and object_lock_capability.bucket_object_lock_enabled
    )
    compliance_enforceable = bool(
        object_lock_capability and object_lock_capability.compliance_enforceable
    )
    object_lock_probe_reason = (
        object_lock_capability.reason if object_lock_capability else "not_probed"
    )

    missing_requirements: list[str] = []
    if adapter != S3_COMPATIBLE_ADAPTER:
        missing_requirements.append("S3-compatible adapter")
    if not endpoint_configured:
        missing_requirements.append("endpoint")
    if not bucket_configured:
        missing_requirements.append("bucket")
    if not access_key_configured:
        missing_requirements.append("access key")
    if not secret_key_configured:
        missing_requirements.append("secret key")
    if not effective_secure_transport:
        missing_requirements.append("TLS transport")
    if not object_lock_enabled:
        missing_requirements.append("object lock")
    if not retention_mode_supported:
        missing_requirements.append("retention mode")
    if not retention_days_configured:
        missing_requirements.append("retention days")
    if compliance_configured and not compliance_enforceable:
        missing_requirements.append(VERIFIED_OBJECT_LOCK_REQUIREMENT)

    return ObjectStoreReadiness(
        adapter=adapter,
        production_ready=not missing_requirements,
        bucket_configured=bucket_configured,
        endpoint_configured=endpoint_configured,
        credentials_configured=credentials_configured,
        secure_transport=effective_secure_transport,
        object_lock_enabled=object_lock_enabled,
        worm_retention_enabled=worm_retention_enabled,
        retention_mode=retention_mode,
        retention_days=max(settings.connector_export_s3_retention_days, 0),
        legal_hold_enabled=settings.connector_export_s3_legal_hold_enabled,
        object_lock_bucket_verified=object_lock_bucket_verified,
        compliance_enforceable=compliance_enforceable,
        object_lock_probe_reason=object_lock_probe_reason,
        missing_requirements=missing_requirements,
    )


def probe_object_lock_capability(
    settings: Settings,
    *,
    s3_client_factory: Callable[..., S3PutObjectClient] = _s3_client_factory,
) -> ObjectLockCapability:
    """Live-probe the audit-export bucket's object-lock capability.

    Returns a fail-closed capability if the store cannot be constructed, is a
    local filesystem store, or the bucket lacks object-lock. Never raises for
    configuration or network problems: readiness callers fold the result in and
    the export gate treats a non-enforceable capability as a hard stop.
    """

    adapter = settings.connector_export_object_store_adapter.strip().casefold()
    if adapter == LOCAL_FILESYSTEM_ADAPTER:
        return LocalObjectStore(
            settings.connector_export_object_store_root
        ).object_lock_capability()
    try:
        store = build_connector_export_object_store(
            settings, s3_client_factory=s3_client_factory
        )
    except ObjectStoreConfigurationError as exc:
        return ObjectLockCapability(
            adapter=adapter or "unknown",
            checked=False,
            bucket_object_lock_enabled=False,
            default_retention_mode=None,
            compliance_enforceable=False,
            reason=f"object_store_misconfigured: {exc}",
        )
    if not isinstance(store, S3CompatibleObjectStore):  # pragma: no cover - defensive
        return store.object_lock_capability()  # type: ignore[attr-defined]
    return store.object_lock_capability()


def build_connector_export_object_store(
    settings: Settings,
    *,
    s3_client_factory: Callable[..., S3PutObjectClient] = _s3_client_factory,
) -> ObjectStore:
    adapter = settings.connector_export_object_store_adapter.strip().casefold()
    if adapter == LOCAL_FILESYSTEM_ADAPTER:
        return LocalObjectStore(settings.connector_export_object_store_root)
    if adapter != S3_COMPATIBLE_ADAPTER:
        raise ObjectStoreConfigurationError(
            f"Unsupported connector export object-store adapter: {adapter}"
        )

    # The verified-object-lock requirement needs a live bucket probe, which
    # cannot run before the client exists. Store construction only gates on the
    # config-level requirements; the live compliance gate is enforced by the
    # readiness report and the export path via probe_object_lock_capability.
    readiness = build_object_store_readiness(settings)
    construction_requirements = [
        requirement
        for requirement in readiness.missing_requirements
        if requirement != VERIFIED_OBJECT_LOCK_REQUIREMENT
    ]
    if construction_requirements:
        missing = ", ".join(construction_requirements)
        raise ObjectStoreConfigurationError(
            f"S3-compatible object storage is missing required configuration: {missing}."
        )
    endpoint, secure = _normalize_s3_endpoint(
        settings.connector_export_s3_endpoint or "",
        settings.connector_export_s3_secure_transport,
    )
    client = s3_client_factory(
        endpoint=endpoint,
        access_key=settings.connector_export_s3_access_key,
        secret_key=settings.connector_export_s3_secret_key,
        secure=secure,
        region=settings.connector_export_s3_region,
    )
    return S3CompatibleObjectStore(
        client=client,
        bucket_name=settings.connector_export_s3_bucket or "",
        retention_mode=settings.connector_export_s3_retention_mode,
        retention_days=settings.connector_export_s3_retention_days,
        legal_hold_enabled=settings.connector_export_s3_legal_hold_enabled,
    )
