"""Tests for ReconcileEventLog (JSONL persistence)."""

from __future__ import annotations

import json

import pytest

from toolwright.core.reconcile.event_log import ReconcileEventLog
from toolwright.models.reconcile import EventKind, ReconcileEvent


class TestReconcileEventLog:
    def test_record_writes_jsonl(self, tmp_path):
        log = ReconcileEventLog(str(tmp_path))
        event = ReconcileEvent(
            kind=EventKind.PROBE_HEALTHY,
            tool_id="get_users",
            description="Health probe passed",
        )
        log.record(event)

        log_file = tmp_path / ".toolwright" / "state" / "reconcile.log.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["kind"] == "probe_healthy"
        assert data["tool_id"] == "get_users"

    def test_record_appends_multiple_events(self, tmp_path):
        log = ReconcileEventLog(str(tmp_path))
        for i in range(5):
            event = ReconcileEvent(
                kind=EventKind.PROBE_HEALTHY,
                tool_id=f"tool_{i}",
                description=f"Event {i}",
            )
            log.record(event)

        log_file = tmp_path / ".toolwright" / "state" / "reconcile.log.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 5

    def test_recent_returns_last_n(self, tmp_path):
        log = ReconcileEventLog(str(tmp_path))
        for i in range(10):
            event = ReconcileEvent(
                kind=EventKind.PROBE_HEALTHY,
                tool_id=f"tool_{i}",
                description=f"Event {i}",
            )
            log.record(event)

        recent = log.recent(n=3)
        assert len(recent) == 3
        # Last 3 events should be tool_7, tool_8, tool_9
        assert recent[0]["tool_id"] == "tool_7"
        assert recent[2]["tool_id"] == "tool_9"

    def test_recent_returns_all_when_fewer_than_n(self, tmp_path):
        log = ReconcileEventLog(str(tmp_path))
        event = ReconcileEvent(
            kind=EventKind.PROBE_HEALTHY,
            tool_id="only_one",
            description="Single event",
        )
        log.record(event)

        recent = log.recent(n=50)
        assert len(recent) == 1

    def test_recent_returns_empty_when_no_log(self, tmp_path):
        log = ReconcileEventLog(str(tmp_path))
        assert log.recent() == []

    def test_events_for_tool(self, tmp_path):
        log = ReconcileEventLog(str(tmp_path))
        # Write events for multiple tools
        for i in range(5):
            log.record(ReconcileEvent(
                kind=EventKind.PROBE_HEALTHY,
                tool_id="get_users",
                description=f"Probe {i}",
            ))
            log.record(ReconcileEvent(
                kind=EventKind.PROBE_UNHEALTHY,
                tool_id="create_issue",
                description=f"Probe {i}",
            ))

        events = log.events_for_tool("get_users", n=3)
        assert len(events) == 3
        for e in events:
            assert e["tool_id"] == "get_users"

    def test_events_for_tool_returns_empty_for_unknown_tool(self, tmp_path):
        log = ReconcileEventLog(str(tmp_path))
        log.record(ReconcileEvent(
            kind=EventKind.PROBE_HEALTHY,
            tool_id="get_users",
            description="Probe",
        ))
        assert log.events_for_tool("nonexistent") == []

    def test_creates_parent_directories(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "project"
        log = ReconcileEventLog(str(nested))
        log.record(ReconcileEvent(
            kind=EventKind.PROBE_HEALTHY,
            tool_id="test",
            description="test",
        ))
        log_file = nested / ".toolwright" / "state" / "reconcile.log.jsonl"
        assert log_file.exists()
