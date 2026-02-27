"""Endpoint-related data models."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AuthType(StrEnum):
    """Detected authentication type."""

    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    COOKIE = "cookie"
    BASIC = "basic"
    OAUTH2 = "oauth2"
    UNKNOWN = "unknown"


class ParameterLocation(StrEnum):
    """Where a parameter appears."""

    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    BODY = "body"
    COOKIE = "cookie"


class Parameter(BaseModel):
    """An API parameter."""

    name: str
    location: ParameterLocation
    param_type: str = "string"
    required: bool = False
    default: Any | None = None
    example: Any | None = None
    description: str | None = None
    json_schema: dict[str, Any] | None = None  # Renamed from 'schema' to avoid shadowing
    pattern: str | None = None


class Endpoint(BaseModel):
    """A normalized API endpoint."""

    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    stable_id: str | None = None  # Hash of method + normalized_path + host

    # Three-layer identity (from STRATEGY.md)
    signature_id: str | None = None  # Physical: sha256(method + host + path + params)
    tool_id: str | None = None  # Logical: human-friendly name (e.g., get_user)
    tool_version: int = 1  # Incremented on breaking changes
    aliases: list[str] = Field(default_factory=list)  # Previous signature_ids

    # Core properties
    method: str
    path: str  # Normalized path (e.g., /api/users/{id})
    host: str

    # Full URL for reference
    url: str | None = None

    # Parameters
    parameters: list[Parameter] = Field(default_factory=list)

    # Request details
    request_content_type: str | None = None
    request_body_schema: dict[str, Any] | None = None
    request_examples: list[dict[str, Any]] = Field(default_factory=list)

    # Response details
    response_status_codes: list[int] = Field(default_factory=list)
    response_content_type: str | None = None
    response_body_schema: dict[str, Any] | None = None
    response_examples: list[dict[str, Any]] = Field(default_factory=list)

    # Auth detection
    auth_type: AuthType = AuthType.UNKNOWN
    auth_header: str | None = None

    # Tags (semantic labels for scoping/filtering)
    tags: list[str] = Field(default_factory=list)

    # Classification
    is_first_party: bool = True
    is_state_changing: bool = False
    is_auth_related: bool = False
    has_pii: bool = False

    # Risk assessment
    risk_tier: str = "low"

    # Observation metadata
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    observation_count: int = 1

    # Confidence in inferences
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    # Raw exchange references
    exchange_ids: list[str] = Field(default_factory=list)

    def compute_signature_id(self) -> str:
        """Compute the signature_id from method, host, path, and params."""
        param_keys = sorted([p.name for p in self.parameters])
        canonical = f"{self.method.upper()}:{self.host}:{self.path}:{','.join(param_keys)}"
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def compute_stable_id(self) -> str:
        """Compute stable_id from method, host, and normalized path."""
        canonical = f"{self.method.upper()}:{self.host}:{self.path}"
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def generate_tool_id(self) -> str:
        """Generate a human-friendly tool_id using verb_noun pattern."""
        from toolwright.utils.naming import generate_tool_name

        return generate_tool_name(self.method, self.path)

    def model_post_init(self, __context: Any) -> None:
        """Compute IDs if not set."""
        if not self.stable_id:
            object.__setattr__(self, "stable_id", self.compute_stable_id())
        if not self.signature_id:
            object.__setattr__(self, "signature_id", self.compute_signature_id())
        if not self.tool_id:
            object.__setattr__(self, "tool_id", self.generate_tool_id())

        # Determine if state-changing
        if self.method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            object.__setattr__(self, "is_state_changing", True)
