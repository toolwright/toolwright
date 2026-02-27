"""Toolset artifact generator for curated action surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import yaml

from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION

READ_METHODS = {"GET", "HEAD"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_graphql_query_action(action: dict[str, Any]) -> bool:
    """Return True for operation-scoped GraphQL query actions."""
    operation_type = str(action.get("graphql_operation_type", "")).lower()
    fixed_body = action.get("fixed_body")
    if operation_type != "query":
        return False
    if not isinstance(fixed_body, dict):
        return False
    return isinstance(fixed_body.get("operationName"), str)


class ToolsetGenerator:
    """Generate named toolsets from a compiled tools manifest."""

    def __init__(
        self,
        default_toolset: str = "readonly",
    ) -> None:
        """Initialize the toolset generator."""
        self.default_toolset = default_toolset

    def generate(
        self,
        manifest: dict[str, Any],
        generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Build first-class toolset artifact from a tools manifest."""
        actions = list(manifest.get("actions", []))
        actions_sorted = sorted(actions, key=lambda a: str(a.get("name", "")))

        all_actions = [a["name"] for a in actions_sorted if "name" in a]
        readonly_actions = [
            a["name"]
            for a in actions_sorted
            if "name" in a
            and (
                str(a.get("method", "GET")).upper() in READ_METHODS or _is_graphql_query_action(a)
            )
            and str(a.get("risk_tier", "low")).lower() not in {"high", "critical"}
        ]
        write_actions = [
            a["name"]
            for a in actions_sorted
            if "name" in a
            and str(a.get("method", "GET")).upper() in WRITE_METHODS
            and not _is_graphql_query_action(a)
        ]
        high_risk_actions = [
            a["name"]
            for a in actions_sorted
            if str(a.get("risk_tier", "low")).lower() in {"high", "critical"} and "name" in a
        ]

        return {
            "version": "1.0.0",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
            "source_manifest": manifest.get("name", "Generated Tools"),
            "capture_id": manifest.get("capture_id"),
            "scope": manifest.get("scope"),
            "default_toolset": self.default_toolset,
            "toolsets": {
                "readonly": {
                    "description": "Read-only tools for autonomous agents",
                    "actions": readonly_actions,
                },
                "write_ops": {
                    "description": "State-changing tools requiring explicit operator approval",
                    "actions": write_actions,
                },
                "high_risk": {
                    "description": "High/critical risk tools requiring extra controls",
                    "actions": high_risk_actions,
                },
                "operator": {
                    "description": "Full reviewed tool surface for trusted operator flows",
                    "actions": all_actions,
                },
            },
        }

    def to_yaml(self, toolsets: dict[str, Any]) -> str:
        """Serialize toolsets artifact to YAML."""
        return yaml.dump(toolsets, default_flow_style=False, allow_unicode=True, sort_keys=False)
