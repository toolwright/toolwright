"""Tests for --toolpack option on all gate subcommands."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli


def _lockfile_path_from_toolpack(toolpack_file: Path) -> Path:
    """Read the toolpack.yaml and return the absolute pending lockfile path."""
    with open(toolpack_file) as f:
        tp = yaml.safe_load(f)
    lockfile_rel = tp["paths"]["lockfiles"].get("pending") or tp["paths"]["lockfiles"].get("approved")
    assert lockfile_rel is not None
    return toolpack_file.parent / lockfile_rel


class TestGateSyncWithToolpack:
    """gate sync --toolpack resolves tools/lockfile from toolpack."""

    def test_gate_sync_with_toolpack(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "sync",
            "--toolpack", str(toolpack_file),
        ])
        # sync should succeed (exit 0 or 1 for pending)
        assert result.exit_code in (0, 1), f"Unexpected exit: {result.output}"
        assert "Synced lockfile" in result.output

    def test_gate_sync_toolpack_and_tools_conflict(self, tmp_path: Path) -> None:
        """Providing both --toolpack and --tools should error."""
        toolpack_file = write_demo_toolpack(tmp_path)
        tools_path = toolpack_file.parent / "artifact" / "tools.json"
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "sync",
            "--toolpack", str(toolpack_file),
            "--tools", str(tools_path),
        ])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower() or "cannot use" in result.output.lower()

    def test_gate_sync_requires_tools_or_toolpack(self, tmp_path: Path) -> None:
        """gate sync with neither --tools nor --toolpack should error."""
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "sync",
        ])
        assert result.exit_code != 0


class TestGateAllowWithToolpack:
    """gate allow --toolpack resolves lockfile from toolpack."""

    def test_gate_allow_with_toolpack(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "allow", "--all",
            "--toolpack", str(toolpack_file),
        ])
        assert result.exit_code == 0, f"Unexpected exit: {result.output}"
        assert "Approved" in result.output


class TestGateCheckWithToolpack:
    """gate check --toolpack resolves lockfile from toolpack."""

    def test_gate_check_with_toolpack(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        # First approve all so check passes
        runner.invoke(cli, [
            "--root", root_path,
            "gate", "allow", "--all",
            "--toolpack", str(toolpack_file),
        ])

        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "check",
            "--toolpack", str(toolpack_file),
        ])
        # check should succeed (exit 0) or fail (exit 1) -- we just need it to run, not crash
        assert result.exit_code in (0, 1), f"Unexpected exit: {result.output}"


class TestGateSnapshotWithToolpack:
    """gate snapshot --toolpack resolves lockfile from toolpack."""

    def test_gate_snapshot_with_toolpack(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        # First approve all
        runner.invoke(cli, [
            "--root", root_path,
            "gate", "allow", "--all",
            "--toolpack", str(toolpack_file),
        ])

        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "snapshot",
            "--toolpack", str(toolpack_file),
        ])
        assert result.exit_code == 0, f"Unexpected exit: {result.output}"


class TestGateStatusWithToolpack:
    """gate status --toolpack resolves lockfile from toolpack."""

    def test_gate_status_with_toolpack(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "status",
            "--toolpack", str(toolpack_file),
        ])
        assert result.exit_code == 0, f"Unexpected exit: {result.output}"
        assert "Lockfile:" in result.output


class TestGateBlockWithToolpack:
    """gate block --toolpack resolves lockfile from toolpack."""

    def test_gate_block_with_toolpack(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "block", "get_users",
            "--toolpack", str(toolpack_file),
            "--reason", "testing",
        ])
        # Should find and block the tool (exit 0) or find nothing (exit 1)
        # The important thing is it didn't crash looking for the lockfile
        assert result.exit_code in (0, 1), f"Unexpected exit: {result.output}"


class TestGateResealWithToolpack:
    """gate reseal --toolpack resolves lockfile from toolpack."""

    def test_gate_reseal_with_toolpack(self, tmp_path: Path) -> None:
        toolpack_file = write_demo_toolpack(tmp_path)
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "reseal",
            "--toolpack", str(toolpack_file),
        ])
        assert result.exit_code == 0, f"Unexpected exit: {result.output}"
        assert "Re-signed" in result.output
