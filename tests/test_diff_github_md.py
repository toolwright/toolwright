"""Snapshot tests for GitHub markdown diff output."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.core.approval import LockfileManager
from tests.helpers import write_demo_toolpack


def _append_write_action(tools_path: Path) -> None:
    payload = json.loads(tools_path.read_text())
    payload["actions"].append(
        {
            "id": "create_user",
            "tool_id": "sig_create_user",
            "name": "create_user",
            "description": "Create a user",
            "endpoint_id": "ep_create_user",
            "signature_id": "sig_create_user",
            "method": "POST",
            "path": "/users",
            "host": "api.example.com",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            "risk_tier": "medium",
            "confirmation_required": "on_risk",
            "rate_limit_per_minute": 30,
            "tags": ["write"],
        }
    )
    payload["actions"] = sorted(payload["actions"], key=lambda action: action["id"])
    tools_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def test_diff_writes_github_md_snapshot(tmp_path: Path) -> None:
    toolpack_file = write_demo_toolpack(tmp_path)
    lockfile_path = toolpack_file.parent / "lockfile" / "toolwright.lock.pending.yaml"
    tools_path = toolpack_file.parent / "artifact" / "tools.json"

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

    _append_write_action(tools_path)

    output_dir = tmp_path / "diff_output"
    result = runner.invoke(
        cli,
        [
            "diff",
            "--toolpack",
            str(toolpack_file),
            "--output",
            str(output_dir),
            "--format",
            "github-md",
        ],
    )
    assert result.exit_code == 0

    diff_md = output_dir / "diff.github.md"
    assert diff_md.exists()

    expected_path = Path(__file__).parent / "fixtures" / "diff_github_md_snapshot.md"
    assert diff_md.read_text() == expected_path.read_text()
