"""Tests for repair retry budget — per-tool failure tracking and escalation.

After 3 consecutive failed repairs in a 1-hour window, auto-healing should
be suspended for that tool with a WARNING log.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from toolwright.models.reconcile import (
    EventKind,
    ReconcileState,
    ToolReconcileState,
    ToolStatus,
)


class TestToolReconcileStateRepairFields:
    """ToolReconcileState must track consecutive repair failures."""

    def test_has_consecutive_repair_failures_field(self) -> None:
        state = ToolReconcileState(tool_id="t1")
        assert hasattr(state, "consecutive_repair_failures")
        assert state.consecutive_repair_failures == 0

    def test_has_repair_suspended_field(self) -> None:
        state = ToolReconcileState(tool_id="t1")
        assert hasattr(state, "repair_suspended")
        assert state.repair_suspended is False

    def test_has_first_failure_at_field(self) -> None:
        state = ToolReconcileState(tool_id="t1")
        assert hasattr(state, "first_failure_at")
        assert state.first_failure_at is None


class TestRepairRetryBudget:
    """Reconciliation loop must suspend auto-heal after 3 consecutive failures."""

    def _make_loop(self, tool_state: ToolReconcileState):
        """Create a ReconcileLoop with minimal mocks for repair testing."""
        from toolwright.core.reconcile.loop import ReconcileLoop
        from toolwright.models.reconcile import AutoHealPolicy, ReconcileState, WatchConfig

        state = ReconcileState(tools={tool_state.tool_id: tool_state})
        config = WatchConfig(auto_heal=AutoHealPolicy.ALL)
        loop = ReconcileLoop.__new__(ReconcileLoop)
        loop._state = state
        loop._config = config
        loop._project_root = MagicMock()
        loop._auto_heal = config.auto_heal
        loop._action_by_tool = {}
        loop._event_log = MagicMock()
        return loop

    def test_repair_failure_increments_counter(self) -> None:
        """A failed repair attempt must increment consecutive_repair_failures."""
        ts = ToolReconcileState(tool_id="t1", status=ToolStatus.DEGRADED)
        loop = self._make_loop(ts)

        # Simulate a repair where all patches fail (not applied)
        from toolwright.core.repair.applier import ApplyResult, PatchResult

        mock_result = ApplyResult(
            total=1,
            applied=0,
            results=[PatchResult(patch_id="p1", applied=False, reason="failed")],
        )

        with patch("toolwright.core.reconcile.loop.RepairApplier") as MockApplier:
            MockApplier.return_value.apply_plan.return_value = mock_result
            from toolwright.models.drift import DriftReport, DriftItem, DriftType, DriftSeverity
            drift = DriftReport(
                id="dr1", total_drifts=1, breaking_count=0, risk_count=0,
                drifts=[DriftItem(id="d1", type=DriftType.ADDITIVE, severity=DriftSeverity.WARNING, title="t", description="d")],
            )
            loop._handle_repair("t1", drift)

        assert ts.consecutive_repair_failures >= 1

    def test_successful_repair_resets_counter(self) -> None:
        """A successful repair must reset consecutive_repair_failures to 0."""
        ts = ToolReconcileState(
            tool_id="t1", status=ToolStatus.DEGRADED,
            consecutive_repair_failures=2,
        )
        loop = self._make_loop(ts)

        from toolwright.core.repair.applier import ApplyResult, PatchResult

        mock_result = ApplyResult(
            total=1,
            applied=1,
            results=[PatchResult(patch_id="p1", applied=True, reason="ok")],
        )

        with patch("toolwright.core.reconcile.loop.RepairApplier") as MockApplier:
            MockApplier.return_value.apply_plan.return_value = mock_result
            from toolwright.models.drift import DriftReport, DriftItem, DriftType, DriftSeverity
            drift = DriftReport(
                id="dr1", total_drifts=1, breaking_count=0, risk_count=0,
                drifts=[DriftItem(id="d1", type=DriftType.ADDITIVE, severity=DriftSeverity.WARNING, title="t", description="d")],
            )
            loop._handle_repair("t1", drift)

        assert ts.consecutive_repair_failures == 0
        assert ts.repair_suspended is False

    def test_suspends_after_three_failures(self) -> None:
        """After 3 consecutive failures in 1 hour, repair_suspended must be True."""
        ts = ToolReconcileState(
            tool_id="t1", status=ToolStatus.DEGRADED,
            consecutive_repair_failures=2,
            first_failure_at=time.time(),
        )
        loop = self._make_loop(ts)

        from toolwright.core.repair.applier import ApplyResult, PatchResult

        mock_result = ApplyResult(
            total=1,
            applied=0,
            results=[PatchResult(patch_id="p1", applied=False, reason="failed")],
        )

        with patch("toolwright.core.reconcile.loop.RepairApplier") as MockApplier:
            MockApplier.return_value.apply_plan.return_value = mock_result
            from toolwright.models.drift import DriftReport, DriftItem, DriftType, DriftSeverity
            drift = DriftReport(
                id="dr1", total_drifts=1, breaking_count=0, risk_count=0,
                drifts=[DriftItem(id="d1", type=DriftType.ADDITIVE, severity=DriftSeverity.WARNING, title="t", description="d")],
            )
            loop._handle_repair("t1", drift)

        assert ts.consecutive_repair_failures == 3
        assert ts.repair_suspended is True

    def test_suspended_tool_skips_repair(self) -> None:
        """If repair_suspended is True, _handle_repair must return early."""
        ts = ToolReconcileState(
            tool_id="t1", status=ToolStatus.DEGRADED,
            repair_suspended=True,
            consecutive_repair_failures=3,
        )
        loop = self._make_loop(ts)

        with patch("toolwright.core.reconcile.loop.RepairApplier") as MockApplier:
            from toolwright.models.drift import DriftReport, DriftItem, DriftType, DriftSeverity
            drift = DriftReport(
                id="dr1", total_drifts=1, breaking_count=0, risk_count=0,
                drifts=[DriftItem(id="d1", type=DriftType.ADDITIVE, severity=DriftSeverity.WARNING, title="t", description="d")],
            )
            loop._handle_repair("t1", drift)
            MockApplier.assert_not_called()

    def test_failure_window_resets_after_one_hour(self) -> None:
        """If first failure was >1 hour ago, counter resets on next failure."""
        ts = ToolReconcileState(
            tool_id="t1", status=ToolStatus.DEGRADED,
            consecutive_repair_failures=2,
            first_failure_at=time.time() - 3700,  # >1 hour ago
        )
        loop = self._make_loop(ts)

        from toolwright.core.repair.applier import ApplyResult, PatchResult

        mock_result = ApplyResult(
            total=1,
            applied=0,
            results=[PatchResult(patch_id="p1", applied=False, reason="failed")],
        )

        with patch("toolwright.core.reconcile.loop.RepairApplier") as MockApplier:
            MockApplier.return_value.apply_plan.return_value = mock_result
            from toolwright.models.drift import DriftReport, DriftItem, DriftType, DriftSeverity
            drift = DriftReport(
                id="dr1", total_drifts=1, breaking_count=0, risk_count=0,
                drifts=[DriftItem(id="d1", type=DriftType.ADDITIVE, severity=DriftSeverity.WARNING, title="t", description="d")],
            )
            loop._handle_repair("t1", drift)

        # Window expired, counter should have reset to 1 (this failure)
        assert ts.consecutive_repair_failures == 1
        assert ts.repair_suspended is False

    def test_suspension_warning_logged(self, caplog) -> None:
        """Suspension must log a WARNING with repair plan instructions."""
        import logging

        ts = ToolReconcileState(
            tool_id="t1", status=ToolStatus.DEGRADED,
            consecutive_repair_failures=2,
            first_failure_at=time.time(),
        )
        loop = self._make_loop(ts)

        from toolwright.core.repair.applier import ApplyResult, PatchResult

        mock_result = ApplyResult(
            total=1,
            applied=0,
            results=[PatchResult(patch_id="p1", applied=False, reason="failed")],
        )

        with (
            patch("toolwright.core.reconcile.loop.RepairApplier") as MockApplier,
            caplog.at_level(logging.WARNING),
        ):
            MockApplier.return_value.apply_plan.return_value = mock_result
            from toolwright.models.drift import DriftReport, DriftItem, DriftType, DriftSeverity
            drift = DriftReport(
                id="dr1", total_drifts=1, breaking_count=0, risk_count=0,
                drifts=[DriftItem(id="d1", type=DriftType.ADDITIVE, severity=DriftSeverity.WARNING, title="t", description="d")],
            )
            loop._handle_repair("t1", drift)

        assert any("Auto-heal suspended" in r.message and "t1" in r.message for r in caplog.records)
        assert any("toolwright repair plan" in r.message for r in caplog.records)
