"""Append-only JSONL event log for the reconciliation loop."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.models.reconcile import ReconcileEvent


class ReconcileEventLog:
    """Append-only structured log of all reconciliation events.

    Stored at .toolwright/state/reconcile.log.jsonl (one JSON object per line).
    """

    LOG_FILE = ".toolwright/state/reconcile.log.jsonl"

    def __init__(self, project_root: str) -> None:
        self.log_path = Path(project_root) / self.LOG_FILE
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: ReconcileEvent) -> None:
        """Append an event to the log."""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def recent(self, n: int = 50) -> list[dict]:
        """Read the N most recent events."""
        if not self.log_path.exists():
            return []
        with open(self.log_path, encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(line) for line in lines[-n:]]

    def events_for_tool(self, tool_id: str, n: int = 20) -> list[dict]:
        """Read recent events for a specific tool."""
        all_events = self.recent(500)
        return [e for e in all_events if e["tool_id"] == tool_id][-n:]
