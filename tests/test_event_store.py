"""Tests for EventStore — persistence, work item lifecycle, SSE, expiration."""

import asyncio
import json
import time

from toolwright.models.work_item import (
    WorkItem,
    WorkItemAction,
    WorkItemKind,
    WorkItemStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path):
    """Create an EventStore in a temp directory."""
    from toolwright.mcp.event_store import EventStore

    return EventStore(state_dir=tmp_path)


def _make_approval_item(tool_id="get_users"):
    return WorkItem(
        id=f"wi_approval_{tool_id}",
        kind=WorkItemKind.TOOL_APPROVAL,
        subject_id=tool_id,
        subject_label=tool_id,
        subject_detail=f"GET /api/{tool_id}",
        risk_tier="low",
        evidence={"method": "GET", "path": f"/api/{tool_id}"},
        actions=[
            WorkItemAction("approve", "Approve", style="primary"),
            WorkItemAction("block", "Block", style="danger"),
        ],
    )


def _make_confirmation_item(token_id="token_1", tool_id="delete_repo"):
    return WorkItem(
        id=f"wi_confirm_{token_id}",
        kind=WorkItemKind.CONFIRMATION,
        subject_id=token_id,
        subject_label=tool_id,
        is_blocking=True,
        expires_at=time.time() + 300,
        actions=[
            WorkItemAction("confirm", "Confirm", style="primary"),
            WorkItemAction("deny", "Deny", style="danger"),
        ],
    )


# ---------------------------------------------------------------------------
# Event publishing
# ---------------------------------------------------------------------------


class TestEventPublishing:
    def test_publish_event_appends_to_ring_buffer(self, tmp_path):
        store = _make_store(tmp_path)
        from toolwright.mcp.event_store import ConsoleEvent

        event = ConsoleEvent(
            id="", timestamp=time.time(),
            event_type="tool_call_success", severity="success",
            summary="get_users succeeded", tool_id="get_users",
        )
        store.publish_event(event)
        assert len(store._ring) == 1
        assert store._ring[0].event_type == "tool_call_success"
        # Event ID should have been auto-assigned
        assert store._ring[0].id != ""
        store.close()

    def test_publish_event_writes_to_audit_log(self, tmp_path):
        store = _make_store(tmp_path)
        from toolwright.mcp.event_store import ConsoleEvent

        event = ConsoleEvent(
            id="", timestamp=time.time(),
            event_type="test_event", severity="info",
            summary="Test event",
        )
        store.publish_event(event)
        store.close()

        log_path = tmp_path / "console.log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event_type"] == "test_event"

    def test_event_ids_are_monotonic(self, tmp_path):
        store = _make_store(tmp_path)
        from toolwright.mcp.event_store import ConsoleEvent

        ids = []
        for i in range(5):
            e = ConsoleEvent(
                id="", timestamp=time.time(),
                event_type="test", severity="info", summary=f"Event {i}",
            )
            store.publish_event(e)
            ids.append(e.id)

        # IDs should be strictly increasing (string comparison works due to format)
        for i in range(1, len(ids)):
            assert ids[i] > ids[i - 1]
        store.close()


# ---------------------------------------------------------------------------
# Work item lifecycle
# ---------------------------------------------------------------------------


class TestWorkItemLifecycle:
    def test_publish_and_retrieve(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_approval_item()
        store.publish_work_item(item)

        retrieved = store.get_work_item(item.id)
        assert retrieved is not None
        assert retrieved.id == item.id
        assert retrieved.kind == WorkItemKind.TOOL_APPROVAL
        store.close()

    def test_publish_persists_to_file(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_approval_item()
        store.publish_work_item(item)
        store.close()

        # File should exist
        item_file = tmp_path / "work_items" / f"{item.id}.json"
        assert item_file.exists()
        data = json.loads(item_file.read_text())
        assert data["id"] == item.id

    def test_upsert_updates_evidence_not_created_at(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_approval_item()
        item.created_at = 1000.0
        store.publish_work_item(item)

        # Publish again with updated evidence
        item2 = _make_approval_item()
        item2.evidence["extra"] = "new_data"
        item2.created_at = 2000.0  # Should NOT overwrite
        store.publish_work_item(item2)

        retrieved = store.get_work_item(item.id)
        assert retrieved.evidence["extra"] == "new_data"
        assert retrieved.created_at == 1000.0  # Original timestamp preserved
        store.close()

    def test_upsert_reopens_terminal_item(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_approval_item()
        store.publish_work_item(item)

        # Resolve it
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            store.resolve_work_item(item.id, WorkItemStatus.APPROVED)
        )
        loop.close()

        assert store.get_work_item(item.id).is_terminal()

        # Re-publish — should reopen
        new_item = _make_approval_item()
        store.publish_work_item(new_item)

        retrieved = store.get_work_item(item.id)
        assert retrieved.status == WorkItemStatus.OPEN
        store.close()

    def test_resolve_success(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_approval_item()
        store.publish_work_item(item)

        loop = asyncio.new_event_loop()
        result, conflict = loop.run_until_complete(
            store.resolve_work_item(
                item.id, WorkItemStatus.APPROVED,
                resolved_by="console", reason="Operator approved"
            )
        )
        loop.close()

        assert result is not None
        assert not conflict
        assert result.status == WorkItemStatus.APPROVED
        assert result.resolved_by == "console"
        assert result.resolved_at is not None
        store.close()

    def test_resolve_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_approval_item()
        store.publish_work_item(item)

        loop = asyncio.new_event_loop()
        # Resolve twice to same state
        loop.run_until_complete(
            store.resolve_work_item(item.id, WorkItemStatus.APPROVED)
        )
        result, conflict = loop.run_until_complete(
            store.resolve_work_item(item.id, WorkItemStatus.APPROVED)
        )
        loop.close()

        assert result is not None
        assert not conflict  # Idempotent, not conflict
        store.close()

    def test_resolve_conflict(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_approval_item()
        store.publish_work_item(item)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            store.resolve_work_item(item.id, WorkItemStatus.APPROVED)
        )
        result, conflict = loop.run_until_complete(
            store.resolve_work_item(item.id, WorkItemStatus.DENIED)
        )
        loop.close()

        assert result is not None
        assert conflict  # Already approved, trying to deny = conflict
        assert result.status == WorkItemStatus.APPROVED
        store.close()

    def test_resolve_not_found(self, tmp_path):
        store = _make_store(tmp_path)
        loop = asyncio.new_event_loop()
        result, conflict = loop.run_until_complete(
            store.resolve_work_item("nonexistent", WorkItemStatus.APPROVED)
        )
        loop.close()
        assert result is None
        assert not conflict
        store.close()

    def test_open_work_items_filtered_by_kind(self, tmp_path):
        store = _make_store(tmp_path)
        store.publish_work_item(_make_approval_item("a"))
        store.publish_work_item(_make_approval_item("b"))
        store.publish_work_item(_make_confirmation_item())

        all_open = store.open_work_items()
        assert len(all_open) == 3

        approvals = store.open_work_items(kind=WorkItemKind.TOOL_APPROVAL)
        assert len(approvals) == 2

        confirmations = store.open_work_items(kind=WorkItemKind.CONFIRMATION)
        assert len(confirmations) == 1
        store.close()

    def test_work_item_counts(self, tmp_path):
        store = _make_store(tmp_path)
        store.publish_work_item(_make_approval_item("a"))
        store.publish_work_item(_make_approval_item("b"))
        store.publish_work_item(_make_confirmation_item())

        counts = store.work_item_counts()
        assert counts["open"] == 3
        assert counts["by_kind"]["tool_approval"] == 2
        assert counts["by_kind"]["confirmation"] == 1
        assert counts["blocking"] == 1
        store.close()


# ---------------------------------------------------------------------------
# Persistence and reconstruction
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_reconstruct_from_files(self, tmp_path):
        # Create store, add items, close
        store = _make_store(tmp_path)
        store.publish_work_item(_make_approval_item("x"))
        store.publish_work_item(_make_confirmation_item("t1"))
        store.close()

        # Create new store from same dir — should reconstruct
        store2 = _make_store(tmp_path)
        assert store2.get_work_item("wi_approval_x") is not None
        assert store2.get_work_item("wi_confirm_t1") is not None
        assert len(store2.open_work_items()) == 2
        store2.close()

    def test_atomic_write_creates_no_tmp_files(self, tmp_path):
        store = _make_store(tmp_path)
        store.publish_work_item(_make_approval_item())
        store.close()

        items_dir = tmp_path / "work_items"
        tmp_files = list(items_dir.glob(".*"))
        assert len(tmp_files) == 0  # No leftover .tmp files


# ---------------------------------------------------------------------------
# SSE replay
# ---------------------------------------------------------------------------


class TestSSEReplay:
    def test_events_since_returns_after_id(self, tmp_path):
        store = _make_store(tmp_path)
        from toolwright.mcp.event_store import ConsoleEvent

        events = []
        for i in range(5):
            e = ConsoleEvent(
                id="", timestamp=time.time(),
                event_type="test", severity="info", summary=f"Event {i}",
            )
            store.publish_event(e)
            events.append(e)

        # Get events after the 2nd one
        result = store.events_since(events[1].id)
        assert len(result) == 3  # events 2, 3, 4
        assert result[0].summary == "Event 2"
        store.close()

    def test_events_since_unknown_id_returns_all(self, tmp_path):
        store = _make_store(tmp_path)
        from toolwright.mcp.event_store import ConsoleEvent

        for i in range(3):
            e = ConsoleEvent(
                id="", timestamp=time.time(),
                event_type="test", severity="info", summary=f"E{i}",
            )
            store.publish_event(e)

        result = store.events_since("nonexistent_id")
        assert len(result) == 3  # Falls back to all
        store.close()

    def test_events_since_empty_id_returns_all(self, tmp_path):
        store = _make_store(tmp_path)
        from toolwright.mcp.event_store import ConsoleEvent

        for i in range(3):
            e = ConsoleEvent(
                id="", timestamp=time.time(),
                event_type="test", severity="info", summary=f"E{i}",
            )
            store.publish_event(e)

        result = store.events_since("")
        assert len(result) == 3
        store.close()


# ---------------------------------------------------------------------------
# Expiration
# ---------------------------------------------------------------------------


class TestExpiration:
    def test_expired_items_get_expired_status(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_confirmation_item()
        item.expires_at = time.time() - 10  # Already expired
        store.publish_work_item(item)

        # Mock confirmation_store
        class MockConfirmationStore:
            denied = []
            def deny(self, token_id, _reason=None):
                self.denied.append(token_id)
                return True

        mock_store = MockConfirmationStore()
        expired = store.check_expirations(mock_store)

        assert len(expired) == 1
        assert expired[0].status == WorkItemStatus.EXPIRED
        assert expired[0].resolved_by == "timeout"
        # CRITICAL: must have called deny on the confirmation store
        assert item.subject_id in mock_store.denied
        store.close()

    def test_non_expired_items_untouched(self, tmp_path):
        store = _make_store(tmp_path)
        item = _make_confirmation_item()
        item.expires_at = time.time() + 3600  # Future
        store.publish_work_item(item)

        class MockConfirmationStore:
            denied = []
            def deny(self, token_id, _reason=None):
                self.denied.append(token_id)

        mock_store = MockConfirmationStore()
        expired = store.check_expirations(mock_store)

        assert len(expired) == 0
        assert store.get_work_item(item.id).status == WorkItemStatus.OPEN
        store.close()


# ---------------------------------------------------------------------------
# SSE subscription
# ---------------------------------------------------------------------------


class TestSubscription:
    def test_subscribe_receives_published_events(self, tmp_path):
        store = _make_store(tmp_path)
        from toolwright.mcp.event_store import ConsoleEvent

        queue = store.subscribe()

        event = ConsoleEvent(
            id="", timestamp=time.time(),
            event_type="test", severity="info", summary="Hello",
        )
        store.publish_event(event)

        # Queue should have the event
        assert not queue.empty()
        received = queue.get_nowait()
        assert received.summary == "Hello"

        store.unsubscribe(queue)
        store.close()
