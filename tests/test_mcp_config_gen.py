"""Tests for MCP client config generation."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.cli.init import _build_mcp_client_config


def _setup_toolpack(tmp_path: Path) -> Path:
    """Create a minimal toolpack directory with artifacts."""
    tp_dir = tmp_path / "tp_test"
    tp_dir.mkdir()
    artifact_dir = tp_dir / "artifact"
    artifact_dir.mkdir()

    toolpack_file = tp_dir / "toolpack.yaml"
    toolpack_file.write_text("toolpack_id: tp_test\n")

    (artifact_dir / "tools.json").write_text('{"actions": []}')
    (artifact_dir / "policy.yaml").write_text("name: test\n")

    return toolpack_file


def test_claude_config_format(tmp_path: Path) -> None:
    tp = _setup_toolpack(tmp_path)
    config = _build_mcp_client_config(tp, "claude")
    assert "mcpServers" in config
    assert "toolwright" in config["mcpServers"]
    server = config["mcpServers"]["toolwright"]
    assert server["command"] == "toolwright"
    assert "run" in server["args"]
    assert "--toolpack" in server["args"]


def test_cursor_config_format(tmp_path: Path) -> None:
    tp = _setup_toolpack(tmp_path)
    config = _build_mcp_client_config(tp, "cursor")
    assert "mcpServers" in config
    assert "toolwright" in config["mcpServers"]


def test_generic_config_format(tmp_path: Path) -> None:
    tp = _setup_toolpack(tmp_path)
    config = _build_mcp_client_config(tp, "generic")
    assert "server" in config
    assert config["server"]["transport"] == "stdio"
    assert "toolwright" in config["server"]["command"]


def test_config_includes_tools_path(tmp_path: Path) -> None:
    tp = _setup_toolpack(tmp_path)
    config = _build_mcp_client_config(tp, "claude")
    args = config["mcpServers"]["toolwright"]["args"]
    assert "--tools" in args


def test_config_includes_policy_path(tmp_path: Path) -> None:
    tp = _setup_toolpack(tmp_path)
    config = _build_mcp_client_config(tp, "claude")
    args = config["mcpServers"]["toolwright"]["args"]
    assert "--policy" in args


def test_config_without_artifacts(tmp_path: Path) -> None:
    """Config should still work even without tools/policy files."""
    tp_dir = tmp_path / "tp_empty"
    tp_dir.mkdir()
    tp_file = tp_dir / "toolpack.yaml"
    tp_file.write_text("toolpack_id: tp_empty\n")

    config = _build_mcp_client_config(tp_file, "claude")
    args = config["mcpServers"]["toolwright"]["args"]
    # Should still have --toolpack but not --tools or --policy
    assert "--toolpack" in args


def test_config_is_valid_json(tmp_path: Path) -> None:
    tp = _setup_toolpack(tmp_path)
    config = _build_mcp_client_config(tp, "claude")
    # Verify it round-trips through JSON
    json_str = json.dumps(config, indent=2)
    parsed = json.loads(json_str)
    assert parsed == config
