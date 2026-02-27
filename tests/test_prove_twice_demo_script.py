"""Unit tests for the Prove Twice orchestration script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_script_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "prove_twice_demo.py"
    assert script_path.exists(), f"missing script under repo root: {script_path}"
    spec = importlib.util.spec_from_file_location("prove_twice_demo_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_arg_parser_supports_auth_refresh_scenario() -> None:
    mod = _load_script_module()
    parser = mod.build_arg_parser()
    args = parser.parse_args(["--scenario", "auth_refresh", "--workdir", "/tmp/demo"])
    assert args.scenario == "auth_refresh"


def test_build_scenario_auth_refresh_contains_refresh_paths() -> None:
    mod = _load_script_module()
    spec = mod.build_scenario("auth_refresh", 8787)
    assert spec.name == "auth_refresh"
    assert "/oauth/token" in spec.server_script
    assert "grant_type: refresh_token" in spec.prove_once_workflow_yaml
    assert "Orders loaded 3 total" in spec.prove_once_workflow_yaml
    assert spec.parity_assertion
    assert spec.prove_once_step_id


def test_pick_tool_call_prefers_non_auth_get_paths(tmp_path: Path) -> None:
    mod = _load_script_module()

    toolpack_dir = tmp_path / "toolpack"
    artifact_dir = toolpack_dir / "artifact"
    artifact_dir.mkdir(parents=True)
    tools_json = artifact_dir / "tools.json"
    tools_json.write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "name": "post_oauth_token",
                        "method": "POST",
                        "path": "/oauth/token",
                        "input_schema": {"required": ["grant_type", "refresh_token"]},
                    },
                    {
                        "name": "get_profile",
                        "method": "GET",
                        "path": "/api/profile",
                        "input_schema": {"required": []},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    toolpack_path = toolpack_dir / "toolpack.yaml"
    toolpack_path.write_text("version: '1.0.0'\n", encoding="utf-8")

    tool_name, args = mod.pick_tool_call(toolpack_path, preferred_paths=["/api/profile"])
    assert tool_name == "get_profile"
    assert args == {}


def test_pick_tool_call_honors_preference_order(tmp_path: Path) -> None:
    mod = _load_script_module()

    toolpack_dir = tmp_path / "toolpack"
    artifact_dir = toolpack_dir / "artifact"
    artifact_dir.mkdir(parents=True)
    tools_json = artifact_dir / "tools.json"
    tools_json.write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "name": "get_profile",
                        "method": "GET",
                        "path": "/api/profile",
                        "input_schema": {"required": []},
                    },
                    {
                        "name": "get_healthz",
                        "method": "GET",
                        "path": "/healthz",
                        "input_schema": {"required": []},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    toolpack_path = toolpack_dir / "toolpack.yaml"
    toolpack_path.write_text("version: '1.0.0'\n", encoding="utf-8")

    tool_name, args = mod.pick_tool_call(
        toolpack_path,
        preferred_paths=["/healthz", "/api/profile"],
    )
    assert tool_name == "get_healthz"
    assert args == {}


def test_build_scenario_rejects_unknown() -> None:
    mod = _load_script_module()
    with pytest.raises(ValueError, match="Unknown scenario"):
        mod.build_scenario("does_not_exist", 8787)
