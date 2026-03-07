"""Default policy generator."""

from __future__ import annotations

from typing import Any

from toolwright.models.endpoint import Endpoint
from toolwright.models.scope import Scope
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION


class PolicyGenerator:
    """Generate default enforcement policies from endpoints."""

    def __init__(self, name: str = "Generated Policy") -> None:
        """Initialize the policy generator.

        Args:
            name: Name for the generated policy
        """
        self.name = name

    def generate(
        self,
        endpoints: list[Endpoint],
        scope: Scope | None = None,
    ) -> dict[str, Any]:
        """Generate a default policy from endpoints.

        Args:
            endpoints: List of endpoints
            scope: Optional scope that was applied

        Returns:
            Policy configuration as dict
        """
        # Collect unique hosts
        hosts = sorted({ep.host for ep in endpoints})

        # Build rules
        rules = self._build_rules(endpoints, hosts, scope)

        policy: dict[str, Any] = {
            "version": "1.0.0",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "name": self.name,
            "description": f"Auto-generated policy for {len(endpoints)} endpoints",
            "default_action": "deny",
            "global_rate_limit": 100,
            "audit_all": True,
            "redact_headers": [
                "authorization",
                "cookie",
                "set-cookie",
                "x-api-key",
                "x-auth-token",
                "proxy-authorization",
            ],
            "redact_patterns": [
                r"bearer\s+[a-zA-Z0-9\-_.]+",
                r"api[_-]?key[\"']?\s*[=:]\s*[\"']?[a-zA-Z0-9]+",
            ],
            "redact_pattern_justifications": {
                r"bearer\s+[a-zA-Z0-9\-_.]+": "Redact bearer tokens from logs and evidence.",
                r"api[_-]?key[\"']?\s*[=:]\s*[\"']?[a-zA-Z0-9]+": (
                    "Redact API keys from query strings, payloads, and headers."
                ),
            },
            "state_changing_overrides": [],
            "rules": rules,
        }

        if scope:
            policy["scope"] = scope.name

        return policy

    def _build_rules(
        self,
        endpoints: list[Endpoint],
        hosts: list[str],
        _scope: Scope | None,
    ) -> list[dict[str, Any]]:
        """Build policy rules from endpoints."""
        rules: list[dict[str, Any]] = []
        rule_priority = 100

        # Rule: Allow GraphQL query tools in the readonly toolset without confirmation.
        #
        # At runtime we default to toolset=readonly when toolsets.yaml is present, so
        # scope-aware rules remain safe. This avoids confirmation spam for POST-based
        # GraphQL query actions while still requiring confirmation for write toolsets.
        if any(ep.method.upper() == "POST" and "graphql" in ep.path.lower() for ep in endpoints):
            rules.append(
                {
                    "id": "allow_graphql_readonly",
                    "name": "Allow GraphQL queries in readonly toolset",
                    "type": "allow",
                    "priority": rule_priority + 10,
                    "match": {
                        "hosts": hosts,
                        "methods": ["POST"],
                        "path_pattern": ".*/graphql.*",
                        "scopes": ["readonly"],
                    },
                    "settings": {
                        "allow_without_confirmation": True,
                        "justification": (
                            "GraphQL queries are POST-based but should be usable by autonomous agents "
                            "without out-of-band confirmation when restricted to the readonly toolset."
                        ),
                    },
                }
            )

        # Rule: Allow first-party GET requests
        rules.append({
            "id": "allow_first_party_get",
            "name": "Allow first-party read operations",
            "type": "allow",
            "priority": rule_priority,
            "match": {
                "hosts": hosts,
                "methods": ["GET", "HEAD"],
            },
        })
        rule_priority -= 10

        # Rule: Require confirmation for state-changing operations
        state_changing_endpoints = [ep for ep in endpoints if ep.is_state_changing]
        if state_changing_endpoints:
            rules.append({
                "id": "confirm_state_changes",
                "name": "Require confirmation for mutations",
                "type": "confirm",
                "priority": rule_priority,
                "match": {
                    "methods": ["POST", "PUT", "PATCH", "DELETE"],
                },
                "settings": {
                    "message": "This action will modify data. Proceed?",
                },
            })
            rule_priority -= 10

        # Rule: Budget for write operations
        rules.append({
            "id": "budget_writes",
            "name": "Rate limit write operations",
            "type": "budget",
            "priority": rule_priority,
            "match": {
                "methods": ["POST", "PUT", "PATCH"],
            },
            "settings": {
                "per_minute": 10,
                "per_hour": 100,
            },
        })
        rule_priority -= 10

        # Rule: Extra strict budget for deletes
        rules.append({
            "id": "budget_deletes",
            "name": "Strict rate limit for deletes",
            "type": "budget",
            "priority": rule_priority,
            "match": {
                "methods": ["DELETE"],
            },
            "settings": {
                "per_minute": 5,
                "per_hour": 20,
            },
        })
        rule_priority -= 10

        # Rule: Audit auth operations
        auth_endpoints = [ep for ep in endpoints if ep.is_auth_related]
        if auth_endpoints:
            rules.append({
                "id": "audit_auth",
                "name": "Detailed audit for auth operations",
                "type": "audit",
                "priority": rule_priority,
                "match": {
                    "path_pattern": ".*/(login|logout|auth|token|session).*",
                },
                "settings": {
                    "level": "detailed",
                    "include_body": False,
                    "justification": "Authentication surfaces require heightened audit visibility.",
                },
            })
            rule_priority -= 10

        # Rule: Extra protection for PII endpoints
        pii_endpoints = [ep for ep in endpoints if ep.has_pii]
        if pii_endpoints:
            rules.append({
                "id": "protect_pii",
                "name": "Extra protection for PII",
                "type": "confirm",
                "priority": rule_priority,
                "match": {
                    "path_pattern": ".*/(user|profile|account|customer).*",
                },
                "settings": {
                    "message": "This endpoint handles personal data. Confirm access?",
                    "justification": "PII-linked endpoints require explicit human confirmation.",
                },
            })

        return rules

    def to_yaml(self, policy: dict[str, Any]) -> str:
        """Serialize policy to YAML string.

        Args:
            policy: Policy dict

        Returns:
            YAML string
        """
        import yaml

        return yaml.dump(policy, default_flow_style=False, allow_unicode=True, sort_keys=False)
