"""Tests that gate allow prints the lockfile path after approval."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli


class TestGateAllowPrintsLockfilePath:
    """gate allow should print the lockfile path after approval."""

    def test_allow_all_prints_lockfile_path(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()

        # Sync first
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "sync", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code in (0, 1), f"Sync failed: {result.output}"

        # Allow all
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "allow", "--all", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code == 0, f"Allow failed: {result.output}"
        assert "Lockfile:" in result.output, f"Missing lockfile path in output: {result.output}"

    def test_allow_specific_tool_prints_lockfile_path(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()

        # Sync first
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "sync", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code in (0, 1), f"Sync failed: {result.output}"

        # Allow a specific tool
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "allow", "get_users", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code == 0, f"Allow failed: {result.output}"
        assert "Lockfile:" in result.output, f"Missing lockfile path in output: {result.output}"
