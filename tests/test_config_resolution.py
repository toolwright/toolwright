"""Tests for config command path resolution."""

from __future__ import annotations

from pathlib import Path

from toolwright.utils.config import build_mcp_config_payload


def test_command_defaults_to_toolwright_not_absolute_path(
    tmp_path: Path,
) -> None:
    """The command field should be 'toolwright', not an absolute .venv path."""
    toolpack = tmp_path / "toolpack.yaml"
    toolpack.write_text("toolpack_id: tp_test\n")

    payload = build_mcp_config_payload(toolpack_path=toolpack, server_name="tp_test")
    assert payload["mcpServers"]["tp_test"]["command"] == "toolwright"


def test_root_points_to_parent_toolwright_dir_not_nested(
    tmp_path: Path,
) -> None:
    """--root should point to the .toolwright state root, not a nested .toolwright inside the toolpack dir.

    Given: .toolwright/toolpacks/github/toolpack.yaml
    The --root arg should be .toolwright, NOT .toolwright/toolpacks/github/.toolwright
    """
    tw_root = tmp_path / ".toolwright"
    toolpack_dir = tw_root / "toolpacks" / "github"
    toolpack_dir.mkdir(parents=True)
    toolpack = toolpack_dir / "toolpack.yaml"
    toolpack.write_text("toolpack_id: github\n")

    payload = build_mcp_config_payload(toolpack_path=toolpack, server_name="github")
    args = payload["mcpServers"]["github"]["args"]
    root_idx = args.index("--root")
    root_value = args[root_idx + 1]
    assert root_value == str(tw_root.resolve())


def test_command_override_parameter(tmp_path: Path) -> None:
    """When command_override is provided, use it instead of default."""
    toolpack = tmp_path / "toolpack.yaml"
    toolpack.write_text("toolpack_id: tp_test\n")

    payload = build_mcp_config_payload(
        toolpack_path=toolpack, server_name="tp_test", command_override="/usr/local/bin/tw"
    )
    assert payload["mcpServers"]["tp_test"]["command"] == "/usr/local/bin/tw"


def test_root_fallback_when_not_in_standard_layout(tmp_path: Path) -> None:
    """When toolpack.yaml is NOT inside a .toolwright/toolpacks/<name>/ layout,
    fall back to toolpack_dir/.toolwright as before."""
    toolpack = tmp_path / "my-project" / "toolpack.yaml"
    toolpack.parent.mkdir(parents=True)
    toolpack.write_text("toolpack_id: custom\n")

    payload = build_mcp_config_payload(toolpack_path=toolpack, server_name="custom")
    args = payload["mcpServers"]["custom"]["args"]
    root_idx = args.index("--root")
    root_value = args[root_idx + 1]
    # Should fall back to the toolpack dir's parent .toolwright
    assert root_value == str((tmp_path / "my-project" / ".toolwright").resolve())
