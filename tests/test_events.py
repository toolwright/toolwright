"""Tests for EventBus (Sprint 3a).

TDD RED phase: tests define expected behavior before implementation.
"""

from __future__ import annotations

import asyncio

import pytest

# ---------------------------------------------------------------------------
# EventBus core
# ---------------------------------------------------------------------------


class TestEventBus:
    """In-memory event bus with ring buffer semantics."""

    @pytest.mark.asyncio
    async def test_publish_and_recent(self) -> None:
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        bus.publish("tool_called", {"tool": "get_users"})
        bus.publish("decision", {"decision": "allow"})

        recent = bus.recent(10)
        assert len(recent) == 2
        assert recent[0].event_type == "tool_called"
        assert recent[1].event_type == "decision"

    @pytest.mark.asyncio
    async def test_ring_buffer_drops_oldest(self) -> None:
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=3)
        for i in range(5):
            bus.publish("event", {"index": i})

        recent = bus.recent(10)
        assert len(recent) == 3
        # Should have events 2, 3, 4 (oldest 0, 1 dropped)
        assert recent[0].data["index"] == 2
        assert recent[2].data["index"] == 4

    @pytest.mark.asyncio
    async def test_subscribe_receives_new_events(self) -> None:
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        received: list = []

        async def subscriber():
            async for event in bus.subscribe():
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.01)  # let subscriber start

        bus.publish("event_a", {"a": 1})
        bus.publish("event_b", {"b": 2})

        await asyncio.wait_for(task, timeout=2.0)
        assert len(received) == 2
        assert received[0].event_type == "event_a"
        assert received[1].event_type == "event_b"

    @pytest.mark.asyncio
    async def test_publish_is_synchronous(self) -> None:
        """Publish should not block (fire-and-forget)."""
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        # This should complete immediately even with no subscribers
        bus.publish("test", {"data": "value"})
        assert len(bus.recent(10)) == 1

    @pytest.mark.asyncio
    async def test_server_event_has_timestamp(self) -> None:
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        bus.publish("test", {"data": "value"})
        event = bus.recent(1)[0]
        assert hasattr(event, "timestamp")
        assert event.timestamp > 0

    @pytest.mark.asyncio
    async def test_server_event_has_id(self) -> None:
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        bus.publish("test", {})
        event = bus.recent(1)[0]
        assert hasattr(event, "event_id")
        assert event.event_id  # non-empty

    @pytest.mark.asyncio
    async def test_server_event_serializable(self) -> None:
        """Events should be JSON-serializable via to_dict()."""
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        bus.publish("tool_called", {"tool": "get_users", "args": {"limit": 10}})
        event = bus.recent(1)[0]

        d = event.to_dict()
        assert d["event_type"] == "tool_called"
        assert d["data"]["tool"] == "get_users"
        assert "timestamp" in d
        assert "event_id" in d

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self) -> None:
        """Multiple subscribers each get all events."""
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        received_a: list = []
        received_b: list = []

        async def sub_a():
            async for event in bus.subscribe():
                received_a.append(event)
                if len(received_a) >= 1:
                    break

        async def sub_b():
            async for event in bus.subscribe():
                received_b.append(event)
                if len(received_b) >= 1:
                    break

        task_a = asyncio.create_task(sub_a())
        task_b = asyncio.create_task(sub_b())
        await asyncio.sleep(0.01)

        bus.publish("shared_event", {"data": 1})

        await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=2.0)
        assert len(received_a) == 1
        assert len(received_b) == 1

    @pytest.mark.asyncio
    async def test_recent_empty(self) -> None:
        from toolwright.mcp.events import EventBus

        bus = EventBus(max_events=100)
        assert bus.recent(10) == []
