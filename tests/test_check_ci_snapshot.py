"""Tests for check_ci snapshot validation."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli
from toolwright.core.approval import LockfileManager


def test_check_ci_requires_snapshot(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

    manager = LockfileManager(lockfile_path)
    manager.load()
    manager.approve_all()
    manager.save()

    runner = CliRunner()
    result = runner.invoke(cli, ["gate", "check", "--lockfile", str(lockfile_path)])
    assert result.exit_code == 1
    assert "baseline snapshot missing" in result.output

    result = runner.invoke(cli, ["gate", "snapshot", "--lockfile", str(lockfile_path)])
    assert result.exit_code == 0

    result = runner.invoke(cli, ["gate", "check", "--lockfile", str(lockfile_path)])
    assert result.exit_code == 0
