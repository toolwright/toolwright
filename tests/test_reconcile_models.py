"""Tests for reconciliation models (Phase 9)."""

from __future__ import annotations

import json

import yaml

from toolwright.models.reconcile import (
    AutoHealPolicy,
    EventKind,
    ReconcileAction,
    ReconcileEvent,
    ReconcileState,
    ToolReconcileState,
    ToolStatus,
    WatchConfig,
)

# ---------------------------------------------------------------------------
# ToolStatus enum
# ---------------------------------------------------------------------------


class TestToolStatus:
    def test_values(self):
        assert ToolStatus.HEALTHY == "healthy"
        assert ToolStatus.DEGRADED == "degraded"
        assert ToolStatus.UNHEALTHY == "unhealthy"
        assert ToolStatus.UNKNOWN == "unknown"


# ---------------------------------------------------------------------------
# AutoHealPolicy enum
# ---------------------------------------------------------------------------


class TestAutoHealPolicy:
    def test_values(self):
        assert AutoHealPolicy.OFF == "off"
        assert AutoHealPolicy.SAFE == "safe"
        assert AutoHealPolicy.ALL == "all"


# ---------------------------------------------------------------------------
# ReconcileAction enum
# ---------------------------------------------------------------------------


class TestReconcileAction:
    def test_values(self):
        assert ReconcileAction.NONE == "none"
        assert ReconcileAction.AUTO_REPAIRED == "auto_repaired"
        assert ReconcileAction.APPROVAL_QUEUED == "approval_queued"
        assert ReconcileAction.QUARANTINED == "quarantined"
        assert ReconcileAction.BREAKER_TRIPPED == "breaker_tripped"


# ---------------------------------------------------------------------------
# EventKind enum
# ---------------------------------------------------------------------------


class TestEventKind:
    def test_all_event_kinds_exist(self):
        kinds = [
            EventKind.PROBE_HEALTHY,
            EventKind.PROBE_UNHEALTHY,
            EventKind.DRIFT_DETECTED,
            EventKind.AUTO_REPAIRED,
            EventKind.REPAIR_FAILED,
            EventKind.APPROVAL_QUEUED,
            EventKind.QUARANTINED,
            EventKind.BREAKER_TRIPPED,
            EventKind.BREAKER_RECOVERED,
            EventKind.CAPABILITY_REQUESTED,
            EventKind.CAPABILITY_DRAFTED,
            EventKind.RULE_SUGGESTED,
            EventKind.ROLLBACK,
        ]
        assert len(kinds) == 13


# ---------------------------------------------------------------------------
# ToolReconcileState
# ---------------------------------------------------------------------------


class TestToolReconcileState:
    def test_defaults(self):
        state = ToolReconcileState(tool_id="get_users")
        assert state.tool_id == "get_users"
        assert state.status == ToolStatus.UNKNOWN
        assert state.failure_class is None
        assert state.consecutive_healthy == 0
        assert state.consecutive_unhealthy == 0
        assert state.last_probe_at is None
        assert state.last_action == ReconcileAction.NONE
        assert state.pending_repair is None
        assert state.version == 0

    def test_serialization_roundtrip(self):
        state = ToolReconcileState(
            tool_id="create_issue",
            status=ToolStatus.DEGRADED,
            consecutive_unhealthy=3,
            last_action=ReconcileAction.APPROVAL_QUEUED,
            pending_repair="new required field project_id",
            version=2,
        )
        data = state.model_dump()
        restored = ToolReconcileState.model_validate(data)
        assert restored.tool_id == "create_issue"
        assert restored.status == ToolStatus.DEGRADED
        assert restored.consecutive_unhealthy == 3
        assert restored.last_action == ReconcileAction.APPROVAL_QUEUED
        assert restored.pending_repair == "new required field project_id"
        assert restored.version == 2

    def test_json_roundtrip(self):
        state = ToolReconcileState(tool_id="list_repos", status=ToolStatus.HEALTHY)
        json_str = state.model_dump_json()
        restored = ToolReconcileState.model_validate_json(json_str)
        assert restored == state


# ---------------------------------------------------------------------------
# ReconcileState (aggregate)
# ---------------------------------------------------------------------------


class TestReconcileState:
    def test_defaults(self):
        state = ReconcileState()
        assert state.tools == {}
        assert state.last_full_reconcile is None
        assert state.reconcile_count == 0
        assert state.auto_repairs_applied == 0
        assert state.approvals_queued == 0
        assert state.errors == 0

    def test_with_tools(self):
        t1 = ToolReconcileState(tool_id="get_users", status=ToolStatus.HEALTHY)
        t2 = ToolReconcileState(tool_id="create_issue", status=ToolStatus.DEGRADED)
        state = ReconcileState(
            tools={"get_users": t1, "create_issue": t2},
            reconcile_count=5,
            auto_repairs_applied=1,
        )
        assert len(state.tools) == 2
        assert state.tools["get_users"].status == ToolStatus.HEALTHY
        assert state.reconcile_count == 5

    def test_json_persistence(self):
        t1 = ToolReconcileState(tool_id="get_users", status=ToolStatus.HEALTHY)
        state = ReconcileState(tools={"get_users": t1}, reconcile_count=10)
        json_str = state.model_dump_json()
        data = json.loads(json_str)
        assert data["reconcile_count"] == 10
        restored = ReconcileState.model_validate_json(json_str)
        assert restored.tools["get_users"].status == ToolStatus.HEALTHY


# ---------------------------------------------------------------------------
# WatchConfig
# ---------------------------------------------------------------------------


class TestWatchConfig:
    def test_defaults(self):
        config = WatchConfig()
        assert config.auto_heal == AutoHealPolicy.SAFE
        assert config.probe_intervals["critical"] == 120
        assert config.probe_intervals["high"] == 300
        assert config.probe_intervals["medium"] == 600
        assert config.probe_intervals["low"] == 1800
        assert config.max_concurrent_probes == 5
        assert config.snapshot_before_repair is True
        assert config.unhealthy_backoff_multiplier == 2.0
        assert config.unhealthy_backoff_max == 3600

    def test_probe_interval_for_risk(self):
        config = WatchConfig()
        assert config.probe_interval_for_risk("critical") == 120
        assert config.probe_interval_for_risk("high") == 300
        assert config.probe_interval_for_risk("medium") == 600
        assert config.probe_interval_for_risk("low") == 1800
        # Unknown risk tier falls back to medium
        assert config.probe_interval_for_risk("unknown_tier") == 600

    def test_custom_intervals(self):
        config = WatchConfig(
            probe_intervals={"critical": 60, "high": 120, "medium": 300, "low": 600}
        )
        assert config.probe_interval_for_risk("critical") == 60

    def test_from_yaml(self, tmp_path):
        yaml_content = {
            "auto_heal": "off",
            "probe_intervals": {
                "critical": 60,
                "high": 120,
                "medium": 300,
                "low": 600,
            },
            "max_concurrent_probes": 3,
            "snapshot_before_repair": False,
        }
        yaml_path = tmp_path / "watch.yaml"
        yaml_path.write_text(yaml.dump(yaml_content))

        config = WatchConfig.from_yaml(str(yaml_path))
        assert config.auto_heal == AutoHealPolicy.OFF
        assert config.probe_intervals["critical"] == 60
        assert config.max_concurrent_probes == 3
        assert config.snapshot_before_repair is False

    def test_from_yaml_missing_file_returns_defaults(self):
        config = WatchConfig.from_yaml("/nonexistent/path/watch.yaml")
        assert config.auto_heal == AutoHealPolicy.SAFE
        assert config.probe_intervals["critical"] == 120

    def test_from_yaml_partial_overrides(self, tmp_path):
        yaml_path = tmp_path / "watch.yaml"
        yaml_path.write_text("auto_heal: all\n")

        config = WatchConfig.from_yaml(str(yaml_path))
        assert config.auto_heal == AutoHealPolicy.ALL
        # Other fields should be defaults
        assert config.probe_intervals["critical"] == 120


# ---------------------------------------------------------------------------
# ReconcileEvent
# ---------------------------------------------------------------------------


class TestReconcileEvent:
    def test_creation(self):
        event = ReconcileEvent(
            kind=EventKind.PROBE_HEALTHY,
            tool_id="get_users",
            description="Health probe passed",
        )
        assert event.kind == EventKind.PROBE_HEALTHY
        assert event.tool_id == "get_users"
        assert event.timestamp is not None
        assert event.classification is None
        assert event.snapshot_id is None

    def test_with_optional_fields(self):
        event = ReconcileEvent(
            kind=EventKind.AUTO_REPAIRED,
            tool_id="create_issue",
            description="Fixed schema",
            classification="safe",
            snapshot_id="20240315T094500Z",
        )
        assert event.classification == "safe"
        assert event.snapshot_id == "20240315T094500Z"

    def test_json_serialization(self):
        event = ReconcileEvent(
            kind=EventKind.DRIFT_DETECTED,
            tool_id="list_repos",
            description="2 changes detected",
        )
        data = json.loads(event.model_dump_json())
        assert data["kind"] == "drift_detected"
        assert data["tool_id"] == "list_repos"
        assert "timestamp" in data

    def test_jsonl_line_format(self):
        """Events should serialize to valid JSONL lines."""
        event = ReconcileEvent(
            kind=EventKind.QUARANTINED,
            tool_id="delete_repo",
            description="Manual intervention needed",
            classification="manual",
        )
        line = event.model_dump_json()
        # Should be a single line (no newlines in the JSON)
        assert "\n" not in line
        # Should parse back
        parsed = json.loads(line)
        assert parsed["kind"] == "quarantined"
