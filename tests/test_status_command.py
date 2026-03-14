"""Tests for the ``toolwright status`` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tests.helpers import write_demo_toolpack
from toolwright.cli.main import cli


class TestStatusCommand:
    """Tests for ``toolwright status``."""

    def test_status_with_explicit_toolpack(self, tmp_path: Path) -> None:
        """Status command works when --toolpack is given."""
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "status", "--toolpack", str(toolpack_file)],
        )
        assert result.exit_code == 0

    def test_status_json_mode(self, tmp_path: Path) -> None:
        """Status --json outputs valid JSON to stdout."""
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "status", "--toolpack", str(toolpack_file), "--json"],
        )
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert data["toolpack_id"] == "example"
        assert isinstance(data["tool_count"], int)
        assert "lockfile" in data
        assert "next_step" in data
        assert "alternatives" in data

    def test_status_json_lockfile_state(self, tmp_path: Path) -> None:
        """JSON output reflects lockfile state (pending from demo fixture)."""
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "status", "--toolpack", str(toolpack_file), "--json"],
        )
        assert result.exit_code == 0

        data = json.loads(result.output)
        # Demo toolpack has a pending lockfile
        assert data["lockfile"]["state"] in ("missing", "pending", "sealed", "stale")

    def test_status_auto_discover_single(self, tmp_path: Path) -> None:
        """Status auto-discovers when only one toolpack exists."""
        write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "status", "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["toolpack_id"] == "example"

    def test_status_no_toolpacks_found(self, tmp_path: Path) -> None:
        """Status exits with error when no toolpacks exist."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "status"],
        )
        assert result.exit_code != 0

    def test_status_json_includes_next_step(self, tmp_path: Path) -> None:
        """JSON mode includes next step recommendation."""
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "status", "--toolpack", str(toolpack_file), "--json"],
        )
        assert result.exit_code == 0

        data = json.loads(result.output)
        ns = data["next_step"]
        assert "command" in ns
        assert "label" in ns
        assert "why" in ns
        # Next step should have a toolwright command
        assert ns["command"].startswith("toolwright ")

    def test_status_json_drift_and_verify(self, tmp_path: Path) -> None:
        """JSON mode includes drift and verification state."""
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "status", "--toolpack", str(toolpack_file), "--json"],
        )
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert data["drift"] in ("not_checked", "clean", "warnings", "breaking")
        assert data["verification"] in ("not_run", "pass", "fail", "partial")

    def test_status_appears_in_help(self) -> None:
        """Status command shows in help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "status" in result.output

    def test_status_json_baseline_field(self, tmp_path: Path) -> None:
        """JSON output includes baseline information."""
        toolpack_file = write_demo_toolpack(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--root", str(tmp_path), "status", "--toolpack", str(toolpack_file), "--json"],
        )
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert "baseline" in data
        assert "exists" in data["baseline"]
