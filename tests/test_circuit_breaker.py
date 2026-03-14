"""Tests for the KILL pillar circuit breaker.

Tests the circuit breaker state machine, registry, persistence,
and CLI-driven kill/enable operations.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from toolwright.core.kill.breaker import (
    BreakerState,
    CircuitBreakerRegistry,
    ToolCircuitBreaker,
)

# ---------------------------------------------------------------------------
# Tests: BreakerState enum
# ---------------------------------------------------------------------------


class TestBreakerState:
    """Test the BreakerState enum values."""

    def test_states_exist(self):
        assert BreakerState.CLOSED == "closed"
        assert BreakerState.OPEN == "open"
        assert BreakerState.HALF_OPEN == "half_open"


# ---------------------------------------------------------------------------
# Tests: ToolCircuitBreaker model
# ---------------------------------------------------------------------------


class TestToolCircuitBreaker:
    """Test the ToolCircuitBreaker Pydantic model."""

    def test_default_construction(self):
        breaker = ToolCircuitBreaker(tool_id="test_tool")
        assert breaker.tool_id == "test_tool"
        assert breaker.state == BreakerState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0
        assert breaker.failure_threshold == 5
        assert breaker.recovery_timeout_seconds == 60
        assert breaker.success_threshold == 3
        assert breaker.manual_override is None

    def test_custom_thresholds(self):
        breaker = ToolCircuitBreaker(
            tool_id="search",
            failure_threshold=3,
            recovery_timeout_seconds=30,
            success_threshold=2,
        )
        assert breaker.failure_threshold == 3
        assert breaker.recovery_timeout_seconds == 30
        assert breaker.success_threshold == 2

    def test_serialization_roundtrip(self):
        breaker = ToolCircuitBreaker(
            tool_id="test_tool",
            state=BreakerState.OPEN,
            failure_count=3,
        )
        data = breaker.model_dump(mode="json")
        restored = ToolCircuitBreaker.model_validate(data)
        assert restored.tool_id == "test_tool"
        assert restored.state == BreakerState.OPEN
        assert restored.failure_count == 3


# ---------------------------------------------------------------------------
# Tests: CircuitBreakerRegistry - should_allow
# ---------------------------------------------------------------------------


class TestRegistryShouldAllow:
    """Test the should_allow method."""

    def test_unknown_tool_allowed(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        allowed, reason = reg.should_allow("unknown_tool")
        assert allowed is True
        assert reason == ""

    def test_closed_breaker_allowed(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg._breakers["tool_a"] = ToolCircuitBreaker(
            tool_id="tool_a", state=BreakerState.CLOSED
        )
        allowed, reason = reg.should_allow("tool_a")
        assert allowed is True

    def test_open_breaker_blocked(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg._breakers["tool_a"] = ToolCircuitBreaker(
            tool_id="tool_a",
            state=BreakerState.OPEN,
            last_failure_time=time.time(),
        )
        allowed, reason = reg.should_allow("tool_a")
        assert allowed is False
        assert "open" in reason.lower() or "circuit" in reason.lower()

    def test_open_breaker_transitions_to_half_open_after_timeout(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg._breakers["tool_a"] = ToolCircuitBreaker(
            tool_id="tool_a",
            state=BreakerState.OPEN,
            last_failure_time=time.time() - 120,  # expired
            recovery_timeout_seconds=60,
        )
        allowed, reason = reg.should_allow("tool_a")
        assert allowed is True
        assert reg._breakers["tool_a"].state == BreakerState.HALF_OPEN

    def test_half_open_allows_probe(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg._breakers["tool_a"] = ToolCircuitBreaker(
            tool_id="tool_a", state=BreakerState.HALF_OPEN
        )
        allowed, reason = reg.should_allow("tool_a")
        assert allowed is True


# ---------------------------------------------------------------------------
# Tests: CircuitBreakerRegistry - record_success / record_failure
# ---------------------------------------------------------------------------


class TestRegistryRecordEvents:
    """Test recording successes and failures."""

    def test_record_failure_increments_count(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg.record_failure("tool_a", "timeout")
        assert reg._breakers["tool_a"].failure_count == 1
        assert reg._breakers["tool_a"].state == BreakerState.CLOSED

    def test_failures_at_threshold_trips_breaker(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        for i in range(5):
            reg.record_failure("tool_a", f"error_{i}")
        assert reg._breakers["tool_a"].state == BreakerState.OPEN
        assert reg._breakers["tool_a"].failure_count == 5

    def test_record_success_resets_failures_when_closed(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg.record_failure("tool_a", "err")
        reg.record_failure("tool_a", "err")
        assert reg._breakers["tool_a"].failure_count == 2
        reg.record_success("tool_a")
        assert reg._breakers["tool_a"].failure_count == 0

    def test_half_open_success_threshold_closes_breaker(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg._breakers["tool_a"] = ToolCircuitBreaker(
            tool_id="tool_a",
            state=BreakerState.HALF_OPEN,
            success_threshold=3,
        )
        reg.record_success("tool_a")
        reg.record_success("tool_a")
        assert reg._breakers["tool_a"].state == BreakerState.HALF_OPEN
        reg.record_success("tool_a")
        assert reg._breakers["tool_a"].state == BreakerState.CLOSED

    def test_half_open_failure_reopens_breaker(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg._breakers["tool_a"] = ToolCircuitBreaker(
            tool_id="tool_a", state=BreakerState.HALF_OPEN
        )
        reg.record_failure("tool_a", "still broken")
        assert reg._breakers["tool_a"].state == BreakerState.OPEN


# ---------------------------------------------------------------------------
# Tests: Manual kill / enable
# ---------------------------------------------------------------------------


class TestKillEnable:
    """Test manual kill and enable operations."""

    def test_kill_tool_forces_open(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg.kill_tool("tool_a", reason="manual kill")
        assert reg._breakers["tool_a"].state == BreakerState.OPEN
        assert reg._breakers["tool_a"].manual_override == "killed"

    def test_killed_tool_stays_open_regardless_of_timeout(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg.kill_tool("tool_a", reason="testing")
        reg._breakers["tool_a"].last_failure_time = time.time() - 9999
        allowed, reason = reg.should_allow("tool_a")
        assert allowed is False
        assert "manual" in reason.lower() or "killed" in reason.lower()

    def test_enable_tool_forces_closed(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg.kill_tool("tool_a", reason="testing")
        reg.enable_tool("tool_a")
        assert reg._breakers["tool_a"].state == BreakerState.CLOSED
        assert reg._breakers["tool_a"].manual_override is None
        assert reg._breakers["tool_a"].failure_count == 0


# ---------------------------------------------------------------------------
# Tests: Quarantine report
# ---------------------------------------------------------------------------


class TestQuarantineReport:
    """Test the quarantine report."""

    def test_empty_report(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        report = reg.quarantine_report()
        assert report == []

    def test_report_shows_open_and_half_open(self, tmp_path: Path):
        reg = CircuitBreakerRegistry(state_path=tmp_path / "breakers.json")
        reg._breakers["tool_a"] = ToolCircuitBreaker(
            tool_id="tool_a", state=BreakerState.OPEN
        )
        reg._breakers["tool_b"] = ToolCircuitBreaker(
            tool_id="tool_b", state=BreakerState.HALF_OPEN
        )
        reg._breakers["tool_c"] = ToolCircuitBreaker(
            tool_id="tool_c", state=BreakerState.CLOSED
        )
        report = reg.quarantine_report()
        tool_ids = [b.tool_id for b in report]
        assert "tool_a" in tool_ids
        assert "tool_b" in tool_ids
        assert "tool_c" not in tool_ids


# ---------------------------------------------------------------------------
# Tests: Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Test state persistence to JSON file."""

    def test_save_and_load(self, tmp_path: Path):
        state_path = tmp_path / "breakers.json"
        reg1 = CircuitBreakerRegistry(state_path=state_path)
        reg1.kill_tool("tool_a", reason="test")
        reg1.record_failure("tool_b", "err")
        reg1._save()

        assert state_path.exists()

        reg2 = CircuitBreakerRegistry(state_path=state_path)
        assert "tool_a" in reg2._breakers
        assert reg2._breakers["tool_a"].state == BreakerState.OPEN
        assert "tool_b" in reg2._breakers
        assert reg2._breakers["tool_b"].failure_count == 1

    def test_auto_saves_on_state_change(self, tmp_path: Path):
        state_path = tmp_path / "breakers.json"
        reg = CircuitBreakerRegistry(state_path=state_path)
        reg.kill_tool("tool_a", reason="test")

        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert "tool_a" in data

    def test_handles_missing_state_file(self, tmp_path: Path):
        state_path = tmp_path / "nonexistent" / "breakers.json"
        reg = CircuitBreakerRegistry(state_path=state_path)
        assert len(reg._breakers) == 0

    def test_handles_corrupt_state_file(self, tmp_path: Path):
        state_path = tmp_path / "breakers.json"
        state_path.write_text("not valid json!!!")
        reg = CircuitBreakerRegistry(state_path=state_path)
        assert len(reg._breakers) == 0
