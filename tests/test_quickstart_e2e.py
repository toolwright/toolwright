"""E2E validation tests for quickstart flows.

Uses the bundled tests/fixtures/mini-api.json (5-endpoint spec) to verify
the create command produces a working toolpack that downstream commands can operate on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

FIXTURES = Path(__file__).parent / "fixtures"
MINI_SPEC = FIXTURES / "mini-api.json"


@pytest.fixture
def cli_runner(tmp_path: Path):
    """CliRunner with isolated root."""
    from toolwright.cli.main import cli

    runner = CliRunner()

    def invoke(*args: str, **kwargs):
        return runner.invoke(cli, ["--root", str(tmp_path), *args], catch_exceptions=False, **kwargs)

    return invoke


class TestCreateProducesToolpack:
    """Verify create with a local spec produces all expected artifacts."""

    def test_create_produces_toolpack_dir(self, cli_runner, tmp_path: Path):
        result = cli_runner("create", "--spec", str(MINI_SPEC), "--name", "mini-api")
        assert result.exit_code == 0

        # Should have a toolpacks dir with at least one toolpack
        toolpacks_dir = tmp_path / "toolpacks"
        assert toolpacks_dir.exists()
        toolpack_dirs = list(toolpacks_dir.iterdir())
        assert len(toolpack_dirs) >= 1

        # Toolpack should contain artifact/tools.json and toolpack.yaml
        tp_dir = toolpack_dirs[0]
        assert (tp_dir / "artifact" / "tools.json").exists()
        assert (tp_dir / "toolpack.yaml").exists()

    def test_create_produces_lockfile(self, cli_runner, tmp_path: Path):
        result = cli_runner("create", "--spec", str(MINI_SPEC), "--name", "mini-api")
        assert result.exit_code == 0

        toolpacks_dir = tmp_path / "toolpacks"
        tp_dir = next(toolpacks_dir.iterdir())
        lockfile_dir = tp_dir / "lockfile"
        assert lockfile_dir.exists()
        lockfiles = list(lockfile_dir.glob("*.yaml"))
        assert len(lockfiles) >= 1

    def test_create_tools_have_expected_endpoints(self, cli_runner, tmp_path: Path):
        result = cli_runner("create", "--spec", str(MINI_SPEC), "--name", "mini-api")
        assert result.exit_code == 0

        toolpacks_dir = tmp_path / "toolpacks"
        tp_dir = next(toolpacks_dir.iterdir())
        manifest = json.loads((tp_dir / "artifact" / "tools.json").read_text())

        # Mini spec has 5 endpoints: GET/POST /users, GET/PUT/DELETE /users/{user_id}
        actions = manifest.get("actions", [])
        assert len(actions) == 5


class TestCreateUnknownApiError:
    """Verify helpful error for unknown API names."""

    def test_unknown_api_lists_available(self, cli_runner):
        result = cli_runner("create", "nonexistent-api-xyz")
        assert result.exit_code != 0
        # Should mention available recipes
        assert "available" in result.output.lower() or "unknown" in result.output.lower()


class TestGateStatusAfterCreate:
    """Verify gate status works after create."""

    def test_gate_status_shows_tools(self, cli_runner):
        # Create toolpack first
        result = cli_runner("create", "--spec", str(MINI_SPEC), "--name", "mini-api")
        assert result.exit_code == 0

        # Gate status should work
        result = cli_runner("gate", "status")
        assert result.exit_code == 0
        # Should show some tool information
        output = result.output + result.output
        assert "approved" in output.lower() or "pending" in output.lower() or "tool" in output.lower()


class TestCreateWithSpecUrl:
    """Test --spec flag with local file path."""

    def test_spec_from_local_file(self, cli_runner):
        result = cli_runner("create", "--spec", str(MINI_SPEC))
        assert result.exit_code == 0
        assert "Tools Created" in result.output or "tools" in result.output.lower()
