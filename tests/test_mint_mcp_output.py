"""Tests for MCP integration output after mint."""

from __future__ import annotations

from toolwright.cli.mint import build_mcp_integration_output


def test_integration_output_mentions_config_command() -> None:
    """Output should guide users to generate a client config snippet."""
    output = build_mcp_integration_output(toolpack_path="/path/to/toolpack.yaml")
    assert "toolwright config" in output
    assert "--toolpack" in output


def test_integration_output_mentions_claude_desktop_config() -> None:
    """Output should mention where to paste config for Claude Desktop."""
    output = build_mcp_integration_output(toolpack_path="/path/to/toolpack.yaml")
    assert "claude_desktop_config.json" in output


def test_integration_output_uses_actual_path() -> None:
    """Output should include the actual toolpack path."""
    output = build_mcp_integration_output(toolpack_path="/my/custom/toolpack.yaml")
    assert "/my/custom/toolpack.yaml" in output
