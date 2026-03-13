"""Tests for toolwright plan command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli
from toolwright.core.approval import LockfileManager


def test_plan_writes_deterministic_outputs(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"

    manager = LockfileManager(lockfile_path)
    manager.load()
    manager.approve_all()
    manager.save()

    runner = CliRunner()
    snapshot_result = runner.invoke(
        cli,
        ["gate", "snapshot", "--lockfile", str(lockfile_path)],
    )
    assert snapshot_result.exit_code == 0

    output_dir = tmp_path / "plan_output"
    result = runner.invoke(
        cli,
        ["diff", "--toolpack", str(toolpack_file), "--output", str(output_dir)],
    )

    assert result.exit_code == 0
    assert result.stdout == ""

    plan_json = json.loads((output_dir / "plan.json").read_text())
    assert plan_json["plan_version"] == "1"
    assert "generated_at" not in plan_json
    assert "toolpack_path" not in plan_json
