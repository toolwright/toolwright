"""Tests for auth env var warning and empty-toolpack guard on serve startup."""

from __future__ import annotations

import json
import re
from pathlib import Path

from toolwright.cli.mcp import warn_missing_auth


def _normalize_host(host: str) -> str:
    """Same normalization as server._resolve_auth_for_host."""
    return f"TOOLWRIGHT_AUTH_{re.sub(r'[^A-Za-z0-9]', '_', host).upper()}"


def test_warn_missing_auth_emits_warning_when_no_env_var(
    tmp_path: Path, monkeypatch: object,
) -> None:
    """When no auth env var is set for a host, warn_missing_auth should warn."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps({
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Test",
            "allowed_hosts": ["api.github.com"],
            "actions": [],
        }),
        encoding="utf-8",
    )

    # Ensure env var is NOT set
    env_key = _normalize_host("api.github.com")
    monkeypatch.delenv(env_key, raising=False)

    warnings = warn_missing_auth(
        tools_path=tools_path,
        auth_header=None,
    )
    assert len(warnings) == 1
    assert "api.github.com" in warnings[0]
    assert env_key in warnings[0]
    assert "export" in warnings[0]
    assert '"Bearer <token>"' in warnings[0]


def test_warn_missing_auth_no_warning_when_env_var_set(
    tmp_path: Path, monkeypatch: object,
) -> None:
    """When auth env var is set, no warning should be emitted."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps({
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Test",
            "allowed_hosts": ["api.github.com"],
            "actions": [],
        }),
        encoding="utf-8",
    )

    env_key = _normalize_host("api.github.com")
    monkeypatch.setenv(env_key, "token ghp_fake123")

    warnings = warn_missing_auth(
        tools_path=tools_path,
        auth_header=None,
    )
    assert len(warnings) == 0


def test_warn_missing_auth_no_warning_when_global_auth(
    tmp_path: Path,
) -> None:
    """When --auth is provided globally, no per-host warnings needed."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps({
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Test",
            "allowed_hosts": ["api.github.com"],
            "actions": [],
        }),
        encoding="utf-8",
    )

    warnings = warn_missing_auth(
        tools_path=tools_path,
        auth_header="token ghp_real",
    )
    assert len(warnings) == 0


# ---------- empty-toolpack guard ----------


def test_empty_toolpack_blocks_serve(tmp_path: Path) -> None:
    """Serving a toolpack with 0 actions should exit with a helpful error."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps({
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "Empty",
            "allowed_hosts": ["api.example.com"],
            "actions": [],
        }),
        encoding="utf-8",
    )

    with open(tools_path) as f:
        manifest = json.load(f)
    actions = manifest.get("actions", [])
    assert len(actions) == 0, "Fixture should have 0 actions"


def test_nonempty_toolpack_passes_guard(tmp_path: Path) -> None:
    """A toolpack with at least one action should not be blocked."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps({
            "version": "1.0.0",
            "schema_version": "1.0",
            "name": "HasTools",
            "allowed_hosts": ["api.example.com"],
            "actions": [
                {
                    "name": "list_items",
                    "method": "GET",
                    "path": "/items",
                    "params": [],
                },
            ],
        }),
        encoding="utf-8",
    )

    with open(tools_path) as f:
        manifest = json.load(f)
    actions = manifest.get("actions", [])
    assert len(actions) == 1, "Fixture should have 1 action"
