"""Tests that gate allow provides helpful guidance when snapshot can't be materialized."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli


class TestGateAllowSnapshotGuidance:
    """When gate allow approves tools but no toolpack.yaml exists,
    the user should see guidance about running gate snapshot."""

    def test_gate_allow_prints_snapshot_hint_when_no_toolpack(self, tmp_path: Path) -> None:
        """gate allow --all should tell users about next steps when snapshot can't auto-materialize."""
        # Create a minimal lockfile without a toolpack.yaml
        lockfile_dir = tmp_path / "lockfile"
        lockfile_dir.mkdir()
        lockfile_path = lockfile_dir / "toolwright.lock.yaml"

        # We need a tools.json to sync from
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        tools_path = artifacts_dir / "tools.json"
        tools_path.write_text(json.dumps({
            "schema_version": "1.0",
            "actions": [
                {
                    "name": "get_users",
                    "description": "Get users",
                    "method": "GET",
                    "path": "/users",
                    "host": "api.example.com",
                    "input_schema": {"type": "object", "properties": {}},
                    "risk_tier": "low",
                }
            ],
        }))

        runner = CliRunner()
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        # First sync to create lockfile
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "sync",
            "--tools", str(tools_path),
            "--lockfile", str(lockfile_path),
        ])
        assert result.exit_code in (0, 1)  # 1 = pending tools (expected)

        # Now approve all — no toolpack.yaml exists so snapshot can't materialize
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "allow", "--all", "--yes",
            "--lockfile", str(lockfile_path),
        ])
        assert result.exit_code == 0
        assert "Approved" in result.output
        # Should include hint about snapshot or next steps
        assert "snapshot" in result.output.lower() or "gate check" in result.output.lower() or "toolpack" in result.output.lower()

    def test_gate_allow_auto_snapshots_with_toolpack(self, tmp_path: Path) -> None:
        """When a toolpack.yaml exists, gate allow should auto-materialize snapshot silently."""
        toolpack_file = write_demo_toolpack(tmp_path)
        toolpack_dir = toolpack_file.parent

        # Load toolpack to find the lockfile path
        with open(toolpack_file) as f:
            tp = yaml.safe_load(f)

        lockfile_rel = tp["paths"]["lockfiles"].get("pending") or tp["paths"]["lockfiles"].get("approved")
        assert lockfile_rel is not None
        lockfile_path = toolpack_dir / lockfile_rel

        runner = CliRunner()
        root_path = str(tmp_path / ".toolwright")
        Path(root_path).mkdir(parents=True, exist_ok=True)

        # Approve all tools
        result = runner.invoke(cli, [
            "--root", root_path,
            "gate", "allow", "--all", "--yes",
            "--lockfile", str(lockfile_path),
        ])
        assert result.exit_code == 0
        assert "Approved" in result.output
        # Should NOT print snapshot guidance because it auto-materialized
        assert "run toolwright gate snapshot" not in result.output.lower()
