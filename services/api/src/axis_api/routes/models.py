"""Model HTTP routes; composition supplies the existing shared trust-boundary functions.

Annotations are evaluated at router construction so FastAPI sees the exact
injected dependency callables, including application dependency overrides.
"""

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Annotated, Protocol, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from axis_api.config import Settings
from axis_api.demo import ManufacturingModelRouting
from axis_api.errors import AxisErrorCode
from axis_api.identity import OidcPrincipal
from axis_api.model_endpoints import (
    ModelEndpointConflict,
    ModelEndpointCreateRequest,
    ModelEndpointNotFound,
    ModelEndpointPermissionDenied,
    ModelEndpointRecord,
    ModelEndpointRegistry,
    ModelEndpointStatusUpdateRequest,
    ModelEndpointValidationError,
    build_model_endpoint_registry,
    record_model_endpoint,
    update_model_endpoint_status,
)
from axis_api.model_invocations import (
    ModelEgressBlocked,
    ModelInvocationCursorError,
    ModelInvocationIdempotencyConflict,
    ModelInvocationList,
    ModelInvocationNotFound,
    ModelInvocationPermissionDenied,
    ModelInvocationPreview,
    ModelInvocationPreviewRequest,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelInvocationValidationError,
    ModelRoutingTelemetryProjection,
    build_model_routing_telemetry,
    decode_model_invocation_cursor,
    encode_model_invocation_cursor,
    get_model_invocation_result,
    invoke_model,
    list_model_invocation_results,
    preview_model_invocation,
)
from axis_api.model_providers import ModelInvocationRuntime
from axis_api.model_routing_reference import (
    ModelRoutingReferenceRecordInvalid,
    get_persisted_manufacturing_model_routing,
)
from axis_api.persistence import AxisPersistenceRepository
from axis_api.platform_policies import PlatformPolicyEnforcementDenied
from axis_api.telemetry import (
    ATTR_ACTOR_ID,
    ATTR_MODEL_ID,
    ATTR_MODEL_INPUT_TOKENS,
    ATTR_MODEL_LATENCY_MS,
    ATTR_MODEL_OUTPUT_TOKENS,
    ATTR_MODEL_PROVIDER_ID,
    ATTR_OUTCOME,
    ATTR_TENANT_ID,
    TelemetryRuntime,
    set_span_attributes,
)

BoundBody = TypeVar("BoundBody", bound=BaseModel)


class BodyActorBinder(Protocol):
    def __call__(
        self, request_model: BoundBody, principal: OidcPrincipal | None, actor_field: str,
    ) -> BoundBody: ...


class PrincipalProvider(Protocol):
    def __call__(
        self, request: Request, authorization: str | None = None,
    ) -> OidcPrincipal | None: ...


class ModelReadAuthorizer(Protocol):
    def __call__(
        self, *, tenant_id: str, principal: OidcPrincipal | None, resource: str,
    ) -> None: ...


@dataclass(frozen=True)
class ModelRouteDependencies:
    repository: Callable[[Request], Generator[AxisPersistenceRepository]]
    principal: PrincipalProvider
    runtime: Callable[[Request], ModelInvocationRuntime]
    bind_actor: BodyActorBinder
    authorize_model_read: ModelReadAuthorizer
    authorize_tenant_read: Callable[[str, OidcPrincipal | None], None]
    policy_denial_detail: Callable[[PlatformPolicyEnforcementDenied, str], dict]


def build_model_routers(
    *, settings: Settings, telemetry: TelemetryRuntime, dependencies: ModelRouteDependencies,
) -> tuple[APIRouter, APIRouter]:
    platform_router = APIRouter()
    operations_router = APIRouter()

    @platform_router.post(
        "/platform/models/endpoints",
        response_model=ModelEndpointRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model endpoint admin permission denied"},
            409: {"description": "Model endpoint already exists"},
            422: {"description": "Model endpoint validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["platform"],
    )
    def platform_model_endpoint_create(
        endpoint_request: ModelEndpointCreateRequest,
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
    ) -> ModelEndpointRecord:
        try:
            bound_endpoint = dependencies.bind_actor(endpoint_request, principal, "created_by")
            return record_model_endpoint(repository, bound_endpoint)
        except ModelEndpointPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot administer model endpoints.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope"
                    if exc.decision.reason.startswith("missing_scope:")
                    else exc.decision.reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ModelEndpointConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": AxisErrorCode.CONFLICT.value,
                    "message": "The model endpoint already exists.",
                    "reason": "endpoint_already_exists",
                    "endpoint_id": exc.endpoint_id,
                },
            ) from exc
        except ModelEndpointValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @platform_router.post(
        "/platform/models/endpoints/{endpoint_id}/status",
        response_model=ModelEndpointRecord,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model endpoint admin permission denied"},
            404: {"description": "Model endpoint not found"},
            422: {"description": "Model endpoint status transition invalid"},
        },
        tags=["platform"],
    )
    def platform_model_endpoint_status_update(
        endpoint_id: str,
        status_request: ModelEndpointStatusUpdateRequest,
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
    ) -> ModelEndpointRecord:
        try:
            bound_status = dependencies.bind_actor(status_request, principal, "updated_by")
            return update_model_endpoint_status(repository, endpoint_id, bound_status)
        except ModelEndpointPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot administer model endpoints.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope"
                    if exc.decision.reason.startswith("missing_scope:")
                    else exc.decision.reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc
        except ModelEndpointNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The model endpoint was not found.",
                    "reason": "model_endpoint_not_found",
                    "endpoint_id": exc.endpoint_id,
                },
            ) from exc
        except ModelEndpointValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": exc.message,
                    "reason": exc.reason,
                },
            ) from exc

    @platform_router.get(
        "/platform/models/endpoints",
        response_model=ModelEndpointRegistry,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model endpoint read permission denied"},
        },
        tags=["platform"],
    )
    def platform_model_endpoint_registry(
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        status_filter: str | None = Query(default=None, alias="status", min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ModelEndpointRegistry:
        dependencies.authorize_model_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="model_endpoints",
        )
        return build_model_endpoint_registry(
            repository,
            tenant_id=tenant_id,
            status=status_filter,
            limit=limit,
        )

    @platform_router.post(
        "/platform/models/invocations",
        response_model=ModelInvocationResult,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model invocation permission denied or egress blocked"},
            409: {"description": "Model invocation idempotency conflict"},
            422: {"description": "Model invocation validation failed"},
        },
        status_code=status.HTTP_201_CREATED,
        tags=["platform"],
    )
    async def platform_model_invocation_create(
        invocation_request: ModelInvocationRequest,
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
        runtime: Annotated[ModelInvocationRuntime, Depends(dependencies.runtime)],
        response: Response,
    ) -> ModelInvocationResult:
        with telemetry.tracer.start_as_current_span("axis.model_invocation.invoke") as span:
            set_span_attributes(
                span,
                {
                    ATTR_TENANT_ID: principal.tenant_id if principal else None,
                    ATTR_ACTOR_ID: principal.actor_id if principal else None,
                },
            )
            try:
                bound_invocation = dependencies.bind_actor(
                    invocation_request, principal, "actor_id"
                )
                result = await invoke_model(
                    repository,
                    bound_invocation,
                    runtime,
                    external_model_egress_enabled=(settings.external_model_egress_enabled),
                    prompt_excerpt_chars=(settings.model_invocation_prompt_excerpt_chars),
                    usage_metering_enabled=settings.usage_metering_enabled,
                    usage_window_seconds=(
                        settings.usage_metering_aggregation_window_seconds
                    ),
                    # This handler owns the request transaction, so the
                    # prepared invocation is committed before the provider
                    # call instead of holding a connection for its duration.
                    commit_before_provider_call=True,
                )
            except ModelInvocationPermissionDenied as exc:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": AxisErrorCode.PERMISSION_DENIED.value,
                        "message": "The actor cannot invoke models.",
                        "required_permission": exc.required_permission,
                        "reason": "missing_required_scope"
                        if exc.decision.reason.startswith("missing_scope:")
                        else exc.decision.reason,
                        "permission_reason": exc.decision.reason,
                    },
                ) from exc
            except PlatformPolicyEnforcementDenied as exc:
                repository.session.commit()
                raise HTTPException(
                    status_code=403,
                    detail=dependencies.policy_denial_detail(
                        exc,
                        "A platform policy denies this model invocation.",
                    ),
                ) from exc
            except ModelEgressBlocked as exc:
                repository.session.commit()
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": AxisErrorCode.MODEL_PROVIDER_BLOCKED.value,
                        "message": exc.message,
                        "reason": exc.egress_decision,
                        "endpoint_id": exc.route_decision.endpoint_id,
                        "hosting_boundary": exc.route_decision.hosting_boundary,
                        "audit_event_id": (
                            str(exc.audit_event_id) if exc.audit_event_id is not None else None
                        ),
                        "audit_event_type": exc.audit_event_type,
                    },
                ) from exc
            except ModelInvocationIdempotencyConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": AxisErrorCode.CONFLICT.value,
                        "message": ("The idempotency key already exists with a different payload."),
                        "reason": "idempotency_key_conflict",
                        "invocation_id": str(exc.invocation_id),
                    },
                ) from exc
            except ModelInvocationValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": AxisErrorCode.VALIDATION_FAILED.value,
                        "message": exc.message,
                        "reason": exc.reason,
                    },
                ) from exc

            set_span_attributes(
                span,
                {
                    ATTR_OUTCOME: result.status,
                    ATTR_MODEL_PROVIDER_ID: result.endpoint_id,
                    ATTR_MODEL_ID: result.model_id,
                    ATTR_MODEL_LATENCY_MS: result.latency_ms,
                    ATTR_MODEL_INPUT_TOKENS: result.input_tokens,
                    ATTR_MODEL_OUTPUT_TOKENS: result.output_tokens,
                },
            )
            if result.idempotent_replay or result.status == "model_invocation_deferred":
                response.status_code = status.HTTP_200_OK
            return result

    @platform_router.post(
        "/platform/models/invocations/preview",
        response_model=ModelInvocationPreview,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model invocation permission denied"},
        },
        tags=["platform"],
    )
    def platform_model_invocation_preview(
        preview_request: ModelInvocationPreviewRequest,
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
    ) -> ModelInvocationPreview:
        try:
            bound_preview = dependencies.bind_actor(preview_request, principal, "actor_id")
            return preview_model_invocation(
                repository,
                bound_preview,
                external_model_egress_enabled=(settings.external_model_egress_enabled),
            )
        except ModelInvocationPermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": AxisErrorCode.PERMISSION_DENIED.value,
                    "message": "The actor cannot preview model invocations.",
                    "required_permission": exc.required_permission,
                    "reason": "missing_required_scope"
                    if exc.decision.reason.startswith("missing_scope:")
                    else exc.decision.reason,
                    "permission_reason": exc.decision.reason,
                },
            ) from exc

    @platform_router.get(
        "/platform/models/invocations",
        response_model=ModelInvocationList,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model invocation read permission denied"},
            422: {"description": "Model invocation listing cursor is invalid"},
        },
        tags=["platform"],
    )
    def platform_model_invocation_list(
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        page_size: int = Query(default=20, ge=1, le=100),
        cursor: str | None = Query(default=None, min_length=1, max_length=600),
    ) -> ModelInvocationList:
        dependencies.authorize_model_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="model_invocations",
        )
        try:
            cursor_created_at, cursor_row_id = decode_model_invocation_cursor(cursor)
        except ModelInvocationCursorError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "The model invocation listing cursor is invalid.",
                    "reason": exc.reason,
                },
            ) from exc
        results = list_model_invocation_results(
            repository,
            tenant_id,
            cursor_created_at=cursor_created_at,
            cursor_row_id=cursor_row_id,
            limit=page_size + 1,
        )
        has_more = len(results) > page_size
        page_results = results[:page_size]
        next_cursor = (
            encode_model_invocation_cursor(page_results[-1]) if has_more and page_results else None
        )
        return ModelInvocationList(
            tenant_id=tenant_id,
            invocations=page_results,
            has_more=has_more,
            next_cursor=next_cursor,
            invocation_notes=[
                "Invocations are listed newest-first with keyset continuation.",
                "Prompt and response bodies are never persisted; records carry "
                "hashes, token counts and decisions.",
            ],
        )

    @platform_router.get(
        "/platform/models/invocations/{invocation_id}",
        response_model=ModelInvocationResult,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model invocation read permission denied"},
            404: {"description": "Model invocation not found"},
        },
        tags=["platform"],
    )
    def platform_model_invocation_detail(
        invocation_id: str,
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ModelInvocationResult:
        dependencies.authorize_model_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="model_invocations",
        )
        try:
            return get_model_invocation_result(repository, tenant_id, invocation_id)
        except ModelInvocationNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": AxisErrorCode.NOT_FOUND.value,
                    "message": "The model invocation was not found.",
                    "reason": "model_invocation_not_found",
                },
            ) from exc

    @platform_router.get(
        "/platform/models/routing/telemetry",
        response_model=ModelRoutingTelemetryProjection,
        responses={
            401: {"description": "OIDC authentication required"},
            403: {"description": "Model routing telemetry read permission denied"},
        },
        tags=["platform"],
    )
    def platform_model_routing_telemetry(
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> ModelRoutingTelemetryProjection:
        dependencies.authorize_model_read(
            tenant_id=tenant_id,
            principal=principal,
            resource="model_routing_telemetry",
        )
        return build_model_routing_telemetry(
            repository,
            tenant_id,
            limit=limit,
        )

    @operations_router.get(
        "/model-routing",
        response_model=ManufacturingModelRouting,
        responses={
            404: {"description": "Tenant not found"},
            422: {"description": "Model routing reference payload invalid"},
        },
        tags=["demo"],
    )
    def manufacturing_model_routing(
        repository: Annotated[AxisPersistenceRepository, Depends(dependencies.repository)],
        principal: Annotated[OidcPrincipal | None, Depends(dependencies.principal)],
        tenant_id: str = Query(default="tenant_demo_manufacturing", min_length=1),
    ) -> ManufacturingModelRouting:
        dependencies.authorize_tenant_read(tenant_id, principal)
        try:
            return get_persisted_manufacturing_model_routing(
                repository,
                tenant_id=tenant_id,
            )
        except ModelRoutingReferenceRecordInvalid as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": AxisErrorCode.VALIDATION_FAILED.value,
                    "message": "Manufacturing model routing reference payload is invalid.",
                    "tenant_id": tenant_id,
                    "surface": "model-routing",
                },
            ) from exc


    return platform_router, operations_router
