"""EventStore for the Toolwright Control Plane.

Provides:
- ConsoleEvent dataclass for the informational event stream
- EventStore: persistent work item index + in-memory ring buffer for SSE
- Atomic file writes (tmp + os.replace) for crash safety
- asyncio.Lock critical section for work item state transitions
- SSE subscription via asyncio.Queue
- Audit JSONL log (append-only, line-buffered)
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from toolwright.models.work_item import (
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
)


@dataclass
class ConsoleEvent:
    """A single event in the console event feed."""

    id: str  # Monotonic, format: "{start_epoch}_{seq:016d}"
    timestamp: float
    event_type: str
    severity: str  # "info", "warn", "error", "success"
    summary: str
    detail: Optional[dict[str, Any]] = None
    tool_id: Optional[str] = None
    session_id: Optional[str] = None
    work_item_id: Optional[str] = None


class EventStore:
    """Persistent event store with work item index and SSE support.

    State model:
    - WorkItem source of truth: per-item JSON files in work_items/{id}.json
    - Audit log: JSONL at console.log.jsonl (append-only)
    - Ring buffer: in-memory deque for SSE replay (ephemeral)
    """

    RING_BUFFER_SIZE = 5000

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # Audit log — opened once, line-buffered, held open
        self._log_path = self._state_dir / "console.log.jsonl"
        self._log_handle = open(self._log_path, "a", buffering=1)  # noqa: SIM115

        # Ring buffer for SSE replay
        self._ring: deque[ConsoleEvent] = deque(maxlen=self.RING_BUFFER_SIZE)

        # Work item index: id -> WorkItem
        self._work_items: dict[str, WorkItem] = {}

        # Sequence counter for monotonic event IDs
        self._server_start = int(time.time())
        self._sequence = 0
        self._seq_lock = threading.Lock()

        # Critical section for work item state transitions
        self._resolve_lock = asyncio.Lock()

        # SSE subscribers
        self._subscribers: list[asyncio.Queue[ConsoleEvent]] = []

        # Reconstruct open work items from persisted files
        self._reconstruct_from_files()

    def next_event_id(self) -> str:
        with self._seq_lock:
            self._sequence += 1
            return f"{self._server_start}_{self._sequence:016d}"

    # --- Event Publishing ---

    def publish_event(self, event: ConsoleEvent) -> None:
        if not event.id:
            event.id = self.next_event_id()

        # Audit log (best-effort)
        record = {
            "id": event.id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "severity": event.severity,
            "summary": event.summary,
            "detail": event.detail,
            "tool_id": event.tool_id,
            "session_id": event.session_id,
            "work_item_id": event.work_item_id,
        }
        try:
            self._log_handle.write(json.dumps(record) + "\n")
        except Exception:
            pass  # Best-effort audit

        # Ring buffer
        self._ring.append(event)

        # Notify SSE subscribers
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # --- Work Item Management ---

    def publish_work_item(self, item: WorkItem) -> None:
        """Upsert a work item.

        - If ID exists and is OPEN: update evidence (don't reset created_at)
        - If ID exists and is terminal: overwrite with new OPEN item (reopen)
        - If new: insert
        """
        existing = self._work_items.get(item.id)
        if existing and existing.status == WorkItemStatus.OPEN:
            # Update evidence on existing open item
            existing.evidence = item.evidence
            existing.subject_detail = item.subject_detail
            # Do NOT overwrite created_at
            self._persist_work_item(existing)
            return

        # New item OR reopening a previously-resolved item
        self._work_items[item.id] = item
        self._persist_work_item(item)

    def get_work_item(self, item_id: str) -> Optional[WorkItem]:
        return self._work_items.get(item_id)

    async def resolve_work_item(
        self,
        item_id: str,
        status: WorkItemStatus,
        resolved_by: str = "console",
        reason: str = "",
    ) -> tuple[Optional[WorkItem], bool]:
        """Transition a work item to a terminal state.

        Returns (work_item, is_conflict):
        - (item, False): Success or idempotent (already in target state)
        - (item, True): Conflict — already terminal in DIFFERENT state
        - (None, False): Not found

        IMPORTANT: This only handles the WorkItem state transition.
        The caller MUST perform the side effect (grant confirmation,
        approve tool, etc.) BEFORE calling this method.
        """
        async with self._resolve_lock:
            item = self._work_items.get(item_id)
            if item is None:
                return None, False

            if item.status == status:
                return item, False  # Idempotent

            if item.is_terminal():
                return item, True  # Conflict

            item.status = status
            item.resolved_at = time.time()
            item.resolved_by = resolved_by
            item.resolution_reason = reason

            self._persist_work_item(item)
            return item, False

    def open_work_items(
        self, kind: Optional[WorkItemKind] = None
    ) -> list[WorkItem]:
        items = [
            i
            for i in self._work_items.values()
            if i.status == WorkItemStatus.OPEN
        ]
        if kind:
            items = [i for i in items if i.kind == kind]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def work_item_counts(self) -> dict[str, Any]:
        counts: dict[str, Any] = {"open": 0, "by_kind": {}, "blocking": 0}
        for item in self._work_items.values():
            if item.status == WorkItemStatus.OPEN:
                counts["open"] += 1
                k = item.kind.value
                counts["by_kind"][k] = counts["by_kind"].get(k, 0) + 1
                if item.is_blocking:
                    counts["blocking"] += 1
        return counts

    # --- Expiration ---

    def check_expirations(self, confirmation_store: Any) -> list[WorkItem]:
        """Check for expired work items.

        CRITICAL: must also deny confirmation tokens to unblock waiting agents.
        """
        now = time.time()
        expired: list[WorkItem] = []
        for item in self._work_items.values():
            if (
                item.status == WorkItemStatus.OPEN
                and item.expires_at is not None
                and now > item.expires_at
            ):
                # MUST deny confirmation token to unblock the agent
                if item.kind == WorkItemKind.CONFIRMATION:
                    confirmation_store.deny(item.subject_id)

                item.status = WorkItemStatus.EXPIRED
                item.resolved_at = now
                item.resolved_by = "timeout"
                self._persist_work_item(item)
                expired.append(item)
        return expired

    # --- SSE ---

    def subscribe(self) -> asyncio.Queue[ConsoleEvent]:
        queue: asyncio.Queue[ConsoleEvent] = asyncio.Queue(maxsize=500)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[ConsoleEvent]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def events_since(self, last_event_id: str) -> list[ConsoleEvent]:
        if not last_event_id:
            return list(self._ring)
        events: list[ConsoleEvent] = []
        found = False
        for event in self._ring:
            if found:
                events.append(event)
            elif event.id == last_event_id:
                found = True
        if not found:
            return list(self._ring)
        return events

    # --- Persistence ---

    def _persist_work_item(self, item: WorkItem) -> None:
        """Atomic write: tmp file + os.replace to prevent corruption."""
        items_dir = self._state_dir / "work_items"
        items_dir.mkdir(exist_ok=True)
        tmp = items_dir / f".{item.id}.json.tmp"
        final = items_dir / f"{item.id}.json"
        tmp.write_text(json.dumps(item.to_dict(), indent=2))
        os.replace(str(tmp), str(final))

    def _reconstruct_from_files(self) -> None:
        """On startup, rebuild work item index from per-item JSON files."""
        items_dir = self._state_dir / "work_items"
        if not items_dir.exists():
            return
        for path in items_dir.glob("*.json"):
            if path.name.startswith("."):
                continue  # Skip tmp files
            try:
                data = json.loads(path.read_text())
                item = WorkItem.from_dict(data)
                self._work_items[item.id] = item
            except Exception:
                continue

    def close(self) -> None:
        if self._log_handle:
            self._log_handle.close()
