"""Tests for gate --by-group integration."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli


def _write_full_toolpack(tmp_path: Path) -> Path:
    """Write a toolpack with tools, groups, and pending lockfile."""
    toolpack_dir = tmp_path / "toolpack"
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    artifact_dir.mkdir(parents=True)
    lockfile_dir.mkdir(parents=True)

    tools = {
        "version": "1.0.0", "schema_version": "1.0", "name": "Test",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {"name": "get_products", "method": "GET", "path": "/products", "host": "api.example.com", "signature_id": "sig_gp", "tool_id": "sig_gp", "input_schema": {"type": "object", "properties": {}}, "risk_tier": "low"},
            {"name": "create_product", "method": "POST", "path": "/products", "host": "api.example.com", "signature_id": "sig_cp", "tool_id": "sig_cp", "input_schema": {"type": "object", "properties": {}}, "risk_tier": "medium"},
            {"name": "get_orders", "method": "GET", "path": "/orders", "host": "api.example.com", "signature_id": "sig_go", "tool_id": "sig_go", "input_schema": {"type": "object", "properties": {}}, "risk_tier": "low"},
        ],
    }
    (artifact_dir / "tools.json").write_text(json.dumps(tools))
    (artifact_dir / "toolsets.yaml").write_text(yaml.safe_dump({"version": "1.0.0", "schema_version": "1.0", "toolsets": {"readonly": {"actions": ["get_products", "get_orders"]}}}))
    (artifact_dir / "policy.yaml").write_text(yaml.safe_dump({"version": "1.0.0", "schema_version": "1.0", "name": "Test", "default_action": "allow", "rules": []}))
    (artifact_dir / "baseline.json").write_text(json.dumps({"version": "1.0.0", "schema_version": "1.0"}))
    (artifact_dir / "groups.json").write_text(json.dumps({
        "groups": [
            {"name": "orders", "tools": ["get_orders"], "path_prefix": "/orders", "description": "Orders (1 tools)"},
            {"name": "products", "tools": ["get_products", "create_product"], "path_prefix": "/products", "description": "Products (2 tools)"},
        ],
        "ungrouped": [],
        "generated_from": "auto",
    }))

    # Create a pending lockfile
    (lockfile_dir / "toolwright.lock.pending.yaml").write_text(yaml.safe_dump({
        "version": "1.0.0", "schema_version": "1.0", "tools": {},
    }))

    toolpack_path = toolpack_dir / "toolpack.yaml"
    toolpack_path.write_text(yaml.safe_dump({
        "version": "1.0.0", "schema_version": "1.0",
        "toolpack_id": "tp_test", "created_at": "2026-01-01T00:00:00",
        "capture_id": "cap_test", "artifact_id": "art_test", "scope": "default",
        "allowed_hosts": ["api.example.com"],
        "origin": {"start_url": "https://api.example.com"},
        "paths": {
            "tools": "artifact/tools.json", "toolsets": "artifact/toolsets.yaml",
            "policy": "artifact/policy.yaml", "baseline": "artifact/baseline.json",
            "groups": "artifact/groups.json",
            "lockfiles": {"pending": "lockfile/toolwright.lock.pending.yaml"},
        },
    }))
    return toolpack_path


def test_gate_status_by_group(tmp_path: Path):
    """gate status --by-group shows per-group summary."""
    toolpack_path = _write_full_toolpack(tmp_path)
    runner = CliRunner()
    # First sync to create tool entries in lockfile
    runner.invoke(cli, ["gate", "sync", "--toolpack", str(toolpack_path)])

    result = runner.invoke(cli, ["gate", "status", "--by-group", "--toolpack", str(toolpack_path)])
    assert result.exit_code == 0
    assert "products" in result.output
    assert "orders" in result.output
