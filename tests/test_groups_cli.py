"""Tests for groups CLI commands."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli


def _write_toolpack_with_groups(tmp_path: Path) -> Path:
    """Write a minimal toolpack with groups.json."""
    toolpack_dir = tmp_path / "toolpack"
    artifact_dir = toolpack_dir / "artifact"
    artifact_dir.mkdir(parents=True)

    tools = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {"name": "get_products", "method": "GET", "path": "/products", "host": "api.example.com", "signature_id": "sig_gp", "tool_id": "sig_gp", "input_schema": {"type": "object", "properties": {}}},
            {"name": "create_product", "method": "POST", "path": "/products", "host": "api.example.com", "signature_id": "sig_cp", "tool_id": "sig_cp", "input_schema": {"type": "object", "properties": {}}},
            {"name": "get_orders", "method": "GET", "path": "/orders", "host": "api.example.com", "signature_id": "sig_go", "tool_id": "sig_go", "input_schema": {"type": "object", "properties": {}}},
        ],
    }
    (artifact_dir / "tools.json").write_text(json.dumps(tools))

    groups = {
        "groups": [
            {"name": "orders", "tools": ["get_orders"], "path_prefix": "/orders", "description": "Orders endpoints (1 tools)"},
            {"name": "products", "tools": ["get_products", "create_product"], "path_prefix": "/products", "description": "Products endpoints (2 tools)"},
        ],
        "ungrouped": [],
        "generated_from": "auto",
    }
    (artifact_dir / "groups.json").write_text(json.dumps(groups))

    (artifact_dir / "toolsets.yaml").write_text(yaml.safe_dump({"version": "1.0.0", "schema_version": "1.0", "toolsets": {}}))
    (artifact_dir / "policy.yaml").write_text(yaml.safe_dump({"version": "1.0.0", "schema_version": "1.0", "name": "Test", "default_action": "allow", "rules": []}))
    (artifact_dir / "baseline.json").write_text(json.dumps({"version": "1.0.0", "schema_version": "1.0"}))

    toolpack_path = toolpack_dir / "toolpack.yaml"
    toolpack_path.write_text(yaml.safe_dump({
        "version": "1.0.0",
        "schema_version": "1.0",
        "toolpack_id": "tp_test",
        "created_at": "2026-01-01T00:00:00",
        "capture_id": "cap_test",
        "artifact_id": "art_test",
        "scope": "default",
        "allowed_hosts": ["api.example.com"],
        "origin": {"start_url": "https://api.example.com", "name": "Test"},
        "paths": {
            "tools": "artifact/tools.json",
            "toolsets": "artifact/toolsets.yaml",
            "policy": "artifact/policy.yaml",
            "baseline": "artifact/baseline.json",
            "groups": "artifact/groups.json",
        },
    }))
    return toolpack_path


def test_groups_list_output(tmp_path: Path):
    """groups list shows group names and counts."""
    toolpack_path = _write_toolpack_with_groups(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["groups", "list", "--toolpack", str(toolpack_path)])
    assert result.exit_code == 0
    assert "products" in result.output
    assert "orders" in result.output
    assert "2 tools" in result.output or "2" in result.output


def test_groups_show_existing(tmp_path: Path):
    """groups show <name> lists tools in the group."""
    toolpack_path = _write_toolpack_with_groups(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["groups", "show", "products", "--toolpack", str(toolpack_path)])
    assert result.exit_code == 0
    assert "get_products" in result.output
    assert "create_product" in result.output


def test_groups_show_nonexistent(tmp_path: Path):
    """groups show with wrong name gives error with suggestion."""
    toolpack_path = _write_toolpack_with_groups(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["groups", "show", "prodcts", "--toolpack", str(toolpack_path)])
    assert result.exit_code != 0
    assert "prodcts" in result.output


def test_groups_list_no_groups_file(tmp_path: Path):
    """groups list gracefully handles missing groups.json."""
    toolpack_path = _write_toolpack_with_groups(tmp_path)
    # Remove groups.json
    groups_file = toolpack_path.parent / "artifact" / "groups.json"
    groups_file.unlink()
    runner = CliRunner()
    result = runner.invoke(cli, ["groups", "list", "--toolpack", str(toolpack_path)])
    assert "No tool groups found" in result.output or result.exit_code != 0
