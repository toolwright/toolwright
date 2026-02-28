"""Tests for confirmation prompts on destructive gate commands.

Phase 1.4: gate allow --all requires confirmation (--yes / -y to skip)
Phase 1.5: gate sync --prune-removed requires confirmation (--yes / -y to skip)
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli


class TestGateAllowConfirmation:
    """gate allow --all should prompt for confirmation."""

    def test_allow_all_help_shows_yes_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["gate", "allow", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output or "-y" in result.output

    def test_allow_all_without_yes_aborts_on_decline(self, tmp_path: Path) -> None:
        """gate allow --all without --yes should prompt; declining aborts."""
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()

        # Sync first so there are pending tools
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "sync", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code in (0, 1), f"Sync failed: {result.output}"

        # Decline the confirmation prompt
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "allow", "--all", "--toolpack", str(toolpack_file)],
            input="n\n",
        )
        assert "Aborted" in result.output

    def test_allow_all_without_yes_proceeds_on_confirm(self, tmp_path: Path) -> None:
        """gate allow --all without --yes should prompt; confirming proceeds."""
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

        # Confirm the prompt
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "allow", "--all", "--toolpack", str(toolpack_file)],
            input="y\n",
        )
        assert result.exit_code == 0, f"Allow failed: {result.output}"
        assert "Approved" in result.output

    def test_allow_all_with_yes_skips_prompt(self, tmp_path: Path) -> None:
        """gate allow --all --yes should skip confirmation."""
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

        # --yes skips prompt
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "allow", "--all", "--yes", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code == 0, f"Allow failed: {result.output}"
        assert "Approved" in result.output

    def test_allow_specific_tool_no_prompt(self, tmp_path: Path) -> None:
        """gate allow <tool_id> should NOT prompt (only --all triggers prompt)."""
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

        # Allow a specific tool -- no prompt, no --yes needed
        result = runner.invoke(
            cli,
            ["--root", root_path, "gate", "allow", "get_users", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code == 0, f"Allow failed: {result.output}"
        assert "Approved" in result.output


class TestGateSyncConfirmation:
    """gate sync --prune-removed should prompt for confirmation."""

    def test_sync_help_shows_yes_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["gate", "sync", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output or "-y" in result.output

    def test_sync_prune_without_yes_aborts_on_decline(self, tmp_path: Path) -> None:
        """gate sync --prune-removed without --yes should prompt; declining aborts."""
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()

        # Decline the confirmation prompt
        result = runner.invoke(
            cli,
            [
                "--root", root_path,
                "gate", "sync",
                "--prune-removed",
                "--toolpack", str(toolpack_file),
            ],
            input="n\n",
        )
        assert "Aborted" in result.output

    def test_sync_prune_without_yes_proceeds_on_confirm(self, tmp_path: Path) -> None:
        """gate sync --prune-removed without --yes should prompt; confirming proceeds."""
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()

        # Confirm the prompt
        result = runner.invoke(
            cli,
            [
                "--root", root_path,
                "gate", "sync",
                "--prune-removed",
                "--toolpack", str(toolpack_file),
            ],
            input="y\n",
        )
        assert result.exit_code in (0, 1), f"Sync failed: {result.output}"
        assert "Synced lockfile" in result.output

    def test_sync_prune_with_yes_skips_prompt(self, tmp_path: Path) -> None:
        """gate sync --prune-removed --yes should skip confirmation."""
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "--root", root_path,
                "gate", "sync",
                "--prune-removed",
                "--yes",
                "--toolpack", str(toolpack_file),
            ],
        )
        assert result.exit_code in (0, 1), f"Sync failed: {result.output}"
        assert "Synced lockfile" in result.output

    def test_sync_without_prune_no_prompt(self, tmp_path: Path) -> None:
        """gate sync without --prune-removed should NOT prompt."""
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "--root", root_path,
                "gate", "sync",
                "--toolpack", str(toolpack_file),
            ],
        )
        assert result.exit_code in (0, 1), f"Sync failed: {result.output}"
        assert "Synced lockfile" in result.output
