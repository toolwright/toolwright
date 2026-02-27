"""Integration tests for the full reconcile lifecycle.

Tests the complete flow: probe -> detect drift -> repair plan -> auto-apply -> snapshot.
Each test class verifies a specific integration point across multiple components.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolwright.core.health.checker import FailureClass, HealthResult
from toolwright.core.reconcile.loop import ReconcileLoop
from toolwright.models.drift import DriftItem, DriftReport, DriftSeverity, DriftType
from toolwright.models.endpoint import Endpoint
from toolwright.models.reconcile import (
    AutoHealPolicy,
    EventKind,
    ReconcileAction,
    ReconcileState,
    ToolReconcileState,
    ToolStatus,
    WatchConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _healthy_result(tool_id: str) -> HealthResult:
    return HealthResult(
        tool_id=tool_id, healthy=True, status_code=200, response_time_ms=50.0
    )


def _unhealthy_result(
    tool_id: str,
    failure_class: FailureClass = FailureClass.SERVER_ERROR,
) -> HealthResult:
    return HealthResult(
        tool_id=tool_id,
        healthy=False,
        failure_class=failure_class,
        status_code=500,
        response_time_ms=100.0,
        error_message="Internal Server Error",
    )


def _schema_changed_result(tool_id: str) -> HealthResult:
    return HealthResult(
        tool_id=tool_id,
        healthy=False,
        failure_class=FailureClass.SCHEMA_CHANGED,
        status_code=200,
        response_time_ms=80.0,
        error_message="Schema mismatch detected",
    )


def _make_actions(*tool_ids: str) -> list[dict]:
    return [
        {"name": tid, "method": "GET", "host": "api.example.com", "path": f"/{tid}"}
        for tid in tool_ids
    ]


def _make_risk_tiers(*tool_ids: str) -> dict[str, str]:
    return {tid: "medium" for tid in tool_ids}


def _additive_drift_endpoints() -> list[Endpoint]:
    """Endpoints that produce additive-only drift (new endpoint added)."""
    return [
        Endpoint(method="GET", path="/get_users", host="api.example.com"),
        Endpoint(method="GET", path="/get_users/search", host="api.example.com"),
    ]


def _breaking_drift_endpoints() -> list[Endpoint]:
    """Endpoints that produce breaking drift (baseline removed)."""
    return [
        Endpoint(method="POST", path="/users/v2", host="api.example.com"),
    ]


def _make_loop(tmp_path: Path, **kwargs) -> ReconcileLoop:
    """Build a ReconcileLoop with sensible test defaults."""
    defaults = {
        "project_root": str(tmp_path),
        "actions": _make_actions("get_users"),
        "risk_tiers": _make_risk_tiers("get_users"),
    }
    defaults.update(kwargs)
    return ReconcileLoop(**defaults)


# ---------------------------------------------------------------------------
# TestReconcileLoopLifecycle
# ---------------------------------------------------------------------------


class TestReconcileLoopLifecycle:
    """Integration tests for probe-based lifecycle state tracking."""

    @pytest.mark.asyncio
    async def test_probe_updates_tool_state(self, tmp_path: Path) -> None:
        """Start loop, run one cycle with healthy probe -> tool state is HEALTHY."""
        loop = _make_loop(tmp_path)
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        state = loop.get_state()
        tool = state.tools["get_users"]
        assert tool.status == ToolStatus.HEALTHY
        assert tool.consecutive_healthy == 1
        assert tool.consecutive_unhealthy == 0
        assert tool.last_probe_at is not None

    @pytest.mark.asyncio
    async def test_unhealthy_probe_records_failure(self, tmp_path: Path) -> None:
        """Unhealthy probe -> tool state UNHEALTHY, consecutive_unhealthy increments."""
        loop = _make_loop(tmp_path)
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _unhealthy_result("get_users")}
        )

        await loop._reconcile_cycle()
        await loop._reconcile_cycle()

        state = loop.get_state()
        tool = state.tools["get_users"]
        assert tool.status == ToolStatus.UNHEALTHY
        assert tool.consecutive_unhealthy == 2
        assert tool.consecutive_healthy == 0
        assert tool.failure_class == FailureClass.SERVER_ERROR.value

    @pytest.mark.asyncio
    async def test_healthy_recovery_resets_counters(self, tmp_path: Path) -> None:
        """Tool was unhealthy, now healthy -> consecutive_unhealthy reset to 0."""
        loop = _make_loop(tmp_path)

        # First two cycles: unhealthy
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _unhealthy_result("get_users")}
        )
        await loop._reconcile_cycle()
        await loop._reconcile_cycle()
        assert loop.get_state().tools["get_users"].consecutive_unhealthy == 2

        # Third cycle: healthy recovery
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )
        await loop._reconcile_cycle()

        tool = loop.get_state().tools["get_users"]
        assert tool.status == ToolStatus.HEALTHY
        assert tool.consecutive_unhealthy == 0
        assert tool.consecutive_healthy == 1
        assert tool.failure_class is None

    @pytest.mark.asyncio
    async def test_reconcile_state_persisted_to_disk(self, tmp_path: Path) -> None:
        """After cycle, reconcile.json exists on disk with correct state."""
        loop = _make_loop(tmp_path)
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        state_file = tmp_path / ".toolwright" / "state" / "reconcile.json"
        assert state_file.exists(), "reconcile.json should be written after cycle"

        data = json.loads(state_file.read_text())
        assert data["reconcile_count"] == 1
        assert "get_users" in data["tools"]
        assert data["tools"]["get_users"]["status"] == ToolStatus.HEALTHY.value

        # Verify round-trip: create a new loop that loads persisted state
        loop2 = _make_loop(tmp_path)
        loaded = loop2.get_state()
        assert loaded.reconcile_count == 1
        assert loaded.tools["get_users"].status == ToolStatus.HEALTHY


# ---------------------------------------------------------------------------
# TestDriftToRepairFlow
# ---------------------------------------------------------------------------


class TestDriftToRepairFlow:
    """Integration tests for the drift detection -> repair pipeline."""

    @pytest.mark.asyncio
    async def test_drift_detected_creates_event(self, tmp_path: Path) -> None:
        """When drift is detected, a DRIFT_DETECTED event is logged."""
        loop = _make_loop(tmp_path)
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(
            return_value=_additive_drift_endpoints()
        )

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        drift_events = [
            e for e in events if e["kind"] == EventKind.DRIFT_DETECTED.value
        ]
        assert len(drift_events) >= 1
        assert drift_events[0]["tool_id"] == "get_users"
        assert "drift" in drift_events[0]["description"].lower()

    @pytest.mark.asyncio
    async def test_repair_plan_from_drift(self, tmp_path: Path) -> None:
        """DriftReport with items -> RepairApplier generates patches and records events."""
        loop = _make_loop(
            tmp_path,
            config=WatchConfig(auto_heal=AutoHealPolicy.SAFE),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        # Additive drift: new endpoint added -> generates SAFE patches
        loop._rediscover_endpoints = AsyncMock(
            return_value=_additive_drift_endpoints()
        )

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        # Should have both drift and repair events
        event_kinds = {e["kind"] for e in events}
        assert EventKind.DRIFT_DETECTED.value in event_kinds
        # With SAFE policy and additive drift, safe patches are auto-applied
        assert EventKind.AUTO_REPAIRED.value in event_kinds

        # State should reflect repairs
        state = loop.get_state()
        assert state.auto_repairs_applied >= 1

    @pytest.mark.asyncio
    async def test_safe_patch_auto_applied(self, tmp_path: Path) -> None:
        """With AutoHealPolicy.SAFE, safe patches are applied; breaking ones queued."""
        loop = _make_loop(
            tmp_path,
            actions=_make_actions("tool_a", "tool_b"),
            risk_tiers=_make_risk_tiers("tool_a", "tool_b"),
            config=WatchConfig(auto_heal=AutoHealPolicy.SAFE),
        )

        # tool_a: additive drift (safe patches)
        # tool_b: breaking drift (approval-required patches)
        loop._prober.probe_due_tools = AsyncMock(
            return_value={
                "tool_a": _schema_changed_result("tool_a"),
                "tool_b": _schema_changed_result("tool_b"),
            }
        )

        async def mock_rediscover(tool_id: str):
            if tool_id == "tool_a":
                return _additive_drift_endpoints()
            return _breaking_drift_endpoints()

        loop._rediscover_endpoints = AsyncMock(side_effect=mock_rediscover)

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        auto_repaired = [
            e for e in events if e["kind"] == EventKind.AUTO_REPAIRED.value
        ]
        approval_queued = [
            e for e in events if e["kind"] == EventKind.APPROVAL_QUEUED.value
        ]

        # tool_a should have auto-repaired events
        tool_a_repaired = [e for e in auto_repaired if e["tool_id"] == "tool_a"]
        assert len(tool_a_repaired) >= 1

        # tool_b should have approval-queued events (breaking changes)
        tool_b_queued = [e for e in approval_queued if e["tool_id"] == "tool_b"]
        assert len(tool_b_queued) >= 1

        state = loop.get_state()
        assert state.auto_repairs_applied >= 1
        assert state.approvals_queued >= 1


# ---------------------------------------------------------------------------
# TestSnapshotOnRepair
# ---------------------------------------------------------------------------


class TestSnapshotOnRepair:
    """Integration tests for snapshot/versioning behavior during repair."""

    @pytest.mark.asyncio
    async def test_snapshot_created_before_repair(self, tmp_path: Path) -> None:
        """When auto-repair runs, tool version is incremented (snapshot marker)."""
        loop = _make_loop(
            tmp_path,
            config=WatchConfig(auto_heal=AutoHealPolicy.SAFE),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(
            return_value=_additive_drift_endpoints()
        )

        initial_state = loop.get_state()
        initial_version = initial_state.tools.get("get_users", ToolReconcileState(tool_id="get_users")).version

        await loop._reconcile_cycle()

        tool = loop.get_state().tools["get_users"]
        # Version should be incremented after repair processing
        assert tool.version > initial_version

        # State file should exist and contain the updated version
        state_file = tmp_path / ".toolwright" / "state" / "reconcile.json"
        assert state_file.exists()
        persisted = json.loads(state_file.read_text())
        assert persisted["tools"]["get_users"]["version"] == tool.version

    @pytest.mark.asyncio
    async def test_rollback_restores_state(self, tmp_path: Path) -> None:
        """After repair, loading a pre-repair snapshot restores original state.

        Simulates rollback by saving state before repair, running repair,
        then verifying we can reconstruct the pre-repair state.
        """
        loop = _make_loop(
            tmp_path,
            config=WatchConfig(auto_heal=AutoHealPolicy.SAFE),
        )

        # First cycle: healthy baseline
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )
        await loop._reconcile_cycle()

        # Capture pre-repair state from disk
        state_file = tmp_path / ".toolwright" / "state" / "reconcile.json"
        pre_repair_json = state_file.read_text()
        pre_repair_state = ReconcileState.model_validate_json(pre_repair_json)

        assert pre_repair_state.tools["get_users"].status == ToolStatus.HEALTHY
        assert pre_repair_state.tools["get_users"].version == 0

        # Second cycle: drift -> repair
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(
            return_value=_additive_drift_endpoints()
        )
        await loop._reconcile_cycle()

        # Post-repair state is different
        post_repair_state = loop.get_state()
        assert post_repair_state.tools["get_users"].version >= 1
        assert post_repair_state.tools["get_users"].status == ToolStatus.DEGRADED

        # Simulate rollback: write pre-repair state back and reload
        state_file.write_text(pre_repair_json)
        loop_restored = _make_loop(tmp_path)
        restored = loop_restored.get_state()

        assert restored.tools["get_users"].status == ToolStatus.HEALTHY
        assert restored.tools["get_users"].version == 0


# ---------------------------------------------------------------------------
# TestReconcileStateTransitions
# ---------------------------------------------------------------------------


class TestReconcileStateTransitions:
    """Integration tests for multi-cycle state transitions."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_state_transitions(self, tmp_path: Path) -> None:
        """UNKNOWN -> HEALTHY -> UNHEALTHY -> HEALTHY lifecycle.

        Verifies that the full state machine works across multiple cycles.
        """
        loop = _make_loop(tmp_path)

        # Initially: tool doesn't exist in state yet (would be UNKNOWN)
        assert "get_users" not in loop.get_state().tools

        # Cycle 1: healthy probe -> HEALTHY
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )
        await loop._reconcile_cycle()
        assert loop.get_state().tools["get_users"].status == ToolStatus.HEALTHY

        # Cycle 2: still healthy -> HEALTHY, consecutive_healthy=2
        await loop._reconcile_cycle()
        tool = loop.get_state().tools["get_users"]
        assert tool.status == ToolStatus.HEALTHY
        assert tool.consecutive_healthy == 2

        # Cycle 3: unhealthy probe -> UNHEALTHY
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _unhealthy_result("get_users")}
        )
        await loop._reconcile_cycle()
        tool = loop.get_state().tools["get_users"]
        assert tool.status == ToolStatus.UNHEALTHY
        assert tool.consecutive_unhealthy == 1
        assert tool.consecutive_healthy == 0

        # Cycle 4: healthy again -> HEALTHY (recovery)
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )
        await loop._reconcile_cycle()
        tool = loop.get_state().tools["get_users"]
        assert tool.status == ToolStatus.HEALTHY
        assert tool.consecutive_healthy == 1
        assert tool.consecutive_unhealthy == 0

        # Verify all 4 cycles tracked
        assert loop.get_state().reconcile_count == 4

        # Verify event log has the full history
        events = loop._event_log.recent()
        kinds = [e["kind"] for e in events]
        assert kinds.count(EventKind.PROBE_HEALTHY.value) == 3
        assert kinds.count(EventKind.PROBE_UNHEALTHY.value) == 1

    @pytest.mark.asyncio
    async def test_reconcile_count_increments(self, tmp_path: Path) -> None:
        """Each cycle increments reconcile_count, even on errors."""
        loop = _make_loop(tmp_path)

        # Cycle 1: healthy
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )
        await loop._reconcile_cycle()
        assert loop.get_state().reconcile_count == 1

        # Cycle 2: error
        loop._prober.probe_due_tools = AsyncMock(
            side_effect=RuntimeError("network failure")
        )
        await loop._reconcile_cycle()
        assert loop.get_state().reconcile_count == 2
        assert loop.get_state().errors == 1

        # Cycle 3: healthy again
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )
        await loop._reconcile_cycle()
        assert loop.get_state().reconcile_count == 3

        # Verify last_full_reconcile is set
        assert loop.get_state().last_full_reconcile is not None

        # Verify state persisted correctly after all cycles
        state_file = tmp_path / ".toolwright" / "state" / "reconcile.json"
        data = json.loads(state_file.read_text())
        assert data["reconcile_count"] == 3
        assert data["errors"] == 1
