"""Health prober with scheduling and exponential backoff.

Wraps HealthChecker with risk-tier-based intervals and
backoff for persistently unhealthy tools.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from toolwright.core.health.checker import FailureClass, HealthChecker, HealthResult
from toolwright.models.reconcile import ToolReconcileState, ToolStatus, WatchConfig


class HealthProber:
    """Schedule-aware health prober.

    Decides which tools are due for probing based on risk-tier intervals
    and exponential backoff for unhealthy tools, then delegates to
    HealthChecker for the actual HTTP probe.
    """

    def __init__(
        self,
        *,
        checker: HealthChecker | Any,
        config: WatchConfig,
    ) -> None:
        self.checker = checker
        self.config = config

    def should_probe(self, state: ToolReconcileState, risk_tier: str) -> bool:
        """Decide whether a tool is due for probing.

        Args:
            state: Current reconciliation state for the tool.
            risk_tier: Risk tier of the tool (critical/high/medium/low).

        Returns:
            True if the tool should be probed now.
        """
        if state.last_probe_at is None:
            return True

        base_interval = self.config.probe_interval_for_risk(risk_tier)

        # Apply exponential backoff for unhealthy tools
        if state.status == ToolStatus.UNHEALTHY and state.consecutive_unhealthy > 0:
            effective_interval = base_interval * (
                self.config.unhealthy_backoff_multiplier ** state.consecutive_unhealthy
            )
            effective_interval = min(effective_interval, self.config.unhealthy_backoff_max)
        else:
            effective_interval = base_interval

        last_probe = datetime.fromisoformat(state.last_probe_at)
        elapsed = (datetime.now(UTC) - last_probe).total_seconds()
        return elapsed >= effective_interval

    async def probe_tool(self, action: dict[str, Any]) -> HealthResult:
        """Probe a single tool by delegating to HealthChecker.

        Args:
            action: Dict with ``name``, ``method``, ``host``, ``path`` keys.

        Returns:
            HealthResult from the probe, or a synthetic unhealthy result on error.
        """
        tool_id = action.get("name", "unknown")
        try:
            return await self.checker.check_tool(action)
        except Exception as exc:
            return HealthResult(
                tool_id=tool_id,
                healthy=False,
                failure_class=FailureClass.UNKNOWN,
                error_message=f"{type(exc).__name__}: {exc}",
            )

    async def probe_due_tools(
        self,
        actions: list[dict[str, Any]],
        states: dict[str, ToolReconcileState],
        risk_tiers: dict[str, str],
    ) -> dict[str, HealthResult]:
        """Probe all tools that are due, respecting concurrency limits.

        Args:
            actions: List of action dicts (each has ``name``, ``method``, ``host``, ``path``).
            states: Current reconciliation state per tool_id.
            risk_tiers: Risk tier per tool_id.

        Returns:
            Dict mapping tool_id → HealthResult for tools that were probed.
        """
        due: list[dict[str, Any]] = []
        for action in actions:
            tool_id = action.get("name", "unknown")
            state = states.get(tool_id, ToolReconcileState(tool_id=tool_id))
            tier = risk_tiers.get(tool_id, "medium")
            if self.should_probe(state, tier):
                due.append(action)

        if not due:
            return {}

        semaphore = asyncio.Semaphore(self.config.max_concurrent_probes)

        async def bounded_probe(action: dict[str, Any]) -> HealthResult:
            async with semaphore:
                return await self.probe_tool(action)

        results = await asyncio.gather(*[bounded_probe(a) for a in due])
        return {r.tool_id: r for r in results}
