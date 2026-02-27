"""Tests for HealthProber (scheduling + backoff wrapper around HealthChecker)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolwright.core.health.checker import FailureClass, HealthResult
from toolwright.core.reconcile.prober import HealthProber
from toolwright.models.reconcile import (
    ToolReconcileState,
    ToolStatus,
    WatchConfig,
)


def _make_state(
    tool_id: str = "get_users",
    *,
    last_probe_at: str | None = None,
    consecutive_unhealthy: int = 0,
    status: ToolStatus = ToolStatus.UNKNOWN,
) -> ToolReconcileState:
    return ToolReconcileState(
        tool_id=tool_id,
        last_probe_at=last_probe_at,
        consecutive_unhealthy=consecutive_unhealthy,
        status=status,
    )


def _healthy_result(tool_id: str = "get_users") -> HealthResult:
    return HealthResult(tool_id=tool_id, healthy=True, status_code=200, response_time_ms=50.0)


def _unhealthy_result(
    tool_id: str = "get_users",
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


class TestShouldProbe:
    """Tests for should_probe scheduling logic."""

    def test_should_probe_when_never_probed(self):
        """Tool with no last_probe_at should always be probed."""
        prober = HealthProber(checker=MagicMock(), config=WatchConfig())
        state = _make_state(last_probe_at=None)
        assert prober.should_probe(state, "medium") is True

    def test_should_probe_when_interval_elapsed(self):
        """Tool should be probed when interval has elapsed."""
        config = WatchConfig(probe_intervals={"medium": 600})
        prober = HealthProber(checker=MagicMock(), config=config)
        # Last probed 700 seconds ago (> 600 interval)
        past = datetime.now(UTC) - timedelta(seconds=700)
        state = _make_state(last_probe_at=past.isoformat())
        assert prober.should_probe(state, "medium") is True

    def test_should_not_probe_when_interval_not_elapsed(self):
        """Tool should NOT be probed when interval hasn't elapsed."""
        config = WatchConfig(probe_intervals={"medium": 600})
        prober = HealthProber(checker=MagicMock(), config=config)
        # Last probed 100 seconds ago (< 600 interval)
        recent = datetime.now(UTC) - timedelta(seconds=100)
        state = _make_state(last_probe_at=recent.isoformat())
        assert prober.should_probe(state, "medium") is False

    def test_should_probe_respects_risk_tier(self):
        """Critical tools should be probed more frequently."""
        config = WatchConfig(probe_intervals={"critical": 120, "low": 1800})
        prober = HealthProber(checker=MagicMock(), config=config)
        # Last probed 200 seconds ago
        past = datetime.now(UTC) - timedelta(seconds=200)
        state = _make_state(last_probe_at=past.isoformat())
        # 200 > 120 (critical) → should probe
        assert prober.should_probe(state, "critical") is True
        # 200 < 1800 (low) → should not probe
        assert prober.should_probe(state, "low") is False

    def test_backoff_increases_interval_for_unhealthy(self):
        """Unhealthy tools should have exponentially longer intervals."""
        config = WatchConfig(
            probe_intervals={"medium": 600},
            unhealthy_backoff_multiplier=2.0,
            unhealthy_backoff_max=3600,
        )
        prober = HealthProber(checker=MagicMock(), config=config)
        # Last probed 700 seconds ago, but tool has 1 consecutive unhealthy
        # Effective interval: 600 * 2^1 = 1200 > 700 → should NOT probe
        past = datetime.now(UTC) - timedelta(seconds=700)
        state = _make_state(
            last_probe_at=past.isoformat(),
            consecutive_unhealthy=1,
            status=ToolStatus.UNHEALTHY,
        )
        assert prober.should_probe(state, "medium") is False

    def test_backoff_caps_at_max(self):
        """Backoff should not exceed unhealthy_backoff_max."""
        config = WatchConfig(
            probe_intervals={"medium": 600},
            unhealthy_backoff_multiplier=2.0,
            unhealthy_backoff_max=3600,
        )
        prober = HealthProber(checker=MagicMock(), config=config)
        # 10 consecutive unhealthy: 600 * 2^10 = 614400, capped to 3600
        past = datetime.now(UTC) - timedelta(seconds=3700)
        state = _make_state(
            last_probe_at=past.isoformat(),
            consecutive_unhealthy=10,
            status=ToolStatus.UNHEALTHY,
        )
        assert prober.should_probe(state, "medium") is True

    def test_backoff_does_not_apply_to_healthy_tools(self):
        """Healthy tools should not have backoff applied."""
        config = WatchConfig(probe_intervals={"medium": 600})
        prober = HealthProber(checker=MagicMock(), config=config)
        past = datetime.now(UTC) - timedelta(seconds=700)
        # Consecutive unhealthy > 0 but status is HEALTHY → no backoff
        state = _make_state(
            last_probe_at=past.isoformat(),
            consecutive_unhealthy=3,
            status=ToolStatus.HEALTHY,
        )
        assert prober.should_probe(state, "medium") is True


class TestProbeTool:
    """Tests for probe_tool delegation."""

    @pytest.mark.asyncio
    async def test_probe_tool_delegates_to_checker(self):
        """probe_tool should delegate to HealthChecker.check_tool."""
        mock_checker = AsyncMock()
        expected = _healthy_result()
        mock_checker.check_tool.return_value = expected

        prober = HealthProber(checker=mock_checker, config=WatchConfig())
        action = {"name": "get_users", "method": "GET", "host": "api.example.com", "path": "/users"}
        result = await prober.probe_tool(action)

        assert result is expected
        mock_checker.check_tool.assert_awaited_once_with(action)

    @pytest.mark.asyncio
    async def test_probe_tool_returns_unhealthy_on_exception(self):
        """probe_tool should return unhealthy result if checker raises."""
        mock_checker = AsyncMock()
        mock_checker.check_tool.side_effect = Exception("Connection failed")

        prober = HealthProber(checker=mock_checker, config=WatchConfig())
        action = {"name": "get_users", "method": "GET", "host": "api.example.com", "path": "/users"}
        result = await prober.probe_tool(action)

        assert result.healthy is False
        assert result.tool_id == "get_users"
        assert result.failure_class == FailureClass.UNKNOWN
        assert "Connection failed" in (result.error_message or "")


class TestProbeDueTools:
    """Tests for probe_due_tools with concurrency."""

    @pytest.mark.asyncio
    async def test_probes_only_due_tools(self):
        """probe_due_tools should only probe tools that are due."""
        mock_checker = AsyncMock()
        mock_checker.check_tool.return_value = _healthy_result("tool_due")

        config = WatchConfig(probe_intervals={"medium": 600})
        prober = HealthProber(checker=mock_checker, config=config)

        actions = [
            {"name": "tool_due", "method": "GET", "host": "api.example.com", "path": "/due"},
            {"name": "tool_not_due", "method": "GET", "host": "api.example.com", "path": "/not_due"},
        ]
        states = {
            "tool_due": _make_state("tool_due", last_probe_at=None),
            "tool_not_due": _make_state(
                "tool_not_due",
                last_probe_at=datetime.now(UTC).isoformat(),
            ),
        }
        risk_tiers = {"tool_due": "medium", "tool_not_due": "medium"}

        results = await prober.probe_due_tools(actions, states, risk_tiers)

        assert "tool_due" in results
        assert "tool_not_due" not in results

    @pytest.mark.asyncio
    async def test_respects_max_concurrent(self):
        """probe_due_tools should limit concurrency."""
        call_count = 0
        max_concurrent_seen = 0
        lock = asyncio.Lock()

        async def slow_check(action: dict) -> HealthResult:
            nonlocal call_count, max_concurrent_seen
            async with lock:
                call_count += 1
                current = call_count
            if current > max_concurrent_seen:
                max_concurrent_seen = current
            await asyncio.sleep(0.05)
            async with lock:
                call_count -= 1
            return _healthy_result(action["name"])

        mock_checker = AsyncMock()
        mock_checker.check_tool.side_effect = slow_check

        config = WatchConfig(max_concurrent_probes=2)
        prober = HealthProber(checker=mock_checker, config=config)

        actions = [
            {"name": f"tool_{i}", "method": "GET", "host": "api.example.com", "path": f"/t{i}"}
            for i in range(5)
        ]
        states = {f"tool_{i}": _make_state(f"tool_{i}", last_probe_at=None) for i in range(5)}
        risk_tiers = {f"tool_{i}": "medium" for i in range(5)}

        results = await prober.probe_due_tools(actions, states, risk_tiers)

        assert len(results) == 5
        # max_concurrent_seen should not exceed config limit
        assert max_concurrent_seen <= 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_tools_due(self):
        """probe_due_tools should return empty dict when nothing is due."""
        mock_checker = AsyncMock()
        config = WatchConfig(probe_intervals={"medium": 600})
        prober = HealthProber(checker=mock_checker, config=config)

        actions = [
            {"name": "tool_a", "method": "GET", "host": "api.example.com", "path": "/a"},
        ]
        states = {
            "tool_a": _make_state(
                "tool_a",
                last_probe_at=datetime.now(UTC).isoformat(),
            ),
        }
        risk_tiers = {"tool_a": "medium"}

        results = await prober.probe_due_tools(actions, states, risk_tiers)
        assert results == {}
        mock_checker.check_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_default_risk_tier_when_missing(self):
        """Tools without a risk tier should use 'medium' as default."""
        mock_checker = AsyncMock()
        mock_checker.check_tool.return_value = _healthy_result("tool_no_tier")

        config = WatchConfig(probe_intervals={"medium": 600})
        prober = HealthProber(checker=mock_checker, config=config)

        actions = [
            {"name": "tool_no_tier", "method": "GET", "host": "api.example.com", "path": "/x"},
        ]
        states = {
            "tool_no_tier": _make_state("tool_no_tier", last_probe_at=None),
        }
        # Empty risk_tiers dict — should default to "medium"
        risk_tiers: dict[str, str] = {}

        results = await prober.probe_due_tools(actions, states, risk_tiers)
        assert "tool_no_tier" in results

    @pytest.mark.asyncio
    async def test_creates_default_state_for_unknown_tools(self):
        """Tools not in states dict should get a default state (always probed)."""
        mock_checker = AsyncMock()
        mock_checker.check_tool.return_value = _healthy_result("new_tool")

        prober = HealthProber(checker=mock_checker, config=WatchConfig())

        actions = [
            {"name": "new_tool", "method": "GET", "host": "api.example.com", "path": "/new"},
        ]
        # Empty states dict — tool not yet tracked
        states: dict[str, ToolReconcileState] = {}
        risk_tiers = {"new_tool": "medium"}

        results = await prober.probe_due_tools(actions, states, risk_tiers)
        assert "new_tool" in results
