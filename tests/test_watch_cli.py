"""Tests for watch status and watch log CLI commands."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from toolwright.models.reconcile import (
    EventKind,
    ReconcileEvent,
    ReconcileState,
    ToolReconcileState,
    ToolStatus,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project_root(tmp_path):
    """Create a project root with reconcile state and event log."""
    state_dir = tmp_path / ".toolwright" / "state"
    state_dir.mkdir(parents=True)

    # Write reconcile state
    state = ReconcileState(
        reconcile_count=10,
        last_full_reconcile="2026-02-27T10:00:00+00:00",
        tools={
            "get_users": ToolReconcileState(
                tool_id="get_users",
                status=ToolStatus.HEALTHY,
                consecutive_healthy=5,
                last_probe_at="2026-02-27T10:00:00+00:00",
            ),
            "create_issue": ToolReconcileState(
                tool_id="create_issue",
                status=ToolStatus.UNHEALTHY,
                consecutive_unhealthy=3,
                failure_class="server_error",
                last_probe_at="2026-02-27T09:55:00+00:00",
            ),
        },
    )
    (state_dir / "reconcile.json").write_text(state.model_dump_json(indent=2))

    # Write event log
    events = [
        ReconcileEvent(
            kind=EventKind.PROBE_HEALTHY,
            tool_id="get_users",
            description="Health probe passed (status=200, time=50ms)",
            timestamp="2026-02-27T10:00:00+00:00",
        ),
        ReconcileEvent(
            kind=EventKind.PROBE_UNHEALTHY,
            tool_id="create_issue",
            description="Health probe failed: server_error (status=500)",
            timestamp="2026-02-27T09:55:00+00:00",
        ),
        ReconcileEvent(
            kind=EventKind.PROBE_HEALTHY,
            tool_id="get_users",
            description="Health probe passed (status=200, time=45ms)",
            timestamp="2026-02-27T09:50:00+00:00",
        ),
    ]
    log_path = state_dir / "reconcile.log.jsonl"
    with open(log_path, "w") as f:
        for event in events:
            f.write(event.model_dump_json() + "\n")

    return tmp_path


class TestWatchStatusCommand:
    """Tests for `toolwright watch status`."""

    def test_shows_tool_health(self, runner, project_root):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["watch", "status", "--root", str(project_root)])
        assert result.exit_code == 0
        assert "get_users" in result.output
        assert "create_issue" in result.output
        assert "healthy" in result.output.lower()
        assert "unhealthy" in result.output.lower()

    def test_shows_reconcile_count(self, runner, project_root):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["watch", "status", "--root", str(project_root)])
        assert result.exit_code == 0
        assert "10" in result.output  # reconcile_count

    def test_handles_missing_state_file(self, runner, tmp_path):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["watch", "status", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "no reconcile state" in result.output.lower() or "not running" in result.output.lower()


class TestWatchLogCommand:
    """Tests for `toolwright watch log`."""

    def test_shows_events(self, runner, project_root):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["watch", "log", "--root", str(project_root)])
        assert result.exit_code == 0
        assert "get_users" in result.output
        assert "create_issue" in result.output

    def test_filters_by_tool(self, runner, project_root):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["watch", "log", "--tool", "get_users", "--root", str(project_root)]
        )
        assert result.exit_code == 0
        assert "get_users" in result.output
        assert "create_issue" not in result.output

    def test_limits_events(self, runner, project_root):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["watch", "log", "--last", "1", "--root", str(project_root)]
        )
        assert result.exit_code == 0
        # Should show at most 1 event
        lines = [line for line in result.output.strip().splitlines() if "probe" in line.lower()]
        assert len(lines) <= 1

    def test_handles_missing_log_file(self, runner, tmp_path):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["watch", "log", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "no events" in result.output.lower() or "empty" in result.output.lower()


class TestWatchCommandGroup:
    """Tests for `toolwright watch` command group."""

    def test_watch_help(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["watch", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output
        assert "log" in result.output

    def test_watch_is_registered(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["--help"])
        assert "watch" in result.output
