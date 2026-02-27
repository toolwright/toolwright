"""Test helpers for creating toolpack fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from toolwright.cli.approve import sync_lockfile
from toolwright.core.toolpack import Toolpack, ToolpackOrigin, ToolpackPaths, write_toolpack


def write_demo_artifacts(artifact_dir: Path) -> dict[str, Path]:
    """Write a minimal deterministic artifact set and return paths."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    tools_path = artifact_dir / "tools.json"
    tools_path.write_text(
        """{\n"""
        """  "version": "1.0.0",\n"""
        """  "schema_version": "1.0",\n"""
        """  "name": "Demo Tools",\n"""
        """  "actions": [\n"""
        """    {\n"""
        """      "id": "get_users",\n"""
        """      "tool_id": "sig_get_users",\n"""
        """      "name": "get_users",\n"""
        """      "description": "Retrieve users",\n"""
        """      "endpoint_id": "ep_users",\n"""
        """      "signature_id": "sig_get_users",\n"""
        """      "method": "GET",\n"""
        """      "path": "/users",\n"""
        """      "host": "api.example.com",\n"""
        """      "input_schema": {\n"""
        """        "type": "object",\n"""
        """        "properties": {}\n"""
        """      },\n"""
        """      "risk_tier": "low",\n"""
        """      "confirmation_required": "never",\n"""
        """      "rate_limit_per_minute": 60,\n"""
        """      "tags": []\n"""
        """    }\n"""
        """  ]\n"""
        """}\n"""
    )
    toolsets_path = artifact_dir / "toolsets.yaml"
    toolsets_path.write_text(
        "version: '1.0.0'\n"
        "schema_version: '1.0'\n"
        "toolsets:\n"
        "  readonly:\n"
        "    actions:\n"
        "      - get_users\n"
    )
    policy_path = artifact_dir / "policy.yaml"
    policy_path.write_text(
        "version: '1.0.0'\n"
        "schema_version: '1.0'\n"
        "name: Demo Policy\n"
        "default_action: deny\n"
        "rules: []\n"
    )
    baseline_path = artifact_dir / "baseline.json"
    baseline_path.write_text("{\"schema_version\": \"1.0\", \"endpoints\": []}")
    contracts_path = artifact_dir / "contracts.yaml"
    contracts_path.write_text("version: '1.0.0'\nkind: contracts\ncontracts: []\n")
    contract_yaml_path = artifact_dir / "contract.yaml"
    contract_yaml_path.write_text("openapi: 3.1.0\n")
    contract_json_path = artifact_dir / "contract.json"
    contract_json_path.write_text("{\"openapi\": \"3.1.0\"}")
    return {
        "tools": tools_path,
        "toolsets": toolsets_path,
        "policy": policy_path,
        "baseline": baseline_path,
        "contracts": contracts_path,
        "contract_yaml": contract_yaml_path,
        "contract_json": contract_json_path,
    }


def write_demo_toolpack(tmp_path: Path) -> Path:
    """Create a minimal toolpack with pending lockfile and return toolpack.yaml path."""
    toolpack_id = "tp_demo"
    toolpack_dir = tmp_path / "toolpacks" / toolpack_id
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    lockfile_dir.mkdir(parents=True, exist_ok=True)
    artifacts = write_demo_artifacts(artifact_dir)

    pending_lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
    sync_lockfile(
        tools_path=str(artifacts["tools"]),
        policy_path=str(artifacts["policy"]),
        toolsets_path=str(artifacts["toolsets"]),
        lockfile_path=str(pending_lockfile),
        capture_id="cap_demo",
        scope="agent_safe_readonly",
        deterministic=True,
    )

    lockfiles: dict[str, str] = {
        "pending": str(pending_lockfile.relative_to(toolpack_dir)),
    }

    toolpack = Toolpack(
        toolpack_id=toolpack_id,
        created_at=datetime(2026, 2, 6, tzinfo=UTC),
        capture_id="cap_demo",
        artifact_id="art_demo",
        scope="agent_safe_readonly",
        allowed_hosts=["api.example.com"],
        origin=ToolpackOrigin(start_url="https://app.example.com"),
        paths=ToolpackPaths(
            tools=str(artifacts["tools"].relative_to(toolpack_dir)),
            toolsets=str(artifacts["toolsets"].relative_to(toolpack_dir)),
            policy=str(artifacts["policy"].relative_to(toolpack_dir)),
            baseline=str(artifacts["baseline"].relative_to(toolpack_dir)),
            contracts=str(artifacts["contracts"].relative_to(toolpack_dir)),
            contract_yaml=str(artifacts["contract_yaml"].relative_to(toolpack_dir)),
            contract_json=str(artifacts["contract_json"].relative_to(toolpack_dir)),
            lockfiles=lockfiles,
        ),
    )

    toolpack_file = toolpack_dir / "toolpack.yaml"
    write_toolpack(toolpack, toolpack_file)
    return toolpack_file


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        raise ValueError("Expected mapping")
    return payload
