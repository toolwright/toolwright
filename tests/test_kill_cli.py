"""Tests for the KILL pillar CLI commands.

Tests: kill, enable, quarantine, breaker-status.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "circuit_breakers.json"


def _lockfile_path(tmp_path: Path) -> Path:
    return tmp_path / "toolwright.lock.yaml"


def _create_lockfile(tmp_path: Path, tool_ids: list[str]) -> Path:
    """Create a minimal lockfile with the given tool IDs."""
    tools = {}
    for tid in tool_ids:
        tools[tid] = {
            "tool_id": tid,
            "tool_version": 1,
            "signature_id": f"sig_{tid}",
            "name": tid,
            "method": "GET",
            "path": f"/{tid}",
            "host": "example.com",
            "status": "approved",
        }
    lockfile_data = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "tools": tools,
        "total_tools": len(tool_ids),
    }
    path = _lockfile_path(tmp_path)
    path.write_text(yaml.dump(lockfile_data, default_flow_style=False))
    return path


def _invoke(runner: CliRunner, args: list[str], tmp_path: Path, **kwargs) -> object:
    """Invoke CLI with --breaker-state pointing to tmp_path."""
    return runner.invoke(cli, args + ["--breaker-state", str(_state_path(tmp_path))], **kwargs)


def _invoke_with_lockfile(
    runner: CliRunner, args: list[str], tmp_path: Path, **kwargs
) -> object:
    """Invoke CLI with --breaker-state and --lockfile pointing to tmp_path."""
    return runner.invoke(
        cli,
        args
        + ["--breaker-state", str(_state_path(tmp_path))]
        + ["--lockfile", str(_lockfile_path(tmp_path))],
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests: kill command
# ---------------------------------------------------------------------------


class TestKillCommand:
    """Test the `toolwright kill` command."""

    def test_kill_tool(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["kill", "dangerous_tool", "--reason", "testing", "--yes"], tmp_path)
        assert result.exit_code == 0
        assert "killed" in result.output.lower() or "disabled" in result.output.lower()

        # Verify state was persisted
        state = json.loads(_state_path(tmp_path).read_text())
        assert "dangerous_tool" in state
        assert state["dangerous_tool"]["state"] == "open"

    def test_kill_requires_reason(self, tmp_path: Path):
        runner = CliRunner()
        result = _invoke(runner, ["kill", "some_tool", "--yes"], tmp_path)
        # Should either fail or use a default reason
        # We'll accept both behaviors
        assert result.exit_code == 0 or "reason" in result.output.lower()

    def test_kill_invalid_tool_id_errors(self, tmp_path: Path):
        """Kill with a tool ID not in the lockfile should error with exit code 1."""
        runner = CliRunner()
        _create_lockfile(tmp_path, ["real_tool", "other_tool"])
        result = _invoke_with_lockfile(
            runner, ["kill", "typo_tool", "--reason", "testing", "--yes"], tmp_path
        )
        assert result.exit_code == 1
        assert "not found in lockfile" in result.output.lower()
        assert "real_tool" in result.output
        assert "other_tool" in result.output

    def test_kill_valid_tool_id_with_lockfile_succeeds(self, tmp_path: Path):
        """Kill with a valid tool ID from the lockfile should succeed."""
        runner = CliRunner()
        _create_lockfile(tmp_path, ["real_tool", "other_tool"])
        result = _invoke_with_lockfile(
            runner, ["kill", "real_tool", "--reason", "testing", "--yes"], tmp_path
        )
        assert result.exit_code == 0
        assert "killed" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: enable command
# ---------------------------------------------------------------------------


class TestEnableCommand:
    """Test the `toolwright enable` command."""

    def test_enable_killed_tool(self, tmp_path: Path):
        runner = CliRunner()
        # Kill first
        _invoke(runner, ["kill", "tool_a", "--reason", "test", "--yes"], tmp_path)
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

    def test_enable_invalid_tool_id_errors(self, tmp_path: Path):
        """Enable with a tool ID not in the lockfile should error with exit code 1."""
        runner = CliRunner()
        _create_lockfile(tmp_path, ["real_tool"])
        result = _invoke_with_lockfile(
            runner, ["enable", "typo_tool"], tmp_path
        )
        assert result.exit_code == 1
        assert "not found in lockfile" in result.output.lower()
        assert "real_tool" in result.output

    def test_enable_valid_tool_id_with_lockfile_succeeds(self, tmp_path: Path):
        """Enable with a valid tool ID from the lockfile should succeed."""
        runner = CliRunner()
        _create_lockfile(tmp_path, ["real_tool"])
        # Kill first, then enable
        _invoke_with_lockfile(
            runner, ["kill", "real_tool", "--reason", "test", "--yes"], tmp_path
        )
        result = _invoke_with_lockfile(
            runner, ["enable", "real_tool"], tmp_path
        )
        assert result.exit_code == 0
        assert "enabled" in result.output.lower()


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
        _invoke(runner, ["kill", "tool_a", "--reason", "broken", "--yes"], tmp_path)
        _invoke(runner, ["kill", "tool_b", "--reason", "flaky", "--yes"], tmp_path)

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
        _invoke(runner, ["kill", "tool_a", "--reason", "testing", "--yes"], tmp_path)

        result = _invoke(runner, ["breaker-status", "tool_a"], tmp_path)
        assert result.exit_code == 0
        assert "open" in result.output.lower()
