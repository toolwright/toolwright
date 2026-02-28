"""Async reconciliation loop.

Level-triggered: each cycle compares desired state (tools exist and are healthy)
against actual state (health probe results). When SCHEMA_CHANGED is detected,
runs drift detection via endpoint re-discovery. Idempotent and crash-safe.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from toolwright.core.health.checker import HealthChecker, HealthResult
from toolwright.core.reconcile.differ import DriftDiffer
from toolwright.core.reconcile.event_log import ReconcileEventLog
from toolwright.core.reconcile.prober import HealthProber
from toolwright.core.reconcile.rediscovery import rediscover_endpoints
from toolwright.core.repair.applier import RepairApplier
from toolwright.models.drift import DriftReport, DriftType
from toolwright.models.endpoint import Endpoint
from toolwright.models.reconcile import (
    EventKind,
    ReconcileAction,
    ReconcileEvent,
    ReconcileState,
    ToolReconcileState,
    ToolStatus,
    WatchConfig,
)
from toolwright.models.repair import PatchAction, PatchItem, PatchKind, RepairPatchPlan

logger = logging.getLogger(__name__)

STATE_FILE = ".toolwright/state/reconcile.json"


class ReconcileLoop:
    """Async reconciliation loop for tool health monitoring.

    Probes tool endpoints on risk-tier-based intervals, records state
    transitions in an event log, persists state to disk, and optionally
    updates circuit breakers.
    """

    def __init__(
        self,
        *,
        project_root: str,
        actions: list[dict],
        risk_tiers: dict[str, str],
        config: WatchConfig | None = None,
        checker: HealthChecker | None = None,
        breaker_registry: Any | None = None,
    ) -> None:
        self._project_root = Path(project_root)
        self._actions = actions
        self._risk_tiers = risk_tiers
        self.config = config or WatchConfig()
        self._auto_heal = self.config.auto_heal
        self._breaker_registry = breaker_registry

        self._event_log = ReconcileEventLog(project_root)
        self._prober = HealthProber(
            checker=checker or HealthChecker(),
            config=self.config,
        )
        self._differ = DriftDiffer()

        # Build a lookup: tool_id -> action dict (for host extraction)
        self._action_by_tool: dict[str, dict] = {
            a.get("name", ""): a for a in actions
        }

        self._state = self._load_state()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    # -- Public API --------------------------------------------------------

    def get_state(self) -> ReconcileState:
        """Return a copy of the current reconciliation state."""
        return self._state.model_copy(deep=True)

    @property
    def is_running(self) -> bool:
        """Whether the loop is currently running."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the reconciliation loop as a background task."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the reconciliation loop gracefully."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    # -- Core loop ---------------------------------------------------------

    async def _run(self) -> None:
        """Main loop: run cycles until stopped."""
        tick = self._compute_tick()
        while not self._stop_event.is_set():
            await self._reconcile_cycle()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=tick)
                break  # stop_event was set
            except TimeoutError:
                pass  # normal: tick elapsed, run next cycle

    async def _reconcile_cycle(self) -> None:
        """Execute one probe → classify → drift-check → record → persist cycle.

        Fail-closed: exceptions are caught, logged, and counted.
        """
        try:
            results = await self._prober.probe_due_tools(
                self._actions,
                self._state.tools,
                self._risk_tiers,
            )
            for tool_id, result in results.items():
                self._process_probe_result(tool_id, result)

            # Drift detection phase: check tools that reported SCHEMA_CHANGED
            for tool_id, result in results.items():
                if self._differ.should_check_drift(result):
                    await self._handle_drift(tool_id, result)
        except Exception:
            logger.exception("Reconcile cycle error")
            self._state.errors += 1

        self._state.reconcile_count += 1
        self._state.last_full_reconcile = datetime.now(UTC).isoformat()
        self._persist_state()

    # -- Result processing -------------------------------------------------

    def _process_probe_result(self, tool_id: str, result: HealthResult) -> None:
        """Update state and record events based on a probe result."""
        tool_state = self._state.tools.get(tool_id)
        if tool_state is None:
            tool_state = ToolReconcileState(tool_id=tool_id)
            self._state.tools[tool_id] = tool_state

        now = datetime.now(UTC).isoformat()
        tool_state.last_probe_at = now

        if result.healthy:
            tool_state.status = ToolStatus.HEALTHY
            tool_state.consecutive_healthy += 1
            tool_state.consecutive_unhealthy = 0
            tool_state.failure_class = None
            self._record_event(
                EventKind.PROBE_HEALTHY,
                tool_id,
                f"Health probe passed (status={result.status_code}, "
                f"time={result.response_time_ms:.0f}ms)",
            )
            if self._breaker_registry is not None:
                self._breaker_registry.record_success(tool_id)
        else:
            tool_state.status = ToolStatus.UNHEALTHY
            tool_state.consecutive_unhealthy += 1
            tool_state.consecutive_healthy = 0
            tool_state.failure_class = (
                result.failure_class.value if result.failure_class else None
            )
            self._record_event(
                EventKind.PROBE_UNHEALTHY,
                tool_id,
                f"Health probe failed: {result.failure_class} "
                f"(status={result.status_code}, error={result.error_message})",
            )
            if self._breaker_registry is not None:
                self._breaker_registry.record_failure(
                    tool_id, result.error_message or "probe failed"
                )

    # -- Drift detection ---------------------------------------------------

    async def _handle_drift(self, tool_id: str, _result: HealthResult) -> None:
        """Run drift detection for a tool that reported SCHEMA_CHANGED.

        Rediscovery failure sets the tool to DEGRADED but does not change
        it to UNHEALTHY (per user requirement). Exceptions are caught
        to maintain fail-closed behavior.
        """
        tool_state = self._state.tools.get(tool_id)
        if tool_state is None:
            return

        try:
            current_endpoints = await self._rediscover_endpoints(tool_id)
        except Exception:
            logger.warning(
                "Rediscovery failed for %s, marking as DEGRADED", tool_id,
                exc_info=True,
            )
            tool_state.status = ToolStatus.DEGRADED
            self._record_event(
                EventKind.DRIFT_DETECTED,
                tool_id,
                "Rediscovery failed. No OpenAPI spec discovered. "
                "Schema drift detection requires manual re-capture.",
            )
            return

        if current_endpoints is None:
            # No spec found - likely HAR-captured API
            tool_state.status = ToolStatus.DEGRADED
            self._record_event(
                EventKind.DRIFT_DETECTED,
                tool_id,
                "No OpenAPI spec discovered. Tools were likely minted "
                "from captured traffic. Schema drift detection requires "
                "manual re-capture.",
            )
            return

        # Get the toolpack's baseline endpoints for this tool
        baseline_endpoints = self._get_toolpack_endpoints(tool_id)

        report = self._differ.check_drift(baseline_endpoints, current_endpoints)

        if report.total_drifts > 0:
            tool_state.status = ToolStatus.DEGRADED
            tool_state.last_action = ReconcileAction.APPROVAL_QUEUED
            self._record_event(
                EventKind.DRIFT_DETECTED,
                tool_id,
                f"API drift detected: {report.total_drifts} changes "
                f"({report.breaking_count} breaking, "
                f"{report.additive_count} additive, "
                f"{report.risk_count} risk)",
            )
            # Repair phase: attempt auto-repair based on policy
            self._handle_repair(tool_id, report)
        else:
            # Schema changed but no drift — may be a transient issue
            tool_state.status = ToolStatus.DEGRADED
            self._record_event(
                EventKind.DRIFT_DETECTED,
                tool_id,
                "SCHEMA_CHANGED reported but no drift found after "
                "re-discovery. May be a transient issue.",
            )

    async def _rediscover_endpoints(
        self, tool_id: str
    ) -> list[Endpoint] | None:
        """Discover current endpoints for a tool's host.

        Uses the tool's action dict to extract the host, then delegates
        to the rediscovery module.
        """
        action = self._action_by_tool.get(tool_id)
        if action is None:
            return None

        host = action.get("host", "")
        if not host:
            return None

        return await rediscover_endpoints(host=host)

    def _get_toolpack_endpoints(self, tool_id: str) -> list[Endpoint]:
        """Build baseline endpoints from the tool's action dict.

        Returns a minimal list for drift comparison.
        """
        action = self._action_by_tool.get(tool_id)
        if action is None:
            return []

        return [
            Endpoint(
                method=action.get("method", "GET"),
                path=action.get("path", "/"),
                host=action.get("host", ""),
            )
        ]

    # -- Auto-repair -------------------------------------------------------

    _REPAIR_MAX_FAILURES = 3
    _REPAIR_WINDOW_SECONDS = 3600  # 1 hour

    def _handle_repair(self, tool_id: str, drift_report: DriftReport) -> None:
        """Create a repair plan from a DriftReport and apply it.

        Maps each DriftItem to a PatchItem based on its type:
          - BREAKING changes -> APPROVAL_REQUIRED / GATE_SYNC
          - ADDITIVE changes -> SAFE / VERIFY_CONTRACTS
          - All others       -> MANUAL / INVESTIGATE

        Tracks consecutive repair failures per tool. After 3 failures
        within a 1-hour window, auto-heal is suspended for that tool.
        """
        tool_state = self._state.tools.get(tool_id)
        if tool_state is None:
            return

        # Skip if repair is suspended for this tool
        if tool_state.repair_suspended:
            logger.debug(
                "Skipping repair for %s — auto-heal suspended", tool_id,
            )
            return

        patches: list[PatchItem] = []
        for item in drift_report.drifts:
            if item.type == DriftType.BREAKING:
                kind = PatchKind.APPROVAL_REQUIRED
                action = PatchAction.GATE_SYNC
            elif item.type == DriftType.ADDITIVE:
                kind = PatchKind.SAFE
                action = PatchAction.VERIFY_CONTRACTS
            else:
                kind = PatchKind.MANUAL
                action = PatchAction.INVESTIGATE

            patches.append(
                PatchItem(
                    id=f"patch-{item.id}",
                    diagnosis_id=item.id,
                    kind=kind,
                    action=action,
                    cli_command=f"toolwright repair apply --patch {item.id}",
                    title=item.title,
                    description=item.description,
                    reason=f"Auto-generated from drift item {item.id}",
                )
            )

        plan = RepairPatchPlan(
            total_patches=len(patches),
            safe_count=sum(1 for p in patches if p.kind == PatchKind.SAFE),
            approval_required_count=sum(
                1 for p in patches if p.kind == PatchKind.APPROVAL_REQUIRED
            ),
            manual_count=sum(1 for p in patches if p.kind == PatchKind.MANUAL),
            patches=patches,
        )

        toolpack_dir = self._project_root / ".toolwright"
        applier = RepairApplier(toolpack_dir, self._auto_heal)
        result = applier.apply_plan(plan)

        # Record events for each patch result
        for pr in result.results:
            if pr.applied:
                tool_state.last_action = ReconcileAction.AUTO_REPAIRED
                self._state.auto_repairs_applied += 1
                self._record_event(
                    EventKind.AUTO_REPAIRED,
                    tool_id,
                    f"Patch {pr.patch_id} auto-applied",
                )
            else:
                # Not applied — queue for approval or manual
                tool_state.last_action = ReconcileAction.APPROVAL_QUEUED
                self._state.approvals_queued += 1
                self._record_event(
                    EventKind.APPROVAL_QUEUED,
                    tool_id,
                    f"Patch {pr.patch_id} queued: {pr.reason}",
                )

        # Track repair success/failure for retry budget
        any_applied = any(pr.applied for pr in result.results)
        if any_applied:
            tool_state.consecutive_repair_failures = 0
            tool_state.repair_suspended = False
            tool_state.first_failure_at = None
            logger.info(
                "Patch applied to %s, will verify on next probe cycle",
                tool_id,
            )
        elif result.total > 0:
            now = time.time()
            # Reset window if first failure was >1 hour ago
            if (
                tool_state.first_failure_at is not None
                and now - tool_state.first_failure_at > self._REPAIR_WINDOW_SECONDS
            ):
                tool_state.consecutive_repair_failures = 0
                tool_state.first_failure_at = None
            if tool_state.first_failure_at is None:
                tool_state.first_failure_at = now
            tool_state.consecutive_repair_failures += 1
            if tool_state.consecutive_repair_failures >= self._REPAIR_MAX_FAILURES:
                tool_state.repair_suspended = True
                logger.warning(
                    "Auto-heal suspended for %s after %d consecutive failures. "
                    "Run `toolwright repair plan` to review manually.",
                    tool_id,
                    tool_state.consecutive_repair_failures,
                )

        # Increment version after repair processing
        if result.total > 0:
            tool_state.version += 1

    # -- Helpers -----------------------------------------------------------

    def _record_event(
        self, kind: EventKind, tool_id: str, description: str
    ) -> None:
        """Record an event in the JSONL log."""
        event = ReconcileEvent(
            kind=kind,
            tool_id=tool_id,
            description=description,
        )
        self._event_log.record(event)

    def _compute_tick(self) -> float:
        """Compute the sleep interval between cycles.

        Uses half the minimum probe interval, with a floor of 10 seconds.
        """
        if not self.config.probe_intervals:
            return 10.0
        min_interval = min(self.config.probe_intervals.values())
        return max(min_interval / 2, 10.0)

    def _persist_state(self) -> None:
        """Write current state to disk."""
        state_path = self._project_root / STATE_FILE
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(self._state.model_dump_json(indent=2))

    def _load_state(self) -> ReconcileState:
        """Load state from disk if it exists, otherwise return defaults."""
        state_path = self._project_root / STATE_FILE
        if not state_path.exists():
            return ReconcileState()
        try:
            return ReconcileState.model_validate_json(state_path.read_text())
        except Exception:
            logger.warning("Failed to load reconcile state, starting fresh")
            return ReconcileState()
