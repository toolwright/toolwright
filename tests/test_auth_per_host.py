"""Tests for per-host auth env var resolution (Task 7.7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolwright.mcp.server import ToolwrightMCPServer


def _write_minimal_tools(tmp_path: Path) -> Path:
    """Create a minimal tools.json for server instantiation."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps({
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test",
        "allowed_hosts": [],
        "actions": [],
    }))
    return tools_path


def test_per_host_env_var_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOOLWRIGHT_AUTH_API_EXAMPLE_COM should resolve for host api.example.com
    when no global auth_header is set."""
    monkeypatch.setenv("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", "Bearer host-token-abc")

    tools_path = _write_minimal_tools(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path)

    result = server._resolve_auth_for_host("api.example.com")
    assert result == "Bearer host-token-abc"


def test_global_fallback_when_no_per_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When only global auth_header is set (no per-host env var),
    the global value should be returned for any host."""
    # Ensure no per-host env var is set
    monkeypatch.delenv("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", raising=False)

    tools_path = _write_minimal_tools(tmp_path)
    server = ToolwrightMCPServer(
        tools_path=tools_path,
        auth_header="Bearer global-token",
    )

    result = server._resolve_auth_for_host("api.example.com")
    assert result == "Bearer global-token"


def test_explicit_auth_overrides_per_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both global auth_header (from --auth) and per-host env var are set,
    the global auth_header should win because --auth is the explicit override."""
    monkeypatch.setenv("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", "Bearer per-host-token")

    tools_path = _write_minimal_tools(tmp_path)
    server = ToolwrightMCPServer(
        tools_path=tools_path,
        auth_header="Bearer global-explicit",
    )

    result = server._resolve_auth_for_host("api.example.com")
    assert result == "Bearer global-explicit"


def test_no_auth_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When neither global auth nor per-host env var is set, return None."""
    monkeypatch.delenv("TOOLWRIGHT_AUTH_API_EXAMPLE_COM", raising=False)

    tools_path = _write_minimal_tools(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path)

    result = server._resolve_auth_for_host("api.example.com")
    assert result is None
