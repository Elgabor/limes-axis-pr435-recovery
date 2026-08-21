from enum import StrEnum
from typing import Any


class AxisErrorCode(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"
    CONFLICT = "CONFLICT"
    TENANT_SCOPE_REQUIRED = "TENANT_SCOPE_REQUIRED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    ACTION_REQUIRES_APPROVAL = "ACTION_REQUIRES_APPROVAL"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    CONNECTOR_UNAVAILABLE = "CONNECTOR_UNAVAILABLE"
    MODEL_PROVIDER_BLOCKED = "MODEL_PROVIDER_BLOCKED"
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    REPLAY_NOT_AVAILABLE = "REPLAY_NOT_AVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    CONTROL_PLANE_UNAVAILABLE = "CONTROL_PLANE_UNAVAILABLE"


def error_response(code: AxisErrorCode, message: str, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code.value,
            "message": message,
            "request_id": request_id,
        }
    }
