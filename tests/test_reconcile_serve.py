"""Tests for --watch flag integration with serve command."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from toolwright.core.health.checker import HealthResult
from toolwright.core.reconcile.loop import ReconcileLoop
from toolwright.models.reconcile import WatchConfig


class TestReconcileLoopIntegrationWithServer:
    """Tests for ReconcileLoop starting alongside MCP server."""

    @pytest.mark.asyncio
    async def test_reconcile_loop_starts_from_server_actions(self, tmp_path):
        """ReconcileLoop should be constructable from server action dicts."""
        actions = [
            {"name": "get_users", "method": "GET", "host": "api.example.com", "path": "/users"},
            {"name": "create_issue", "method": "POST", "host": "api.example.com", "path": "/issues"},
        ]
        risk_tiers = {"get_users": "medium", "create_issue": "high"}

        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=actions,
            risk_tiers=risk_tiers,
        )

        # Mock the prober
        loop._prober.probe_due_tools = AsyncMock(
            return_value={
                "get_users": HealthResult(tool_id="get_users", healthy=True, status_code=200),
                "create_issue": HealthResult(tool_id="create_issue", healthy=True, status_code=200),
            }
        )

        await loop.start()
        await asyncio.sleep(0.1)
        await loop.stop()

        state = loop.get_state()
        assert state.reconcile_count >= 1

    @pytest.mark.asyncio
    async def test_reconcile_loop_coexists_with_async_work(self, tmp_path):
        """ReconcileLoop should not block other async tasks on the same loop."""
        loop = ReconcileLoop(
            project_root=str(tmp_path),
            actions=[{"name": "tool_a", "method": "GET", "host": "api.example.com", "path": "/a"}],
            risk_tiers={"tool_a": "medium"},
            config=WatchConfig(probe_intervals={"medium": 1}),
        )
        loop._prober.probe_due_tools = AsyncMock(
            return_value={
                "tool_a": HealthResult(tool_id="tool_a", healthy=True, status_code=200),
            }
        )

        # Start reconcile loop
        await loop.start()

        # Do other async work concurrently (simulating MCP tool call handling)
        other_work_completed = False

        async def other_work():
            nonlocal other_work_completed
            await asyncio.sleep(0.1)
            other_work_completed = True

        await other_work()

        await loop.stop()

        assert other_work_completed
        assert loop.get_state().reconcile_count >= 1


class TestRunMcpServerWithWatch:
    """Tests for run_mcp_server --watch integration."""

    def test_run_mcp_server_accepts_watch_params(self):
        """run_mcp_server should accept watch and watch_config params."""
        import inspect

        from toolwright.mcp.server import run_mcp_server

        sig = inspect.signature(run_mcp_server)
        assert "watch" in sig.parameters
        assert "watch_config_path" in sig.parameters

    def test_run_mcp_serve_accepts_watch_params(self):
        """run_mcp_serve should accept watch and watch_config params."""
        import inspect

        from toolwright.cli.mcp import run_mcp_serve

        sig = inspect.signature(run_mcp_serve)
        assert "watch" in sig.parameters
        assert "watch_config_path" in sig.parameters


class TestWatchConfigLoading:
    """Tests for WatchConfig loading from --watch-config path."""

    def test_loads_config_from_yaml(self, tmp_path):
        config_path = tmp_path / "watch.yaml"
        config_path.write_text(
            "auto_heal: off\n"
            "probe_intervals:\n"
            "  critical: 60\n"
            "  high: 180\n"
            "max_concurrent_probes: 3\n"
        )

        config = WatchConfig.from_yaml(str(config_path))
        assert config.auto_heal.value == "off"
        assert config.probe_intervals["critical"] == 60
        assert config.max_concurrent_probes == 3

    def test_defaults_when_file_missing(self, tmp_path):
        config = WatchConfig.from_yaml(str(tmp_path / "nonexistent.yaml"))
        assert config.auto_heal.value == "safe"
        assert config.probe_intervals["medium"] == 600

    def test_default_watch_yaml_path(self, tmp_path):
        """Default watch config should be .toolwright/watch.yaml."""
        default_path = tmp_path / ".toolwright" / "watch.yaml"
        default_path.parent.mkdir(parents=True)
        default_path.write_text("auto_heal: all\n")

        config = WatchConfig.from_yaml(str(default_path))
        assert config.auto_heal.value == "all"


class TestServeCommandWatchOptions:
    """Tests for --watch and --watch-config CLI options on serve command."""

    def test_serve_command_has_watch_option(self):
        """The serve command should have --watch and --watch-config options."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "--watch" in result.output
        # --watch-config is hidden (advanced); verify it's accepted
        result2 = runner.invoke(cli, ["serve", "--watch-config", "watch.yaml", "--help"])
        assert result2.exit_code == 0


class TestServeAutoHealFlag:
    """Tests for --auto-heal CLI option on serve command."""

    def test_auto_heal_accepted(self):
        """serve should accept --auto-heal option (hidden but functional)."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--auto-heal", "safe", "--help"])
        assert result.exit_code == 0

    def test_auto_heal_without_watch_errors(self):
        """Using --auto-heal without --watch should exit with error code 2."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--auto-heal", "safe"])
        assert result.exit_code == 2
        assert "--watch" in result.output

    def test_auto_heal_choices_validated(self):
        """--auto-heal should reject invalid choices."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--auto-heal", "invalid"])
        assert result.exit_code != 0
