"""Scope-related data models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ScopeType(StrEnum):
    """Types of scopes."""

    FIRST_PARTY_ONLY = "first_party_only"
    AUTH_SURFACE = "auth_surface"
    STATE_CHANGING = "state_changing"
    PII_SURFACE = "pii_surface"
    AGENT_SAFE_READONLY = "agent_safe_readonly"
    CUSTOM = "custom"


class FilterOperator(StrEnum):
    """Operators for filter conditions."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"  # Regex
    IN = "in"
    NOT_IN = "not_in"


class ScopeFilter(BaseModel):
    """A single filter condition."""

    field: str  # e.g., "host", "method", "path", "auth_type", "is_first_party"
    operator: FilterOperator
    value: str | bool | int | list[str]  # Supports various types for matching

    def evaluate(self, endpoint: Any) -> bool:
        """Evaluate this filter against an endpoint.

        Args:
            endpoint: Endpoint object to evaluate

        Returns:
            True if filter matches
        """
        # Get the field value from endpoint
        field_value = self._get_field_value(endpoint)

        # Apply operator
        if self.operator == FilterOperator.EQUALS:
            return bool(field_value == self.value)

        elif self.operator == FilterOperator.NOT_EQUALS:
            return bool(field_value != self.value)

        elif self.operator == FilterOperator.CONTAINS:
            if isinstance(field_value, list) and isinstance(self.value, str):
                return self.value in field_value
            if isinstance(field_value, str) and isinstance(self.value, str):
                return self.value in field_value
            return False

        elif self.operator == FilterOperator.NOT_CONTAINS:
            if isinstance(field_value, list) and isinstance(self.value, str):
                return self.value not in field_value
            if isinstance(field_value, str) and isinstance(self.value, str):
                return self.value not in field_value
            return True

        elif self.operator == FilterOperator.MATCHES:
            import re

            if isinstance(field_value, str) and isinstance(self.value, str):
                return bool(re.match(self.value, field_value, re.IGNORECASE))
            return False

        elif self.operator == FilterOperator.IN:
            if isinstance(self.value, list):
                return field_value in self.value
            return False

        elif self.operator == FilterOperator.NOT_IN:
            if isinstance(self.value, list):
                return field_value not in self.value
            return True

        return False

    def _get_field_value(self, endpoint: Any) -> Any:
        """Get the value of a field from an endpoint."""
        # Handle nested fields with dot notation
        parts = self.field.split(".")
        value = endpoint

        for part in parts:
            if hasattr(value, part):
                value = getattr(value, part)
            elif isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None

        # Handle enum values
        if hasattr(value, "value"):
            return value.value

        return value


class ScopeRule(BaseModel):
    """A rule within a scope (AND of filters)."""

    name: str | None = None
    description: str | None = None

    # Filters (all must match = AND)
    filters: list[ScopeFilter] = Field(default_factory=list)

    # Action when matched
    include: bool = True  # True = include, False = exclude

    def evaluate(self, endpoint: Any) -> bool | None:
        """Evaluate this rule against an endpoint.

        Args:
            endpoint: Endpoint object to evaluate

        Returns:
            True if should include, False if should exclude, None if no match
        """
        # All filters must match (AND logic)
        for filter_ in self.filters:
            if not filter_.evaluate(endpoint):
                return None  # Rule doesn't match

        # All filters matched
        return self.include


class RiskReason(StrEnum):
    """Standardized risk reasons for scope confidence."""

    STATE_CHANGING = "state_changing"
    HAS_PII = "has_pii"
    AUTH_RELATED = "auth_related"
    HIGH_RISK_TIER = "high_risk_tier"
    UNKNOWN_AUTH = "unknown_auth"
    THIRD_PARTY = "third_party"
    WRITE_OPERATION = "write_operation"
    SENSITIVE_PATH = "sensitive_path"


class ScopeDraft(BaseModel):
    """A draft scope assignment with confidence scoring.

    Per docs/architecture.md §6.3: confidence scoring based on signal strength.
    When confidence < 0.7 and risk >= high, review_required is set.
    """

    endpoint_id: str
    scope_name: str
    confidence: float = 0.5  # 0.0 - 1.0
    risk_tier: str = "medium"
    risk_reasons: list[RiskReason] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)  # human-readable signal descriptions
    review_required: bool = False
    explanation: str = ""

    def model_post_init(self, __context: Any) -> None:
        """Auto-set review_required based on confidence and risk."""
        high_risk_tiers = {"high", "critical"}
        if self.confidence < 0.7 and self.risk_tier in high_risk_tiers:
            object.__setattr__(self, "review_required", True)


class Scope(BaseModel):
    """A scope definition for filtering endpoints."""

    # Identity
    name: str
    type: ScopeType = ScopeType.CUSTOM
    description: str | None = None

    # For FIRST_PARTY_ONLY scope
    first_party_hosts: list[str] = Field(default_factory=list)

    # Rules (evaluated in order, first match wins)
    rules: list[ScopeRule] = Field(default_factory=list)

    # Risk settings for this scope
    default_risk_tier: str = "medium"
    confirmation_required: bool = False

    # Rate limits for this scope
    rate_limit_per_minute: int | None = None

    def matches(self, endpoint: Any) -> bool:
        """Check if an endpoint matches this scope.

        Args:
            endpoint: Endpoint to check

        Returns:
            True if endpoint should be included in this scope
        """
        # Evaluate rules in order, first match wins
        for rule in self.rules:
            result = rule.evaluate(endpoint)
            if result is not None:
                return result

        # No rule matched - default to exclude for safety
        return False
