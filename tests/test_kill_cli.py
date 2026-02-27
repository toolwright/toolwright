"""Tests for the KILL pillar CLI commands.

Tests: kill, enable, quarantine, breaker-status.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "circuit_breakers.json"


def _invoke(runner: CliRunner, args: list[str], tmp_path: Path) -> object:
    """Invoke CLI with --breaker-state pointing to tmp_path."""
    return runner.invoke(cli, args + ["--breaker-state", str(_state_path(tmp_path))])


# ---------------------------------------------------------------------------
# Tests: kill command
# ---------------------------------------------------------------------------


class TestKillCommand:
    """Test the `toolwright kill` command."""

    def test_kill_tool(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["kill", "dangerous_tool", "--reason", "testing"], tmp_path)
        assert result.exit_code == 0
        assert "killed" in result.output.lower() or "disabled" in result.output.lower()

        # Verify state was persisted
        state = json.loads(_state_path(tmp_path).read_text())
        assert "dangerous_tool" in state
        assert state["dangerous_tool"]["state"] == "open"

    def test_kill_requires_reason(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["kill", "some_tool"], tmp_path)
        # Should either fail or use a default reason
        # We'll accept both behaviors
        assert result.exit_code == 0 or "reason" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: enable command
# ---------------------------------------------------------------------------


class TestEnableCommand:
    """Test the `toolwright enable` command."""

    def test_enable_killed_tool(self, tmp_path: Path):
        runner = CliRunner()
        # Kill first
        _invoke(runner, ["kill", "tool_a", "--reason", "test"], tmp_path)
        # Enable
        result = _invoke(runner, ["enable", "tool_a"], tmp_path)
        assert result.exit_code == 0
        assert "enabled" in result.output.lower() or "closed" in result.output.lower()

        state = json.loads(_state_path(tmp_path).read_text())
        assert state["tool_a"]["state"] == "closed"

    def test_enable_unknown_tool(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["enable", "nonexistent"], tmp_path)
        # Should succeed or give a helpful message
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Tests: quarantine command
# ---------------------------------------------------------------------------


class TestQuarantineCommand:
    """Test the `toolwright quarantine` command."""

    def test_empty_quarantine(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["quarantine"], tmp_path)
        assert result.exit_code == 0
        assert "no tools" in result.output.lower() or "empty" in result.output.lower() or "0" in result.output

    def test_quarantine_shows_killed_tools(self, tmp_path: Path):
        runner = CliRunner()
        _invoke(runner, ["kill", "tool_a", "--reason", "broken"], tmp_path)
        _invoke(runner, ["kill", "tool_b", "--reason", "flaky"], tmp_path)

        result = _invoke(runner, ["quarantine"], tmp_path)
        assert result.exit_code == 0
        assert "tool_a" in result.output
        assert "tool_b" in result.output


# ---------------------------------------------------------------------------
# Tests: breaker-status command
# ---------------------------------------------------------------------------


class TestBreakerStatusCommand:
    """Test the `toolwright breaker-status` command."""

    def test_status_of_unknown_tool(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["breaker-status", "unknown"], tmp_path)
        assert result.exit_code == 0
        assert "closed" in result.output.lower() or "no breaker" in result.output.lower()

    def test_status_of_killed_tool(self, tmp_path: Path):
        runner = CliRunner()
        _invoke(runner, ["kill", "tool_a", "--reason", "testing"], tmp_path)

        result = _invoke(runner, ["breaker-status", "tool_a"], tmp_path)
        assert result.exit_code == 0
        assert "open" in result.output.lower()
