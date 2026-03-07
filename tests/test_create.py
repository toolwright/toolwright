"""Tests for the `toolwright create` command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli


MINI_API_SPEC = Path(__file__).parent / "fixtures" / "mini-api.json"


class TestCreateFromSpec:
    """Test creating a toolpack from a local OpenAPI spec."""

    def test_create_with_spec_produces_toolpack(self, tmp_path: Path) -> None:
        """create --spec <path> should produce a toolpack directory with tools.json and lockfile."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "--spec", str(MINI_API_SPEC),
                "--name", "mini-test",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}\n{result.stderr if hasattr(result, 'stderr') else ''}"

        # Toolpack directory should exist
        toolpacks_dir = tmp_path / ".toolwright" / "toolpacks"
        assert toolpacks_dir.exists(), f"Toolpacks dir missing. Output: {result.output}"

        # Find the toolpack
        toolpack_dirs = list(toolpacks_dir.iterdir())
        assert len(toolpack_dirs) >= 1, f"No toolpack dirs found. Output: {result.output}"

        toolpack_dir = toolpack_dirs[0]
        assert (toolpack_dir / "toolpack.yaml").exists()
        assert (toolpack_dir / "artifact" / "tools.json").exists()

        # Lockfile should exist
        lockfile_dir = toolpack_dir / "lockfile"
        assert lockfile_dir.exists()
        lockfiles = list(lockfile_dir.glob("*.yaml"))
        assert len(lockfiles) >= 1

    def test_create_with_spec_auto_approves_low_medium(self, tmp_path: Path) -> None:
        """create --spec should auto-approve low/medium risk tools by default."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "--spec", str(MINI_API_SPEC),
                "--name", "mini-test",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Find the lockfile
        toolpacks_dir = tmp_path / ".toolwright" / "toolpacks"
        toolpack_dir = list(toolpacks_dir.iterdir())[0]
        lockfile_dir = toolpack_dir / "lockfile"
        lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
        assert lockfile.exists(), f"Lockfile missing at {lockfile}"

        data = yaml.safe_load(lockfile.read_text())
        tools = data.get("tools", {})
        assert len(tools) > 0

        # GET endpoints should be low risk -> auto-approved
        approved = [t for t in tools.values() if t.get("status") == "approved"]
        assert len(approved) > 0, f"No auto-approved tools. Tools: {json.dumps(tools, indent=2)}"

    def test_create_with_spec_applies_crud_safety(self, tmp_path: Path) -> None:
        """create --spec should apply crud-safety rules by default."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "--spec", str(MINI_API_SPEC),
                "--name", "mini-test",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Rules should be applied in the toolpack dir
        toolpacks_dir = tmp_path / ".toolwright" / "toolpacks"
        toolpack_dir = list(toolpacks_dir.iterdir())[0]
        rules_path = toolpack_dir / "rules.json"
        assert rules_path.exists(), f"Rules file missing. Output: {result.output}"

        rules = json.loads(rules_path.read_text())
        assert len(rules) > 0

    def test_create_output_includes_example_tool(self, tmp_path: Path) -> None:
        """create output should show an example tool."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "--spec", str(MINI_API_SPEC),
                "--name", "mini-test",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "Example tool:" in result.output

    def test_create_output_includes_mcp_config(self, tmp_path: Path) -> None:
        """create output should include MCP config JSON for Claude Desktop."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "--spec", str(MINI_API_SPEC),
                "--name", "mini-test",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "mcpServers" in result.output or "toolwright config" in result.output

    def test_create_output_includes_gate_status_inline(self, tmp_path: Path) -> None:
        """create output should show approval status inline (not require separate gate status)."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "--spec", str(MINI_API_SPEC),
                "--name", "mini-test",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        # Should show auto-approved count inline
        assert "Auto-approved" in result.output or "approved" in result.output.lower()


class TestCreateFromRecipe:
    """Test creating a toolpack from a bundled recipe."""

    def test_create_unknown_api_lists_available(self, tmp_path: Path) -> None:
        """create with unknown API name should fail with helpful error."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "nonexistent-api-xyz",
            ],
        )

        assert result.exit_code != 0
        # Should list available APIs
        assert "github" in result.output.lower() or "available" in result.output.lower()

    def test_create_no_args_shows_help(self, tmp_path: Path) -> None:
        """create with no arguments should show help or error."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
            ],
        )

        # Should show help or prompt
        assert result.exit_code != 0 or "spec" in result.output.lower() or "usage" in result.output.lower()


class TestCreateFlags:
    """Test create command flags."""

    def test_no_auto_approve_leaves_tools_pending(self, tmp_path: Path) -> None:
        """create --no-auto-approve should leave all tools as pending."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "--spec", str(MINI_API_SPEC),
                "--name", "mini-test",
                "--no-auto-approve",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # All tools should be pending
        toolpacks_dir = tmp_path / ".toolwright" / "toolpacks"
        toolpack_dir = list(toolpacks_dir.iterdir())[0]
        lockfile = toolpack_dir / "lockfile" / "toolwright.lock.pending.yaml"
        data = yaml.safe_load(lockfile.read_text())
        tools = data.get("tools", {})

        approved = [t for t in tools.values() if t.get("status") == "approved"]
        assert len(approved) == 0, f"Found approved tools when --no-auto-approve: {approved}"

    def test_no_rules_skips_rule_application(self, tmp_path: Path) -> None:
        """create --no-rules should not create rules.json."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root", str(tmp_path / ".toolwright"),
                "create",
                "--spec", str(MINI_API_SPEC),
                "--name", "mini-test",
                "--no-rules",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"

        toolpacks_dir = tmp_path / ".toolwright" / "toolpacks"
        toolpack_dir = list(toolpacks_dir.iterdir())[0]
        rules_path = toolpack_dir / "rules.json"
        assert not rules_path.exists(), f"Rules file should not exist with --no-rules"
