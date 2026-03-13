"""Tests for ReconcileLoop (probe-only async reconciliation loop)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolwright.core.health.checker import FailureClass, HealthResult
from toolwright.core.reconcile.loop import ReconcileLoop
from toolwright.models.reconcile import (
    AutoHealPolicy,
    EventKind,
    ReconcileState,
    ToolReconcileState,
    ToolStatus,
    WatchConfig,
)


def _healthy_result(tool_id: str) -> HealthResult:
    return HealthResult(tool_id=tool_id, healthy=True, status_code=200, response_time_ms=50.0)


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


def _make_actions(*tool_ids: str) -> list[dict]:
    return [
        {"name": tid, "method": "GET", "host": "api.example.com", "path": f"/{tid}"}
        for tid in tool_ids
    ]


def _make_risk_tiers(*tool_ids: str) -> dict[str, str]:
    return {tid: "medium" for tid in tool_ids}


class TestReconcileLoopInit:
    """Tests for ReconcileLoop initialization."""

    def test_creates_with_defaults(self, tmp_path):
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        assert loop.config.auto_heal.value == "safe"
        state = loop.get_state()
        assert isinstance(state, ReconcileState)
        assert state.reconcile_count == 0

    def test_creates_with_custom_config(self, tmp_path):
        config = WatchConfig(max_concurrent_probes=10)
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            config=config,
        )
        assert loop.config.max_concurrent_probes == 10


class TestReconcileCycle:
    """Tests for a single reconciliation cycle."""

    @pytest.mark.asyncio
    async def test_healthy_probe_updates_state(self, tmp_path):
        """Healthy probe should update tool state to HEALTHY."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        # Mock the prober to return healthy
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        state = loop.get_state()
        assert state.reconcile_count == 1
        tool_state = state.tools["get_users"]
        assert tool_state.status == ToolStatus.HEALTHY
        assert tool_state.consecutive_healthy == 1
        assert tool_state.consecutive_unhealthy == 0
        assert tool_state.last_probe_at is not None

    @pytest.mark.asyncio
    async def test_unhealthy_probe_updates_state(self, tmp_path):
        """Unhealthy probe should update tool state to UNHEALTHY."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _unhealthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        state = loop.get_state()
        tool_state = state.tools["get_users"]
        assert tool_state.status == ToolStatus.UNHEALTHY
        assert tool_state.consecutive_unhealthy == 1
        assert tool_state.consecutive_healthy == 0
        assert tool_state.failure_class == FailureClass.SERVER_ERROR.value

    @pytest.mark.asyncio
    async def test_consecutive_healthy_increments(self, tmp_path):
        """Multiple healthy probes should increment consecutive_healthy."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        await loop._reconcile_cycle()
        await loop._reconcile_cycle()
        await loop._reconcile_cycle()

        tool_state = loop.get_state().tools["get_users"]
        assert tool_state.consecutive_healthy == 3

    @pytest.mark.asyncio
    async def test_unhealthy_resets_consecutive_healthy(self, tmp_path):
        """Unhealthy probe after healthy should reset consecutive_healthy."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        # First: healthy
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )
        await loop._reconcile_cycle()
        assert loop.get_state().tools["get_users"].consecutive_healthy == 1

        # Then: unhealthy
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _unhealthy_result("get_users")}
        )
        await loop._reconcile_cycle()
        tool_state = loop.get_state().tools["get_users"]
        assert tool_state.consecutive_healthy == 0
        assert tool_state.consecutive_unhealthy == 1

    @pytest.mark.asyncio
    async def test_records_events(self, tmp_path):
        """Reconciliation cycle should record events in the event log."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        assert len(events) >= 1
        probe_events = [e for e in events if e["kind"] == EventKind.PROBE_HEALTHY.value]
        assert len(probe_events) == 1
        assert probe_events[0]["tool_id"] == "get_users"

    @pytest.mark.asyncio
    async def test_records_unhealthy_event(self, tmp_path):
        """Unhealthy probe should record PROBE_UNHEALTHY event."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _unhealthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        unhealthy_events = [e for e in events if e["kind"] == EventKind.PROBE_UNHEALTHY.value]
        assert len(unhealthy_events) == 1

    @pytest.mark.asyncio
    async def test_persists_state_to_disk(self, tmp_path):
        """State should be persisted to reconcile.json after each cycle."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        state_file = tmp_path / ".toolwright" / "state" / "reconcile.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["reconcile_count"] == 1
        assert "get_users" in data["tools"]

    @pytest.mark.asyncio
    async def test_loads_persisted_state(self, tmp_path):
        """Loop should load state from disk on init if it exists."""
        state_dir = tmp_path / ".toolwright" / "state"
        state_dir.mkdir(parents=True)
        state = ReconcileState(
            reconcile_count=5,
            tools={
                "get_users": ToolReconcileState(
                    tool_id="get_users",
                    status=ToolStatus.HEALTHY,
                    consecutive_healthy=5,
                ),
            },
        )
        (state_dir / "reconcile.json").write_text(state.model_dump_json())

        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )

        loaded = loop.get_state()
        assert loaded.reconcile_count == 5
        assert loaded.tools["get_users"].consecutive_healthy == 5


class TestReconcileLoopFailClosed:
    """Tests for fail-closed behavior."""

    @pytest.mark.asyncio
    async def test_exception_in_cycle_does_not_crash(self, tmp_path):
        """An exception during reconciliation should not crash the loop."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        # Make prober raise
        loop._prober.probe_due_tools = AsyncMock(side_effect=RuntimeError("boom"))

        # Should not raise
        await loop._reconcile_cycle()

        state = loop.get_state()
        assert state.errors == 1
        # reconcile_count should still increment
        assert state.reconcile_count == 1

    @pytest.mark.asyncio
    async def test_multiple_errors_accumulate(self, tmp_path):
        """Error count should accumulate across cycles."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(side_effect=RuntimeError("boom"))

        await loop._reconcile_cycle()
        await loop._reconcile_cycle()

        assert loop.get_state().errors == 2


class TestReconcileLoopStartStop:
    """Tests for async start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, tmp_path):
        """Loop should start, run at least one cycle, and stop cleanly."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            config=WatchConfig(probe_intervals={"medium": 1}),  # Fast for testing
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        # Start loop as background task
        await loop.start()
        # Give it a moment to run at least one cycle
        await asyncio.sleep(0.2)
        await loop.stop()

        assert loop.get_state().reconcile_count >= 1

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self, tmp_path):
        """Stopping a loop that was never started should be harmless."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        # Should not raise
        await loop.stop()

    @pytest.mark.asyncio
    async def test_is_running_property(self, tmp_path):
        """is_running should reflect loop state."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            config=WatchConfig(probe_intervals={"medium": 1}),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        assert loop.is_running is False
        await loop.start()
        assert loop.is_running is True
        await loop.stop()
        assert loop.is_running is False


class TestReconcileLoopMultiTool:
    """Tests for multi-tool reconciliation."""

    @pytest.mark.asyncio
    async def test_multiple_tools_tracked(self, tmp_path):
        """Multiple tools should each get their own state."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users", "create_issue"),
            risk_tiers=_make_risk_tiers("get_users", "create_issue"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={
                "get_users": _healthy_result("get_users"),
                "create_issue": _unhealthy_result("create_issue"),
            }
        )

        await loop._reconcile_cycle()

        state = loop.get_state()
        assert state.tools["get_users"].status == ToolStatus.HEALTHY
        assert state.tools["create_issue"].status == ToolStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_no_tools_due_is_harmless(self, tmp_path):
        """If no tools are due for probing, cycle should be a no-op."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        # Return empty — no tools were due
        loop._prober.probe_due_tools = AsyncMock(return_value={})

        await loop._reconcile_cycle()

        state = loop.get_state()
        assert state.reconcile_count == 1
        assert "get_users" not in state.tools


class TestReconcileLoopCircuitBreaker:
    """Tests for circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_records_failure_in_breaker(self, tmp_path):
        """Unhealthy probe should record failure in circuit breaker if provided."""
        mock_breaker_registry = MagicMock()
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            breaker_registry=mock_breaker_registry,
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _unhealthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        mock_breaker_registry.record_failure.assert_called_once_with(
            "get_users", "Internal Server Error"
        )

    @pytest.mark.asyncio
    async def test_records_success_in_breaker(self, tmp_path):
        """Healthy probe should record success in circuit breaker if provided."""
        mock_breaker_registry = MagicMock()
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            breaker_registry=mock_breaker_registry,
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        await loop._reconcile_cycle()

        mock_breaker_registry.record_success.assert_called_once_with("get_users")

    @pytest.mark.asyncio
    async def test_no_breaker_is_fine(self, tmp_path):
        """Loop should work without a circuit breaker registry."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )

        # Should not raise
        await loop._reconcile_cycle()
        assert loop.get_state().tools["get_users"].status == ToolStatus.HEALTHY


# ---------------------------------------------------------------------------
# Drift detection integration (Task 9.10)
# ---------------------------------------------------------------------------


def _schema_changed_result(tool_id: str) -> HealthResult:
    return HealthResult(
        tool_id=tool_id,
        healthy=False,
        failure_class=FailureClass.SCHEMA_CHANGED,
        status_code=200,
        response_time_ms=80.0,
        error_message="Schema mismatch detected",
    )


class TestReconcileLoopDriftDetection:
    """Tests for drift detection integrated into the reconcile cycle."""

    @pytest.mark.asyncio
    async def test_schema_changed_triggers_drift_check(self, tmp_path):
        """SCHEMA_CHANGED failure should trigger drift detection."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        # Mock rediscovery to return None (no spec found)
        loop._rediscover_endpoints = AsyncMock(return_value=None)

        await loop._reconcile_cycle()

        # Rediscovery should have been called
        loop._rediscover_endpoints.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_error_does_not_trigger_drift_check(self, tmp_path):
        """Non-SCHEMA_CHANGED failures should NOT trigger drift detection."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _unhealthy_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(return_value=None)

        await loop._reconcile_cycle()

        # Should NOT have been called
        loop._rediscover_endpoints.assert_not_called()

    @pytest.mark.asyncio
    async def test_rediscovery_failure_sets_degraded(self, tmp_path):
        """Rediscovery failure should set DEGRADED status, not UNHEALTHY."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(return_value=None)

        await loop._reconcile_cycle()

        tool_state = loop.get_state().tools["get_users"]
        assert tool_state.status == ToolStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_drift_detected_records_event(self, tmp_path):
        """When drift is detected, a DRIFT_DETECTED event should be recorded."""
        from toolwright.models.endpoint import Endpoint

        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        # Return endpoints that differ from the toolpack
        new_endpoints = [
            Endpoint(
                method="GET",
                path="/users",
                host="api.example.com",
            ),
            Endpoint(
                method="POST",
                path="/users/new",
                host="api.example.com",
            ),
        ]
        loop._rediscover_endpoints = AsyncMock(return_value=new_endpoints)

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        drift_events = [
            e for e in events if e["kind"] == EventKind.DRIFT_DETECTED.value
        ]
        assert len(drift_events) >= 1

    @pytest.mark.asyncio
    async def test_drift_with_changes_sets_degraded(self, tmp_path):
        """Drift with actual changes should set DEGRADED."""
        from toolwright.models.endpoint import Endpoint

        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        # Rediscovery returns new endpoint that doesn't exist in toolpack
        new_endpoints = [
            Endpoint(method="POST", path="/users/new", host="api.example.com"),
        ]
        loop._rediscover_endpoints = AsyncMock(return_value=new_endpoints)

        await loop._reconcile_cycle()

        tool_state = loop.get_state().tools["get_users"]
        assert tool_state.status == ToolStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_rediscovery_exception_does_not_crash(self, tmp_path):
        """Rediscovery exception should be caught (fail-closed)."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(
            side_effect=RuntimeError("network boom")
        )

        # Should not raise
        await loop._reconcile_cycle()

        tool_state = loop.get_state().tools["get_users"]
        assert tool_state.status == ToolStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_healthy_probe_does_not_trigger_drift(self, tmp_path):
        """Healthy probes should never trigger drift detection."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _healthy_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(return_value=None)

        await loop._reconcile_cycle()

        loop._rediscover_endpoints.assert_not_called()


# ---------------------------------------------------------------------------
# Auto-repair integration (Task 9.16)
# ---------------------------------------------------------------------------


def _additive_drift_endpoints() -> list:
    """Return endpoints that produce additive-only drift (new endpoint added)."""
    from toolwright.models.endpoint import Endpoint

    return [
        # Keep the baseline endpoint
        Endpoint(method="GET", path="/get_users", host="api.example.com"),
        # Add a new read-only endpoint (additive)
        Endpoint(method="GET", path="/get_users/search", host="api.example.com"),
    ]


def _breaking_drift_endpoints() -> list:
    """Return endpoints that produce breaking drift (baseline removed)."""
    from toolwright.models.endpoint import Endpoint

    return [
        # Baseline endpoint is gone — only a new one exists
        Endpoint(method="POST", path="/users/v2", host="api.example.com"),
    ]


class TestReconcileLoopAutoRepair:
    """Tests for auto-repair wired into the reconcile loop."""

    @pytest.mark.asyncio
    async def test_safe_patches_auto_applied_when_safe_policy(self, tmp_path):
        """Additive drift under SAFE policy should produce AUTO_REPAIRED events."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            config=WatchConfig(auto_heal=AutoHealPolicy.SAFE),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(
            return_value=_additive_drift_endpoints()
        )

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        auto_repaired = [
            e for e in events if e["kind"] == EventKind.AUTO_REPAIRED.value
        ]
        assert len(auto_repaired) >= 1

    @pytest.mark.asyncio
    async def test_no_patches_applied_when_off_policy(self, tmp_path):
        """OFF policy should produce no AUTO_REPAIRED events even with drift."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            config=WatchConfig(auto_heal=AutoHealPolicy.OFF),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(
            return_value=_additive_drift_endpoints()
        )

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        auto_repaired = [
            e for e in events if e["kind"] == EventKind.AUTO_REPAIRED.value
        ]
        assert len(auto_repaired) == 0

    @pytest.mark.asyncio
    async def test_breaking_changes_queued_for_approval(self, tmp_path):
        """Breaking changes under SAFE policy should produce APPROVAL_QUEUED events."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            config=WatchConfig(auto_heal=AutoHealPolicy.SAFE),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(
            return_value=_breaking_drift_endpoints()
        )

        await loop._reconcile_cycle()

        events = loop._event_log.recent()
        approval_queued = [
            e for e in events if e["kind"] == EventKind.APPROVAL_QUEUED.value
        ]
        assert len(approval_queued) >= 1

    @pytest.mark.asyncio
    async def test_repair_updates_tool_version(self, tmp_path):
        """After repair, tool version should be incremented."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=_make_actions("get_users"),
            risk_tiers=_make_risk_tiers("get_users"),
            config=WatchConfig(auto_heal=AutoHealPolicy.SAFE),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={"get_users": _schema_changed_result("get_users")}
        )
        loop._rediscover_endpoints = AsyncMock(
            return_value=_additive_drift_endpoints()
        )

        await loop._reconcile_cycle()

        tool_state = loop.get_state().tools["get_users"]
        assert tool_state.version >= 1
