"""Model aggregate records, ports and SQL implementation.

The caller owns the supplied session and its transaction. Writes flush only;
authorization, audit decisions and provider calls remain in the domain services.
"""

from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from axis_api.models import ModelEndpoint, ModelInvocation, utc_now
from axis_api.repositories.errors import PersistenceRecordNotFound


class ModelEndpointCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    endpoint_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider_type: str = Field(min_length=1)
    hosting_boundary: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    default_model: str = Field(min_length=1)
    task_types: list[str] = Field(min_length=1)
    status: str = Field(default="enabled", min_length=1)
    credential_handle_id: str | None = None
    egress_policy_id: str | None = None
    cost_input_per_1k: Decimal = Field(default=Decimal("0"), ge=0)
    cost_output_per_1k: Decimal = Field(default=Decimal("0"), ge=0)
    created_by: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="model.endpoint.registered", min_length=1)
    notes: list[str] = Field(default_factory=list)

class ModelEndpointStatusUpdate(BaseModel):
    tenant_id: str = Field(min_length=1)
    endpoint_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="model.endpoint.status_changed", min_length=1)
    note: str = Field(min_length=1)

class ModelInvocationCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(default="requested", min_length=1)
    task_type: str = Field(min_length=1)
    endpoint_id: str | None = None
    provider_type: str | None = None
    hosting_boundary: str | None = None
    model_id: str | None = None
    requested_by: str = Field(min_length=1)
    route_decision: dict = Field(default_factory=dict)
    permission_decision: dict = Field(default_factory=dict)
    platform_policy_decision: dict | None = None
    egress_decision: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=64, max_length=64)
    prompt_excerpt: str | None = None
    notes: list[str] = Field(default_factory=list)

class ModelInvocationResultRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    invocation_id: UUID
    status: str = Field(min_length=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost_eur: Decimal = Field(default=Decimal("0"), ge=0)
    response_sha256: str | None = None
    response_excerpt: str | None = None
    provider_request_ref: str | None = None
    error_code: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    notes: list[str] | None = None


class ModelReadPort(Protocol):

    def get_model_endpoint(
        self,
        tenant_id: str,
        endpoint_id: str,
    ) -> ModelEndpoint | None: ...

    def list_model_endpoints(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ModelEndpoint]: ...

    def get_model_invocation(
        self,
        tenant_id: str,
        invocation_id: UUID,
    ) -> ModelInvocation | None: ...

    def get_model_invocation_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ModelInvocation | None: ...

    def list_model_invocations(
        self,
        tenant_id: str,
        cursor_created_at: datetime | None = None,
        cursor_row_id: UUID | None = None,
        limit: int = 100,
    ) -> list[ModelInvocation]: ...


class ModelWritePort(Protocol):

    def create_model_endpoint(self, record: ModelEndpointCreate) -> ModelEndpoint: ...

    def update_model_endpoint_status(
        self,
        record: ModelEndpointStatusUpdate,
    ) -> ModelEndpoint: ...

    def create_model_invocation(self, record: ModelInvocationCreate) -> ModelInvocation: ...

    def record_model_invocation_result(
        self,
        result: ModelInvocationResultRecord,
    ) -> ModelInvocation: ...


class ModelPersistencePort(ModelReadPort, ModelWritePort, Protocol):
    """The existing facade consumes the combined model read/write surface."""


class ModelRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_model_endpoint(self, record: ModelEndpointCreate) -> ModelEndpoint:
        endpoint = ModelEndpoint(
            tenant_id=record.tenant_id,
            endpoint_id=record.endpoint_id,
            display_name=record.display_name,
            provider_type=record.provider_type,
            hosting_boundary=record.hosting_boundary,
            base_url=record.base_url,
            default_model=record.default_model,
            task_types=record.task_types,
            status=record.status,
            credential_handle_id=record.credential_handle_id,
            egress_policy_id=record.egress_policy_id,
            cost_input_per_1k=record.cost_input_per_1k,
            cost_output_per_1k=record.cost_output_per_1k,
            created_by=record.created_by,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(endpoint)
        self.session.flush()
        return endpoint

    def get_model_endpoint(
        self,
        tenant_id: str,
        endpoint_id: str,
    ) -> ModelEndpoint | None:
        statement: Select[tuple[ModelEndpoint]] = select(ModelEndpoint).where(
            ModelEndpoint.tenant_id == tenant_id,
            ModelEndpoint.endpoint_id == endpoint_id,
        )
        return self.session.scalar(statement)

    def list_model_endpoints(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ModelEndpoint]:
        statement: Select[tuple[ModelEndpoint]] = select(ModelEndpoint).where(
            ModelEndpoint.tenant_id == tenant_id
        )
        if status is not None:
            statement = statement.where(ModelEndpoint.status == status)
        statement = statement.order_by(ModelEndpoint.endpoint_id.asc()).limit(limit)
        return list(self.session.scalars(statement))

    def update_model_endpoint_status(
        self,
        record: ModelEndpointStatusUpdate,
    ) -> ModelEndpoint:
        endpoint = self.get_model_endpoint(record.tenant_id, record.endpoint_id)
        if endpoint is None:
            raise PersistenceRecordNotFound("Model endpoint not found")

        endpoint.status = record.status
        endpoint.audit_event_id = record.audit_event_id
        endpoint.audit_event_type = record.audit_event_type
        endpoint.notes = [*endpoint.notes, record.note]
        endpoint.updated_at = utc_now()
        self.session.flush()
        return endpoint

    def create_model_invocation(self, record: ModelInvocationCreate) -> ModelInvocation:
        invocation = ModelInvocation(
            tenant_id=record.tenant_id,
            idempotency_key=record.idempotency_key,
            status=record.status,
            task_type=record.task_type,
            endpoint_id=record.endpoint_id,
            provider_type=record.provider_type,
            hosting_boundary=record.hosting_boundary,
            model_id=record.model_id,
            requested_by=record.requested_by,
            route_decision=record.route_decision,
            permission_decision=record.permission_decision,
            platform_policy_decision=record.platform_policy_decision,
            egress_decision=record.egress_decision,
            prompt_sha256=record.prompt_sha256,
            prompt_excerpt=record.prompt_excerpt,
            notes=record.notes,
        )
        self.session.add(invocation)
        self.session.flush()
        return invocation

    def get_model_invocation(
        self,
        tenant_id: str,
        invocation_id: UUID,
    ) -> ModelInvocation | None:
        statement: Select[tuple[ModelInvocation]] = select(ModelInvocation).where(
            ModelInvocation.tenant_id == tenant_id,
            ModelInvocation.id == invocation_id,
        )
        return self.session.scalar(statement)

    def get_model_invocation_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ModelInvocation | None:
        statement: Select[tuple[ModelInvocation]] = select(ModelInvocation).where(
            ModelInvocation.tenant_id == tenant_id,
            ModelInvocation.idempotency_key == idempotency_key,
        )
        return self.session.scalar(statement)

    def record_model_invocation_result(
        self,
        result: ModelInvocationResultRecord,
    ) -> ModelInvocation:
        invocation = self.get_model_invocation(result.tenant_id, result.invocation_id)
        if invocation is None:
            raise PersistenceRecordNotFound("Model invocation not found")
        invocation.status = result.status
        invocation.input_tokens = result.input_tokens
        invocation.output_tokens = result.output_tokens
        invocation.latency_ms = result.latency_ms
        invocation.estimated_cost_eur = result.estimated_cost_eur
        invocation.response_sha256 = result.response_sha256
        invocation.response_excerpt = result.response_excerpt
        invocation.provider_request_ref = result.provider_request_ref
        invocation.error_code = result.error_code
        invocation.audit_event_id = result.audit_event_id
        invocation.audit_event_type = result.audit_event_type
        if result.notes is not None:
            invocation.notes = result.notes
        invocation.updated_at = utc_now()
        self.session.flush()
        return invocation

    def list_model_invocations(
        self,
        tenant_id: str,
        cursor_created_at: datetime | None = None,
        cursor_row_id: UUID | None = None,
        limit: int = 100,
    ) -> list[ModelInvocation]:
        statement: Select[tuple[ModelInvocation]] = select(ModelInvocation).where(
            ModelInvocation.tenant_id == tenant_id
        )
        if cursor_created_at is not None and cursor_row_id is not None:
            # Newest-first keyset continuation: resume strictly after the
            # cursor row in (created_at desc, id desc) order.
            statement = statement.where(
                or_(
                    ModelInvocation.created_at < cursor_created_at,
                    and_(
                        ModelInvocation.created_at == cursor_created_at,
                        ModelInvocation.id < cursor_row_id,
                    ),
                )
            )
        statement = statement.order_by(
            ModelInvocation.created_at.desc(),
            ModelInvocation.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))
