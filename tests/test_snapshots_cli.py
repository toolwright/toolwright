"""Tests for snapshots and rollback CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from toolwright.core.reconcile.versioner import ToolpackVersioner


@pytest.fixture
def runner():
    return CliRunner()


def _write_toolpack_files(tp_dir: Path) -> Path:
    """Create minimal toolpack files for testing."""
    tp_dir.mkdir(parents=True, exist_ok=True)
    artifact = tp_dir / "artifact"
    artifact.mkdir(exist_ok=True)
    lockfile = tp_dir / "lockfile"
    lockfile.mkdir(exist_ok=True)
    (artifact / "tools.json").write_text(
        json.dumps({"actions": [{"name": "get_users"}]})
    )
    (artifact / "toolsets.yaml").write_text(yaml.safe_dump({"toolsets": []}))
    (artifact / "policy.yaml").write_text(
        yaml.safe_dump({"version": "1.0", "rules": []})
    )
    (artifact / "baseline.json").write_text(json.dumps({"endpoints": []}))
    (lockfile / "toolwright.lock.pending.yaml").write_text(
        yaml.safe_dump({"version": "1.0.0", "tools": {}})
    )
    toolpack = {
        "version": "1.0.0",
        "toolpack_id": "tp_test",
        "paths": {
            "tools": "artifact/tools.json",
            "toolsets": "artifact/toolsets.yaml",
            "policy": "artifact/policy.yaml",
            "baseline": "artifact/baseline.json",
            "lockfiles": {"pending": "lockfile/toolwright.lock.pending.yaml"},
        },
    }
    tp_file = tp_dir / "toolpack.yaml"
    tp_file.write_text(yaml.safe_dump(toolpack, sort_keys=False))
    return tp_file


class TestSnapshotsHelp:
    """Test that snapshots --help shows usage."""

    def test_snapshots_help(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["snapshots", "--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output or "usage" in result.output.lower()


class TestSnapshotsEmpty:
    """Test snapshots command with no snapshots."""

    def test_no_snapshots_message(self, runner, tmp_path):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["snapshots", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "no snapshots" in result.output.lower()


class TestSnapshotsList:
    """Test snapshots command lists existing snapshots."""

    def test_lists_snapshots(self, runner, tmp_path):
        from toolwright.cli.main import cli

        _write_toolpack_files(tmp_path)
        versioner = ToolpackVersioner(tmp_path)
        snap_id = versioner.snapshot(label="test-label")

        result = runner.invoke(cli, ["snapshots", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert snap_id in result.output
        assert "test-label" in result.output

    def test_lists_multiple_snapshots(self, runner, tmp_path):
        from toolwright.cli.main import cli

        _write_toolpack_files(tmp_path)
        versioner = ToolpackVersioner(tmp_path)
        snap1 = versioner.snapshot(label="first")
        snap2 = versioner.snapshot(label="second")

        result = runner.invoke(cli, ["snapshots", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert snap1 in result.output
        assert snap2 in result.output
        assert "first" in result.output
        assert "second" in result.output


class TestRollbackHelp:
    """Test that rollback --help shows usage."""

    def test_rollback_help(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["rollback", "--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output or "usage" in result.output.lower()
        assert "SNAPSHOT_ID" in result.output or "snapshot_id" in result.output.lower()


class TestRollbackInvalid:
    """Test rollback with invalid snapshot_id."""

    def test_invalid_snapshot_exits_1(self, runner, tmp_path):
        from toolwright.cli.main import cli

        result = runner.invoke(
            cli, ["rollback", "nonexistent-snap-id", "--yes", "--root", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "error" in result.output.lower()


class TestRollbackValid:
    """Test rollback with a valid snapshot restores files."""

    def test_rollback_restores_files(self, runner, tmp_path):
        from toolwright.cli.main import cli

        _write_toolpack_files(tmp_path)
        versioner = ToolpackVersioner(tmp_path)
        snap_id = versioner.snapshot(label="before-change")

        # Modify a file after snapshotting
        tools_file = tmp_path / "artifact" / "tools.json"
        tools_file.write_text(json.dumps({"actions": [{"name": "CHANGED"}]}))

        # Verify the file was changed
        assert "CHANGED" in tools_file.read_text()

        # Rollback
        result = runner.invoke(
            cli, ["rollback", snap_id, "--yes", "--root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "rolled back" in result.output.lower() or "success" in result.output.lower()

        # Verify file was restored
        restored = json.loads(tools_file.read_text())
        assert restored["actions"][0]["name"] == "get_users"


class TestCommandsRegistered:
    """Test that both commands are registered in CLI help."""

    def test_snapshots_in_cli_help(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["--help"])
        assert "snapshots" in result.output

    def test_rollback_in_cli_help(self, runner):
        from toolwright.cli.main import cli

        result = runner.invoke(cli, ["--help"])
        assert "rollback" in result.output


class TestSnapshotsInCoreCommands:
    """Test that snapshots is in CORE_COMMANDS."""

    def test_snapshots_in_core_commands(self):
        from toolwright.cli.main import CORE_COMMANDS

        assert "snapshots" in CORE_COMMANDS


class TestRollbackInCoreCommands:
    """Test that rollback is in CORE_COMMANDS."""

    def test_rollback_in_core_commands(self):
        from toolwright.cli.main import CORE_COMMANDS

        assert "rollback" in CORE_COMMANDS
