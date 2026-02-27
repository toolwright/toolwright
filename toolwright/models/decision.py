"""Decision models for runtime governance enforcement."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DecisionType(StrEnum):
    """Decision outcomes for a tool invocation."""

    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


class ReasonCode(StrEnum):
    """Stable reason-code vocabulary for decisioning."""

    ALLOWED_POLICY = "allowed_policy"
    ALLOWED_CONFIRMATION_GRANTED = "allowed_confirmation_granted"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DENIED_UNKNOWN_ACTION = "denied_unknown_action"
    DENIED_POLICY = "denied_policy"
    DENIED_NOT_APPROVED = "denied_not_approved"
    DENIED_APPROVAL_SIGNATURE_REQUIRED = "denied_approval_signature_required"
    DENIED_APPROVAL_SIGNATURE_INVALID = "denied_approval_signature_invalid"
    DENIED_TOOLSET_NOT_ALLOWED = "denied_toolset_not_allowed"
    DENIED_TOOLSET_NOT_APPROVED = "denied_toolset_not_approved"
    DENIED_INTEGRITY_MISMATCH = "denied_integrity_mismatch"
    DENIED_CONFIRMATION_INVALID = "denied_confirmation_invalid"
    DENIED_CONFIRMATION_EXPIRED = "denied_confirmation_expired"
    DENIED_CONFIRMATION_REPLAY = "denied_confirmation_replay"
    DENIED_PARAM_VALIDATION = "denied_param_validation"
    DENIED_METHOD_NOT_ALLOWED = "denied_method_not_allowed"
    DENIED_RESPONSE_TOO_LARGE = "denied_response_too_large"
    DENIED_TIMEOUT = "denied_timeout"
    DENIED_RATE_LIMITED = "denied_rate_limited"
    DENIED_HOST_RESOLUTION_FAILED = "denied_host_resolution_failed"
    DENIED_SCHEME_NOT_ALLOWED = "denied_scheme_not_allowed"
    DENIED_REDIRECT_NOT_ALLOWLISTED = "denied_redirect_not_allowlisted"
    DENIED_CONTENT_TYPE_NOT_ALLOWED = "denied_content_type_not_allowed"
    ERROR_INTERNAL = "error_internal"


class DecisionRequest(BaseModel):
    """Decision request payload."""

    tool_id: str
    action_name: str | None = None
    method: str
    path: str
    host: str
    params: dict[str, Any] = Field(default_factory=dict)
    toolset_name: str | None = None
    confirmation_token_id: str | None = None
    source: str = "enforce"
    mode: str = "evaluate"


class NetworkSafetyConfig(BaseModel):
    """Runtime network safety controls."""

    allow_private_cidrs: list[str] = Field(default_factory=list)
    allow_redirects: bool = False
    max_redirects: int = 3
    allowed_content_types: list[str] = Field(default_factory=list)


class DecisionContext(BaseModel):
    """Decision context used by runtime policy engine."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    manifest_view: dict[str, dict[str, Any]] = Field(default_factory=dict)
    policy: Any | None = None
    policy_engine: Any | None = None
    lockfile: Any | None = None
    toolsets: dict[str, Any] | None = None
    budgets: dict[str, Any] = Field(default_factory=dict)
    redaction_config: dict[str, Any] = Field(default_factory=dict)
    network_safety: NetworkSafetyConfig = Field(default_factory=NetworkSafetyConfig)
    artifacts_digest_current: str | None = None
    lockfile_digest_current: str | None = None
    approval_root_path: str | None = None
    require_signed_approvals: bool = True
    confirmation_ttl_seconds: int = 300


class DecisionResult(BaseModel):
    """Decision result returned by DecisionEngine."""

    decision: DecisionType
    reason_code: ReasonCode
    reason_message: str
    confirmation_token_id: str | None = None
    redaction_summary: dict[str, Any] = Field(default_factory=dict)
    budget_effects: dict[str, Any] = Field(default_factory=dict)
    audit_fields: dict[str, Any] = Field(default_factory=dict)
