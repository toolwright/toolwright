"""Tests for confirmation prompts on destructive commands.

Phase 3.3: Verifies that `kill`, `rules remove`, and `rollback` require
explicit confirmation (or --yes/-y flag) before executing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _breaker_state_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "circuit_breakers.json"


def _rules_file(tmp_path: Path) -> Path:
    return tmp_path / "rules.json"


def _write_toolpack_files(tp_dir: Path) -> Path:
    """Create minimal toolpack files for snapshot/rollback testing."""
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


def _add_rule(runner: CliRunner, tmp_path: Path) -> str:
    """Add a rule and return its rule_id."""
    result = runner.invoke(
        cli,
        [
            "rules",
            "--rules-path",
            str(_rules_file(tmp_path)),
            "add",
            "--kind",
            "prohibition",
            "--target",
            "delete_user",
            "--description",
            "No deletes",
            "--rule-id",
            "test_rule_1",
        ],
    )
    assert result.exit_code == 0
    return "test_rule_1"


# ---------------------------------------------------------------------------
# Tests: kill confirmation
# ---------------------------------------------------------------------------


class TestKillConfirmation:
    """Test that `kill` requires confirmation unless --yes is passed."""

    def test_kill_without_yes_aborts_on_no(self, tmp_path: Path):
        """When the user answers 'n', kill should abort."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "kill",
                "some_tool",
                "--breaker-state",
                str(_breaker_state_path(tmp_path)),
            ],
            input="n\n",
        )
        assert result.exit_code != 0 or "Aborted" in result.output

        # Verify the tool was NOT killed
        state_path = _breaker_state_path(tmp_path)
        if state_path.exists():
            state = json.loads(state_path.read_text())
            assert "some_tool" not in state or state.get("some_tool", {}).get("state") != "open"

    def test_kill_without_yes_proceeds_on_yes_input(self, tmp_path: Path):
        """When the user answers 'y', kill should proceed."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "kill",
                "some_tool",
                "--breaker-state",
                str(_breaker_state_path(tmp_path)),
            ],
            input="y\n",
        )
        assert result.exit_code == 0
        assert "killed" in result.output.lower()

    def test_kill_with_yes_bypasses_confirmation(self, tmp_path: Path):
        """With --yes, kill proceeds without prompting."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "kill",
                "some_tool",
                "--yes",
                "--breaker-state",
                str(_breaker_state_path(tmp_path)),
            ],
        )
        assert result.exit_code == 0
        assert "killed" in result.output.lower()

        # Verify the tool was actually killed
        state = json.loads(_breaker_state_path(tmp_path).read_text())
        assert state["some_tool"]["state"] == "open"

    def test_kill_with_y_flag_bypasses_confirmation(self, tmp_path: Path):
        """With -y short flag, kill proceeds without prompting."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "kill",
                "some_tool",
                "-y",
                "--breaker-state",
                str(_breaker_state_path(tmp_path)),
            ],
        )
        assert result.exit_code == 0
        assert "killed" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: rules remove confirmation
# ---------------------------------------------------------------------------


class TestRulesRemoveConfirmation:
    """Test that `rules remove` requires confirmation unless --yes is passed."""

    def test_rules_remove_without_yes_aborts_on_no(self, tmp_path: Path):
        """When the user answers 'n', remove should abort."""
        runner = CliRunner()
        rule_id = _add_rule(runner, tmp_path)

        result = runner.invoke(
            cli,
            [
                "rules",
                "--rules-path",
                str(_rules_file(tmp_path)),
                "remove",
                rule_id,
            ],
            input="n\n",
        )
        assert result.exit_code != 0 or "Aborted" in result.output

        # Verify rule was NOT removed
        rules = json.loads(_rules_file(tmp_path).read_text())
        assert any(r["rule_id"] == rule_id for r in rules)

    def test_rules_remove_without_yes_proceeds_on_yes_input(self, tmp_path: Path):
        """When the user answers 'y', remove should proceed."""
        runner = CliRunner()
        rule_id = _add_rule(runner, tmp_path)

        result = runner.invoke(
            cli,
            [
                "rules",
                "--rules-path",
                str(_rules_file(tmp_path)),
                "remove",
                rule_id,
            ],
            input="y\n",
        )
        assert result.exit_code == 0
        assert "removed" in result.output.lower()

    def test_rules_remove_with_yes_bypasses_confirmation(self, tmp_path: Path):
        """With --yes, remove proceeds without prompting."""
        runner = CliRunner()
        rule_id = _add_rule(runner, tmp_path)

        result = runner.invoke(
            cli,
            [
                "rules",
                "--rules-path",
                str(_rules_file(tmp_path)),
                "remove",
                rule_id,
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        # Verify rule was actually removed
        rules = json.loads(_rules_file(tmp_path).read_text())
        assert not any(r["rule_id"] == rule_id for r in rules)

    def test_rules_remove_with_y_flag_bypasses_confirmation(self, tmp_path: Path):
        """With -y short flag, remove proceeds without prompting."""
        runner = CliRunner()
        rule_id = _add_rule(runner, tmp_path)

        result = runner.invoke(
            cli,
            [
                "rules",
                "--rules-path",
                str(_rules_file(tmp_path)),
                "remove",
                rule_id,
                "-y",
            ],
        )
        assert result.exit_code == 0
        assert "removed" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: rollback confirmation
# ---------------------------------------------------------------------------


class TestRollbackConfirmation:
    """Test that `rollback` requires confirmation unless --yes is passed."""

    def test_rollback_without_yes_aborts_on_no(self, tmp_path: Path):
        """When the user answers 'n', rollback should abort."""
        _write_toolpack_files(tmp_path)
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        versioner = ToolpackVersioner(tmp_path)
        snap_id = versioner.snapshot(label="before-change")

        # Modify a file
        tools_file = tmp_path / "artifact" / "tools.json"
        tools_file.write_text(json.dumps({"actions": [{"name": "CHANGED"}]}))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["rollback", snap_id, "--root", str(tmp_path)],
            input="n\n",
        )
        assert result.exit_code != 0 or "Aborted" in result.output

        # Verify the file was NOT restored
        assert "CHANGED" in tools_file.read_text()

    def test_rollback_without_yes_proceeds_on_yes_input(self, tmp_path: Path):
        """When the user answers 'y', rollback should proceed."""
        _write_toolpack_files(tmp_path)
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        versioner = ToolpackVersioner(tmp_path)
        snap_id = versioner.snapshot(label="before-change")

        # Modify a file
        tools_file = tmp_path / "artifact" / "tools.json"
        tools_file.write_text(json.dumps({"actions": [{"name": "CHANGED"}]}))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["rollback", snap_id, "--root", str(tmp_path)],
            input="y\n",
        )
        assert result.exit_code == 0
        assert "rolled back" in result.output.lower()

    def test_rollback_with_yes_bypasses_confirmation(self, tmp_path: Path):
        """With --yes, rollback proceeds without prompting."""
        _write_toolpack_files(tmp_path)
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        versioner = ToolpackVersioner(tmp_path)
        snap_id = versioner.snapshot(label="before-change")

        # Modify a file
        tools_file = tmp_path / "artifact" / "tools.json"
        tools_file.write_text(json.dumps({"actions": [{"name": "CHANGED"}]}))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["rollback", snap_id, "--yes", "--root", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "rolled back" in result.output.lower()

        # Verify file was restored
        restored = json.loads(tools_file.read_text())
        assert restored["actions"][0]["name"] == "get_users"

    def test_rollback_with_y_flag_bypasses_confirmation(self, tmp_path: Path):
        """With -y short flag, rollback proceeds without prompting."""
        _write_toolpack_files(tmp_path)
        from toolwright.core.reconcile.versioner import ToolpackVersioner

        versioner = ToolpackVersioner(tmp_path)
        snap_id = versioner.snapshot(label="before-change")

        # Modify a file
        tools_file = tmp_path / "artifact" / "tools.json"
        tools_file.write_text(json.dumps({"actions": [{"name": "CHANGED"}]}))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["rollback", snap_id, "-y", "--root", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "rolled back" in result.output.lower()
