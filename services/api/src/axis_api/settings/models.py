"""Models configuration field definitions (no environment loading)."""

from pydantic import BaseModel, Field


class ModelsSettings(BaseModel):
    external_model_egress_enabled: bool = Field(
        default=False,
        alias="AXIS_EXTERNAL_MODEL_EGRESS_ENABLED",
    )
    model_routing_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_MODEL_ROUTING_EXECUTION_ENABLED",
    )
    model_invocation_timeout_seconds: float = Field(
        default=30.0,
        ge=0.1,
        le=600.0,
        alias="AXIS_MODEL_INVOCATION_TIMEOUT_SECONDS",
    )
    model_invocation_allowed_base_urls: list[str] = Field(
        default_factory=list,
        alias="AXIS_MODEL_INVOCATION_ALLOWED_BASE_URLS",
    )
    model_invocation_prompt_excerpt_chars: int = Field(
        default=0,
        ge=0,
        le=2000,
        alias="AXIS_MODEL_INVOCATION_PROMPT_EXCERPT_CHARS",
    )
    agent_run_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_AGENT_RUN_EXECUTION_ENABLED",
    )
    agent_run_max_model_calls: int = Field(
        default=3,
        ge=1,
        le=10,
        alias="AXIS_AGENT_RUN_MAX_MODEL_CALLS",
    )
