"""In-memory EventBus for the Toolwright MCP server.

Provides a bounded ring buffer of ServerEvent objects with synchronous
publish and async subscribe. Publishers never block; subscribers await
new events via asyncio.Event.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class ServerEvent:
    """A single event in the EventBus."""

    event_type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class EventBus:
    """In-memory event bus with ring buffer and async subscription.

    - publish() is synchronous (fire-and-forget, never blocks the caller)
    - subscribe() is an async generator that yields new events
    - recent() returns the last N events from the buffer
    - Bounded: oldest events are dropped when max_events is reached
    """

    def __init__(self, max_events: int = 1000) -> None:
        self._buffer: deque[ServerEvent] = deque(maxlen=max_events)
        self._subscribers: list[asyncio.Queue[ServerEvent]] = []

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event synchronously. Never blocks."""
        event = ServerEvent(event_type=event_type, data=data)
        self._buffer.append(event)
        # Fan out to all subscribers (non-blocking)
        for q in self._subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)

    def recent(self, limit: int) -> list[ServerEvent]:
        """Return the most recent events (up to limit)."""
        items = list(self._buffer)
        return items[-limit:] if len(items) > limit else items

    async def subscribe(self) -> Any:
        """Async generator that yields new events as they are published."""
        q: asyncio.Queue[ServerEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self._subscribers.remove(q)
