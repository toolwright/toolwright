"""Session history tracker for behavioral rules.

Records tool calls within a session so rule evaluators
can check prerequisites, sequences, and rate limits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CallRecord:
    """A single recorded tool call."""

    tool_id: str
    method: str
    host: str
    params: dict[str, Any]
    result_summary: str
    timestamp: float


class SessionHistory:
    """Tracks tool call history within a session."""

    def __init__(self, max_history: int = 1000) -> None:
        self.max_history = max_history
        self._calls: list[CallRecord] = []

    def record(
        self,
        tool_id: str,
        method: str,
        host: str,
        params: dict[str, Any],
        result_summary: str,
    ) -> None:
        """Append a tool call to history."""
        self._calls.append(
            CallRecord(
                tool_id=tool_id,
                method=method,
                host=host,
                params=params,
                result_summary=result_summary,
                timestamp=time.monotonic(),
            )
        )
        if len(self._calls) > self.max_history:
            self._calls = self._calls[-self.max_history :]

    def has_called(
        self,
        tool_id: str,
        *,
        with_args: dict[str, Any] | None = None,
    ) -> bool:
        """Check if a tool was called, optionally with specific args."""
        for call in self._calls:
            if call.tool_id != tool_id:
                continue
            if with_args is None:
                return True
            if all(call.params.get(k) == v for k, v in with_args.items()):
                return True
        return False

    def calls_since(self, seconds: float) -> list[CallRecord]:
        """Return calls within the last N seconds."""
        cutoff = time.monotonic() - seconds
        return [c for c in self._calls if c.timestamp >= cutoff]

    def call_count(self, tool_id: str | None = None) -> int:
        """Count calls, optionally filtered by tool_id."""
        if tool_id is None:
            return len(self._calls)
        return sum(1 for c in self._calls if c.tool_id == tool_id)

    def last_call(self, tool_id: str | None = None) -> CallRecord | None:
        """Return the most recent call, optionally filtered by tool_id."""
        if tool_id is None:
            return self._calls[-1] if self._calls else None
        for call in reversed(self._calls):
            if call.tool_id == tool_id:
                return call
        return None

    def call_sequence(self) -> list[str]:
        """Return the ordered list of tool_ids called."""
        return [c.tool_id for c in self._calls]

    def clear(self) -> None:
        """Reset all history."""
        self._calls.clear()
