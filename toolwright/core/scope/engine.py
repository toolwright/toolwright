"""Scope engine for filtering endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from toolwright.core.scope.builtins import get_builtin_scope
from toolwright.core.scope.parser import parse_scope_file
from toolwright.models.scope import Scope, ScopeType

if TYPE_CHECKING:
    from toolwright.models.endpoint import Endpoint


class ScopeEngine:
    """Engine for evaluating scopes and filtering endpoints."""

    def __init__(self, first_party_hosts: list[str] | None = None) -> None:
        """Initialize the scope engine.

        Args:
            first_party_hosts: List of first-party host patterns
        """
        self.first_party_hosts = first_party_hosts or []
        self._custom_scopes: dict[str, Scope] = {}

    def load_scope(self, name: str, scope_file: str | None = None) -> Scope:
        """Load a scope by name.

        Args:
            name: Scope name (built-in or custom)
            scope_file: Optional path to custom scope YAML file

        Returns:
            Scope object

        Raises:
            ValueError: If scope not found
        """
        # Try loading from file first
        if scope_file:
            scope = parse_scope_file(scope_file)
            scope.first_party_hosts = self.first_party_hosts
            return scope

        # Try custom scopes
        if name in self._custom_scopes:
            return self._custom_scopes[name]

        # Try built-in scopes
        try:
            scope_type = ScopeType(name)
            scope = get_builtin_scope(scope_type, self.first_party_hosts)
            return scope
        except ValueError:
            pass

        raise ValueError(f"Unknown scope: {name}")

    def register_scope(self, scope: Scope) -> None:
        """Register a custom scope.

        Args:
            scope: Scope to register
        """
        self._custom_scopes[scope.name] = scope

    def filter_endpoints(
        self,
        endpoints: list[Endpoint],
        scope: Scope,
    ) -> list[Endpoint]:
        """Filter endpoints by scope rules.

        Args:
            endpoints: List of endpoints to filter
            scope: Scope to apply

        Returns:
            Filtered list of endpoints
        """
        return [ep for ep in endpoints if scope.matches(ep)]

    def classify_endpoint(
        self,
        endpoint: Endpoint,
        scope: Scope,
    ) -> dict[str, Any]:
        """Return classification info for endpoint in scope.

        Args:
            endpoint: Endpoint to classify
            scope: Scope context

        Returns:
            Classification dict with risk tier, confirmation requirement, etc.
        """
        matches = scope.matches(endpoint)

        # Determine risk tier
        risk_tier = endpoint.risk_tier
        if matches:
            # Use scope's default risk tier as minimum
            risk_order = ["safe", "low", "medium", "high", "critical"]
            scope_idx = risk_order.index(scope.default_risk_tier)
            endpoint_idx = risk_order.index(endpoint.risk_tier)
            if scope_idx > endpoint_idx:
                risk_tier = scope.default_risk_tier

        return {
            "matches_scope": matches,
            "risk_tier": risk_tier,
            "confirmation_required": scope.confirmation_required or endpoint.is_state_changing,
            "rate_limit": scope.rate_limit_per_minute,
            "scope_name": scope.name,
            "scope_type": scope.type.value,
        }

    def get_available_scopes(self) -> list[str]:
        """Get list of available scope names.

        Returns:
            List of scope names (built-in + custom)
        """
        builtin = [s.value for s in ScopeType if s != ScopeType.CUSTOM]
        custom = list(self._custom_scopes.keys())
        return builtin + custom
