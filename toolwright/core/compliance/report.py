"""EU AI Act compliance report generator.

Generates structured evidence of:
- Human oversight (approval chain, who approved what)
- Tool inventory (what tools agents can access, by risk tier)
- Risk management (tools by tier, drift history, blocked requests)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class ComplianceReporter:
    """Generate compliance reports for EU AI Act and governance audits."""

    def generate(
        self,
        tools_manifest: dict[str, Any] | None = None,
        approval_history: list[dict[str, Any]] | None = None,
        drift_history: list[dict[str, Any]] | None = None,
        blocked_requests: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate a structured compliance report.

        Args:
            tools_manifest: The tools.json manifest
            approval_history: List of approval/rejection events
            drift_history: List of drift reports
            blocked_requests: List of blocked enforcement events

        Returns:
            Structured report dict (JSON-serializable)
        """
        actions = (tools_manifest or {}).get("actions", [])
        approvals = approval_history or []
        drifts = drift_history or []
        blocked = blocked_requests or []

        return {
            "report_version": "1.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "human_oversight": self._human_oversight_section(approvals),
            "tool_inventory": self._tool_inventory_section(actions),
            "risk_management": self._risk_management_section(actions, drifts, blocked),
            "accuracy_monitoring": self._accuracy_monitoring_section(drifts),
        }

    def _human_oversight_section(
        self, approvals: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Evidence of human-in-the-loop approval chain."""
        approved = [a for a in approvals if a.get("status") == "approved"]
        rejected = [a for a in approvals if a.get("status") == "rejected"]
        approvers = sorted({a.get("by", "unknown") for a in approved})

        return {
            "approval_count": len(approved),
            "rejection_count": len(rejected),
            "unique_approvers": approvers,
            "approval_required": True,
            "auto_approval_enabled": False,
            "evidence": [
                {
                    "action": a.get("action"),
                    "status": a.get("status"),
                    "by": a.get("by"),
                    "at": a.get("at"),
                }
                for a in approvals
            ],
        }

    def _tool_inventory_section(
        self, actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Complete inventory of accessible tools."""
        return {
            "total_tools": len(actions),
            "tools": [
                {
                    "name": a.get("name"),
                    "method": a.get("method"),
                    "risk_tier": a.get("risk_tier", "unknown"),
                    "description": a.get("description", ""),
                }
                for a in actions
            ],
        }

    def _risk_management_section(
        self,
        actions: list[dict[str, Any]],
        drifts: list[dict[str, Any]],
        blocked: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Risk management evidence: tools by tier, blocked requests."""
        by_tier: dict[str, int] = {}
        for a in actions:
            tier = a.get("risk_tier", "unknown")
            by_tier[tier] = by_tier.get(tier, 0) + 1

        return {
            "by_tier": by_tier,
            "total_drift_reports": len(drifts),
            "total_blocked_requests": len(blocked),
            "deny_by_default": True,
            "confirmation_required_for_writes": True,
        }

    def _accuracy_monitoring_section(
        self, drifts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Drift history as accuracy/stability monitoring evidence."""
        breaking_count = sum(
            1 for d in drifts if d.get("has_breaking_changes")
        )
        return {
            "total_drift_checks": len(drifts),
            "breaking_drift_count": breaking_count,
            "drift_detection_enabled": True,
        }
