"""Tests for MCP CLI path resolution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.cli.mcp import run_mcp_serve


def _write_toolpack_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    toolpack_dir = tmp_path / "toolpack"
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    artifact_dir.mkdir(parents=True)
    lockfile_dir.mkdir(parents=True)

    tools_path = artifact_dir / "tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "Demo",
                "allowed_hosts": ["api.example.com"],
                "actions": [
                    {
                        "name": "get_user",
                        "method": "GET",
                        "path": "/api/users/{id}",
                        "host": "api.example.com",
                        "signature_id": "sig_get_user",
                        "tool_id": "sig_get_user",
                        "input_schema": {"type": "object", "properties": {}},
                    }
                ],
            }
        )
    )

    toolsets_path = artifact_dir / "toolsets.yaml"
    toolsets_path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "toolsets": {"readonly": {"actions": ["get_user"]}},
            }
        )
    )

    policy_path = artifact_dir / "policy.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "Demo Policy",
                "default_action": "allow",
                "rules": [],
            }
        )
    )

    pending_lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
    pending_lockfile.write_text("version: '1.0.0'\nschema_version: '1.0'\ntools: {}\n")

    toolpack_path = toolpack_dir / "toolpack.yaml"
    toolpack_path.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "toolpack_id": "tp_demo",
                "created_at": "1970-01-01T00:00:00+00:00",
                "capture_id": "cap_demo",
                "artifact_id": "art_demo",
                "scope": "agent_safe_readonly",
                "allowed_hosts": ["api.example.com"],
                "origin": {"start_url": "https://example.com", "name": "Demo"},
                "paths": {
                    "tools": "artifact/tools.json",
                    "toolsets": "artifact/toolsets.yaml",
                    "policy": "artifact/policy.yaml",
                    "baseline": "artifact/baseline.json",
                    "lockfiles": {"pending": "lockfile/toolwright.lock.pending.yaml"},
                },
            },
            sort_keys=False,
        )
    )

    baseline_path = artifact_dir / "baseline.json"
    baseline_path.write_text("{}")
    return toolpack_path, tools_path, toolsets_path, policy_path


class TestMCPToolpackResolution:
    def test_toolpack_resolves_paths_and_defaults_readonly(
        self, tmp_path: Path, capsys
    ) -> None:
        toolpack_path, tools_path, toolsets_path, policy_path = _write_toolpack_fixture(tmp_path)

        with patch("toolwright.mcp.server.run_mcp_server") as mock_run:
            run_mcp_serve(
                tools_path=None,
                toolpack_path=str(toolpack_path),
                toolsets_path=None,
                toolset_name=None,
                policy_path=None,
                lockfile_path=None,
                base_url=None,
                auth_header=None,
                audit_log=None,
                dry_run=False,
                confirmation_store_path=".toolwright/confirmations.db",
                allow_private_cidrs=[],
                allow_redirects=False,
                verbose=False,
                unsafe_no_lockfile=True,
            )

        kwargs = mock_run.call_args.kwargs
        assert kwargs["tools_path"] == str(tools_path)
        assert kwargs["toolsets_path"] == str(toolsets_path)
        assert kwargs["policy_path"] == str(policy_path)
        assert kwargs["toolset_name"] == "readonly"
        assert kwargs["lockfile_path"] is None
        captured = capsys.readouterr()
        # Auth warning is expected when no auth env var is set
        assert "WARNING" in captured.err or captured.err == ""

    def test_explicit_tools_override_toolpack_tools(self, tmp_path: Path) -> None:
        toolpack_path, _tools_path, toolsets_path, _policy_path = _write_toolpack_fixture(tmp_path)
        override_tools = tmp_path / "override-tools.json"
        override_tools.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "schema_version": "1.0",
                    "actions": [{"name": "stub", "method": "GET", "path": "/stub"}],
                }
            )
        )

        with patch("toolwright.mcp.server.run_mcp_server") as mock_run:
            run_mcp_serve(
                tools_path=str(override_tools),
                toolpack_path=str(toolpack_path),
                toolsets_path=None,
                toolset_name=None,
                policy_path=None,
                lockfile_path=None,
                base_url=None,
                auth_header=None,
                audit_log=None,
                dry_run=False,
                confirmation_store_path=".toolwright/confirmations.db",
                allow_private_cidrs=[],
                allow_redirects=False,
                verbose=False,
                unsafe_no_lockfile=True,
            )

        kwargs = mock_run.call_args.kwargs
        assert kwargs["tools_path"] == str(override_tools)
        assert kwargs["toolsets_path"] == str(toolsets_path)

    def test_requires_tools_or_toolpack(self) -> None:
        with pytest.raises(SystemExit) as exc:
            run_mcp_serve(
                tools_path=None,
                toolpack_path=None,
                toolsets_path=None,
                toolset_name=None,
                policy_path=None,
                lockfile_path=None,
                base_url=None,
                auth_header=None,
                audit_log=None,
                dry_run=False,
                confirmation_store_path=".toolwright/confirmations.db",
                allow_private_cidrs=[],
                allow_redirects=False,
                verbose=False,
                unsafe_no_lockfile=False,
            )
        assert exc.value.code == 1


def test_runtime_lockfile_search_prefers_canonical_approved_name(tmp_path: Path) -> None:
    toolpack_path, _tools_path, _toolsets_path, _policy_path = _write_toolpack_fixture(tmp_path)
    toolpack_root = toolpack_path.parent
    canonical_approved = toolpack_root / "lockfile" / "toolwright.lock.approved.yaml"
    canonical_approved.write_text("version: '1.0.0'\nschema_version: '1.0'\ntools: {}\n")

    with patch("toolwright.mcp.server.run_mcp_server") as mock_run:
        run_mcp_serve(
            tools_path=None,
            toolpack_path=str(toolpack_path),
            toolsets_path=None,
            toolset_name=None,
            policy_path=None,
            lockfile_path=None,
            base_url=None,
            auth_header=None,
            audit_log=None,
            dry_run=False,
            confirmation_store_path=".toolwright/confirmations.db",
            allow_private_cidrs=[],
            allow_redirects=False,
            verbose=False,
            unsafe_no_lockfile=False,
        )

    kwargs = mock_run.call_args.kwargs
    assert kwargs["lockfile_path"] == str(canonical_approved)


def test_runtime_lockfile_search_falls_back_to_legacy_name(tmp_path: Path) -> None:
    toolpack_path, _tools_path, _toolsets_path, _policy_path = _write_toolpack_fixture(tmp_path)
    toolpack_root = toolpack_path.parent
    legacy_approved = toolpack_root / "lockfile" / "toolwright.lock.yaml"
    legacy_approved.write_text("version: '1.0.0'\nschema_version: '1.0'\ntools: {}\n")

    with patch("toolwright.mcp.server.run_mcp_server") as mock_run:
        run_mcp_serve(
            tools_path=None,
            toolpack_path=str(toolpack_path),
            toolsets_path=None,
            toolset_name=None,
            policy_path=None,
            lockfile_path=None,
            base_url=None,
            auth_header=None,
            audit_log=None,
            dry_run=False,
            confirmation_store_path=".toolwright/confirmations.db",
            allow_private_cidrs=[],
            allow_redirects=False,
            verbose=False,
            unsafe_no_lockfile=False,
        )

    kwargs = mock_run.call_args.kwargs
    assert kwargs["lockfile_path"] == str(legacy_approved)


def test_runtime_allows_pending_lockfile_when_toolset_is_fully_approved(tmp_path: Path) -> None:
    toolpack_path, _tools_path, _toolsets_path, _policy_path = _write_toolpack_fixture(tmp_path)
    toolpack_root = toolpack_path.parent
    pending_lockfile = toolpack_root / "lockfile" / "toolwright.lock.pending.yaml"

    pending_lockfile.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "tools": {
                    "sig_get_user": {
                        "tool_id": "sig_get_user",
                        "tool_version": 1,
                        "signature_id": "sig_get_user",
                        "endpoint_id": None,
                        "name": "get_user",
                        "method": "GET",
                        "path": "/api/users/{id}",
                        "host": "api.example.com",
                        "risk_tier": "low",
                        "toolsets": ["readonly", "write"],
                        "approved_toolsets": ["readonly"],
                        "status": "pending",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with patch("toolwright.mcp.server.run_mcp_server") as mock_run:
        run_mcp_serve(
            tools_path=None,
            toolpack_path=str(toolpack_path),
            toolsets_path=None,
            toolset_name=None,
            policy_path=None,
            lockfile_path=None,
            base_url=None,
            auth_header=None,
            audit_log=None,
            dry_run=False,
            confirmation_store_path=".toolwright/confirmations.db",
            allow_private_cidrs=[],
            allow_redirects=False,
            verbose=False,
            unsafe_no_lockfile=False,
        )

    kwargs = mock_run.call_args.kwargs
    assert kwargs["lockfile_path"] == str(pending_lockfile)


def test_runtime_rejects_pending_lockfile_when_toolset_not_approved(tmp_path: Path) -> None:
    toolpack_path, _tools_path, _toolsets_path, _policy_path = _write_toolpack_fixture(tmp_path)
    toolpack_root = toolpack_path.parent
    pending_lockfile = toolpack_root / "lockfile" / "toolwright.lock.pending.yaml"

    pending_lockfile.write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "tools": {
                    "sig_get_user": {
                        "tool_id": "sig_get_user",
                        "tool_version": 1,
                        "signature_id": "sig_get_user",
                        "endpoint_id": None,
                        "name": "get_user",
                        "method": "GET",
                        "path": "/api/users/{id}",
                        "host": "api.example.com",
                        "risk_tier": "low",
                        "toolsets": ["readonly", "write"],
                        "approved_toolsets": [],
                        "status": "pending",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with patch("toolwright.mcp.server.run_mcp_server"):
        with pytest.raises(SystemExit) as exc:
            run_mcp_serve(
                tools_path=None,
                toolpack_path=str(toolpack_path),
                toolsets_path=None,
                toolset_name=None,
                policy_path=None,
                lockfile_path=None,
                base_url=None,
                auth_header=None,
                audit_log=None,
                dry_run=False,
                confirmation_store_path=".toolwright/confirmations.db",
                allow_private_cidrs=[],
                allow_redirects=False,
                verbose=False,
                unsafe_no_lockfile=False,
            )
        assert exc.value.code == 1


def test_mcp_serve_missing_mcp_exact_error(tmp_path: Path, monkeypatch) -> None:
    toolpack_path, _tools_path, _toolsets_path, _policy_path = _write_toolpack_fixture(tmp_path)
    runner = CliRunner()

    monkeypatch.setattr("importlib.util.find_spec", lambda _name: None)
    monkeypatch.setattr("toolwright.mcp.server.run_mcp_server", lambda **_kwargs: None)

    result = runner.invoke(cli, ["serve", "--toolpack", str(toolpack_path)])

    assert result.exit_code != 0
    assert result.stdout == ""
    assert (
        result.stderr
        == 'Error: mcp not installed. Install with: pip install "toolwright[mcp]"\n'
    )
