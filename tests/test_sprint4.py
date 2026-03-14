"""Tests for Sprint 4: Startup Experience + Golden Path.

Covers: smart gate defaults, config auto-install, rich startup card.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# 4b: Smart Gate Defaults
# ---------------------------------------------------------------------------


class TestSmartGateDefaults:
    """Risk-based auto-approval in ship flow."""

    def test_low_risk_auto_approved(self) -> None:
        """LOW risk tools should be auto-approved with risk_policy provenance."""
        from toolwright.core.approval.smart_gate import classify_approval

        result = classify_approval("low")
        assert result.auto_approve is True
        assert result.approved_by == "risk_policy:low"

    def test_medium_risk_auto_approved(self) -> None:
        """MEDIUM risk tools should be auto-approved with risk_policy provenance."""
        from toolwright.core.approval.smart_gate import classify_approval

        result = classify_approval("medium")
        assert result.auto_approve is True
        assert result.approved_by == "risk_policy:medium"

    def test_high_risk_prompts(self) -> None:
        """HIGH risk tools should prompt, default Yes."""
        from toolwright.core.approval.smart_gate import classify_approval

        result = classify_approval("high")
        assert result.auto_approve is False
        assert result.default_yes is True

    def test_critical_risk_prompts_default_no(self) -> None:
        """CRITICAL risk tools should prompt, default No."""
        from toolwright.core.approval.smart_gate import classify_approval

        result = classify_approval("critical")
        assert result.auto_approve is False
        assert result.default_yes is False

    def test_unknown_risk_treated_as_high(self) -> None:
        """Unknown risk tiers should be treated as high (prompt, default Yes)."""
        from toolwright.core.approval.smart_gate import classify_approval

        result = classify_approval("unknown")
        assert result.auto_approve is False
        assert result.default_yes is True


# ---------------------------------------------------------------------------
# 4d: Client Config Auto-Install
# ---------------------------------------------------------------------------


class TestMCPClientDetection:
    """Detect MCP client config files on the filesystem."""

    def test_detect_claude_desktop_macos(self, tmp_path: Path) -> None:
        """Should detect Claude Desktop on macOS."""
        from toolwright.utils.mcp_clients import detect_mcp_clients

        config_dir = tmp_path / "Library" / "Application Support" / "Claude"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "claude_desktop_config.json"
        config_file.write_text("{}")

        with patch("toolwright.utils.mcp_clients.platform") as mock_platform, \
             patch.dict(os.environ, {"HOME": str(tmp_path)}):
            mock_platform.system.return_value = "Darwin"
            clients = detect_mcp_clients(home_override=tmp_path)

        names = [c.name for c in clients]
        assert "Claude Desktop" in names

    def test_detect_cursor(self, tmp_path: Path) -> None:
        """Should detect Cursor."""
        from toolwright.utils.mcp_clients import detect_mcp_clients

        config_dir = tmp_path / ".cursor"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "mcp.json"
        config_file.write_text("{}")

        clients = detect_mcp_clients(home_override=tmp_path)
        names = [c.name for c in clients]
        assert "Cursor" in names

    def test_no_clients_found(self, tmp_path: Path) -> None:
        """Should return empty list when no clients found."""
        from toolwright.utils.mcp_clients import detect_mcp_clients

        clients = detect_mcp_clients(home_override=tmp_path)
        assert clients == []

    def test_install_config_creates_backup(self, tmp_path: Path) -> None:
        """Installing config should create a .bak file first."""
        from toolwright.utils.mcp_clients import MCPClient, install_config

        config_file = tmp_path / "claude_desktop_config.json"
        config_file.write_text('{"mcpServers": {}}')

        client = MCPClient(name="Test", config_path=config_file)
        install_config(client, server_name="toolwright-test", toolpack_path=Path("/fake/toolpack.yaml"))

        assert (tmp_path / "claude_desktop_config.json.bak").exists()

    def test_install_config_merges_server(self, tmp_path: Path) -> None:
        """Installing config should merge the new server into existing config."""
        from toolwright.utils.mcp_clients import MCPClient, install_config

        config_file = tmp_path / "claude_desktop_config.json"
        config_file.write_text('{"mcpServers": {"existing": {}}}')

        client = MCPClient(name="Test", config_path=config_file)
        install_config(client, server_name="toolwright-test", toolpack_path=Path("/fake/toolpack.yaml"))

        data = json.loads(config_file.read_text())
        assert "existing" in data["mcpServers"]
        assert "toolwright-test" in data["mcpServers"]

    def test_install_config_refuses_on_parse_error(self, tmp_path: Path) -> None:
        """Should refuse to install if existing config is malformed."""
        from toolwright.utils.mcp_clients import MCPClient, install_config

        config_file = tmp_path / "claude_desktop_config.json"
        config_file.write_text("not json")

        client = MCPClient(name="Test", config_path=config_file)
        with pytest.raises(ValueError, match="parse"):
            install_config(client, server_name="toolwright-test", toolpack_path=Path("/fake/toolpack.yaml"))

    def test_uninstall_config(self, tmp_path: Path) -> None:
        """Should remove the server entry from config."""
        from toolwright.utils.mcp_clients import MCPClient, uninstall_config

        config_file = tmp_path / "claude_desktop_config.json"
        config_file.write_text('{"mcpServers": {"toolwright-test": {}, "other": {}}}')

        client = MCPClient(name="Test", config_path=config_file)
        uninstall_config(client, server_name="toolwright-test")

        data = json.loads(config_file.read_text())
        assert "toolwright-test" not in data["mcpServers"]
        assert "other" in data["mcpServers"]


# ---------------------------------------------------------------------------
# 4e: Rich Startup Card
# ---------------------------------------------------------------------------


class TestStartupCard:
    """Startup card rendering."""

    def test_startup_card_has_tool_count(self) -> None:
        """Startup card should include tool count."""
        from toolwright.mcp.startup_card import render_startup_card

        card = render_startup_card(
            name="Test API",
            tools={"read": 5, "write": 3, "admin": 1},
            risk_counts={"low": 3, "medium": 4, "high": 1, "critical": 1},
            context_tokens=1080,
            tokens_per_tool=120,
            dashboard_url="http://localhost:8745/?t=tw_abc123",
            mcp_url="http://localhost:8745/mcp",
        )
        assert "9" in card  # total tools
        assert "5 read" in card

    def test_startup_card_has_dashboard_url(self) -> None:
        """Startup card should include dashboard URL."""
        from toolwright.mcp.startup_card import render_startup_card

        card = render_startup_card(
            name="Test API",
            tools={"read": 5, "write": 3, "admin": 1},
            risk_counts={"low": 3, "medium": 4, "high": 1, "critical": 1},
            context_tokens=1080,
            tokens_per_tool=120,
            dashboard_url="http://localhost:8745/?t=tw_abc123",
            mcp_url="http://localhost:8745/mcp",
        )
        assert "localhost:8745" in card

    def test_startup_card_stdio_no_urls(self) -> None:
        """Startup card for stdio should not include dashboard/MCP URLs."""
        from toolwright.mcp.startup_card import render_startup_card

        card = render_startup_card(
            name="Test API",
            tools={"read": 5, "write": 3, "admin": 1},
            risk_counts={"low": 3, "medium": 4, "high": 1, "critical": 1},
            context_tokens=1080,
            tokens_per_tool=120,
        )
        assert "Dashboard" not in card
        assert "MCP" not in card or "mcp" not in card.lower() or "localhost" not in card


# ---------------------------------------------------------------------------
# 4a: Demo command --offline flag
# ---------------------------------------------------------------------------


class TestDemoOffline:
    """Demo --offline flag preserves old compile-only behavior."""

    def test_demo_offline_exits_zero(self) -> None:
        """toolwright demo --offline should work (compile only, no server)."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["demo", "--offline"])
        assert result.exit_code == 0, f"Failed: {result.output}"

    def test_demo_offline_produces_toolpack(self, tmp_path: Path) -> None:
        """--offline should produce a toolpack file."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["demo", "--offline", "--out", str(tmp_path)])
        assert result.exit_code == 0
        # Should have created toolpacks directory
        toolpack_dirs = list((tmp_path / "toolpacks").iterdir()) if (tmp_path / "toolpacks").exists() else []
        assert len(toolpack_dirs) > 0


# ---------------------------------------------------------------------------
# 4c: Ship accepts URL argument
# ---------------------------------------------------------------------------


class TestShipURL:
    """Ship command should accept an optional URL argument."""

    def test_ship_help_shows_url(self) -> None:
        """ship --help should mention URL argument."""
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["ship", "--help"])
        assert result.exit_code == 0
        assert "url" in result.output.lower() or "URL" in result.output
