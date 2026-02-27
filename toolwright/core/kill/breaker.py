"""Circuit breaker state machine for the KILL pillar.

Each tool gets its own breaker with three states:
  CLOSED  -> normal operation, failures tracked
  OPEN    -> tool blocked, waiting for recovery timeout
  HALF_OPEN -> probe mode, allow limited calls to test recovery

Manual kill/enable overrides the automatic state machine.
State is persisted to JSON for durability across server restarts.
"""

from __future__ import annotations

import json
import time
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel


class BreakerState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ToolCircuitBreaker(BaseModel):
    """Per-tool circuit breaker state."""

    tool_id: str
    state: BreakerState = BreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 60
    success_threshold: int = 3
    manual_override: str | None = None
    last_failure_time: float | None = None
    last_failure_error: str | None = None
    kill_reason: str | None = None


class CircuitBreakerRegistry:
    """Manages circuit breakers for all tools.

    State is persisted to a JSON file using atomic writes.
    """

    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._breakers: dict[str, ToolCircuitBreaker] = {}
        self._load()

    def should_allow(self, tool_id: str) -> tuple[bool, str]:
        """Check if a tool call should be allowed.

        Returns (allowed, reason).
        """
        breaker = self._breakers.get(tool_id)
        if breaker is None:
            return True, ""

        if breaker.state == BreakerState.CLOSED:
            return True, ""

        if breaker.state == BreakerState.OPEN:
            # Manual kills never auto-recover
            if breaker.manual_override == "killed":
                return False, f"Tool '{tool_id}' manually killed: {breaker.kill_reason or 'no reason'}"

            # Check if recovery timeout has elapsed
            if breaker.last_failure_time is not None:
                elapsed = time.time() - breaker.last_failure_time
                if elapsed >= breaker.recovery_timeout_seconds:
                    breaker.state = BreakerState.HALF_OPEN
                    breaker.success_count = 0
                    self._save()
                    return True, ""

            return False, f"Circuit breaker open for '{tool_id}'"

        if breaker.state == BreakerState.HALF_OPEN:
            return True, ""

        return True, ""

    def record_success(self, tool_id: str) -> None:
        """Record a successful tool call."""
        breaker = self._get_or_create(tool_id)

        if breaker.state == BreakerState.CLOSED:
            breaker.failure_count = 0
        elif breaker.state == BreakerState.HALF_OPEN:
            breaker.success_count += 1
            if breaker.success_count >= breaker.success_threshold:
                breaker.state = BreakerState.CLOSED
                breaker.failure_count = 0
                breaker.success_count = 0

        self._save()

    def record_failure(self, tool_id: str, error: str) -> None:
        """Record a failed tool call."""
        breaker = self._get_or_create(tool_id)
        breaker.last_failure_error = error
        breaker.last_failure_time = time.time()

        if breaker.state == BreakerState.CLOSED:
            breaker.failure_count += 1
            if breaker.failure_count >= breaker.failure_threshold:
                breaker.state = BreakerState.OPEN
        elif breaker.state == BreakerState.HALF_OPEN:
            breaker.state = BreakerState.OPEN
            breaker.success_count = 0

        self._save()

    def kill_tool(self, tool_id: str, reason: str) -> None:
        """Manually force a tool's breaker to OPEN."""
        breaker = self._get_or_create(tool_id)
        breaker.state = BreakerState.OPEN
        breaker.manual_override = "killed"
        breaker.kill_reason = reason
        breaker.last_failure_time = time.time()
        self._save()

    def enable_tool(self, tool_id: str) -> None:
        """Manually reset a tool's breaker to CLOSED."""
        breaker = self._get_or_create(tool_id)
        breaker.state = BreakerState.CLOSED
        breaker.manual_override = None
        breaker.kill_reason = None
        breaker.failure_count = 0
        breaker.success_count = 0
        self._save()

    def quarantine_report(self) -> list[ToolCircuitBreaker]:
        """Return all breakers that are OPEN or HALF_OPEN."""
        return [
            b for b in self._breakers.values()
            if b.state in (BreakerState.OPEN, BreakerState.HALF_OPEN)
        ]

    def get_breaker(self, tool_id: str) -> ToolCircuitBreaker | None:
        """Get a breaker by tool_id, or None if not tracked."""
        return self._breakers.get(tool_id)

    def _get_or_create(self, tool_id: str) -> ToolCircuitBreaker:
        """Get an existing breaker or create a new one."""
        if tool_id not in self._breakers:
            self._breakers[tool_id] = ToolCircuitBreaker(tool_id=tool_id)
        return self._breakers[tool_id]

    def _load(self) -> None:
        """Load state from JSON file."""
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text())
            for tool_id, breaker_data in data.items():
                self._breakers[tool_id] = ToolCircuitBreaker.model_validate(breaker_data)
        except (json.JSONDecodeError, ValueError):
            self._breakers = {}

    def _save(self) -> None:
        """Persist state to JSON file atomically."""
        from toolwright.utils.files import atomic_write_text

        data = {
            tool_id: breaker.model_dump(mode="json")
            for tool_id, breaker in self._breakers.items()
        }
        atomic_write_text(self._state_path, json.dumps(data, indent=2))
