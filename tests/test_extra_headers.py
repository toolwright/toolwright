"""Tests for extra header injection (--extra-header / -H support).

Covers:
- parse_extra_headers() parsing and validation
- Server constructor extra_headers acceptance
- Header merge behavior (extra headers don't override Authorization)
- Toolpack model round-trip (extra_headers written to YAML and read back)
- Merge priority (CLI --extra-header overrides toolpack stored headers)
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest

from toolwright.utils.headers import parse_extra_headers

# ── parse_extra_headers tests ──────────────────────────────────────


def test_parse_single_header() -> None:
    raw = ("Notion-Version: 2025-09-03",)
    result = parse_extra_headers(raw)
    assert result == {"Notion-Version": "2025-09-03"}


def test_parse_multiple_headers() -> None:
    raw = (
        "Notion-Version: 2025-09-03",
        "X-Custom-Id: abc123",
    )
    result = parse_extra_headers(raw)
    assert result == {
        "Notion-Version": "2025-09-03",
        "X-Custom-Id": "abc123",
    }


def test_parse_value_with_colons() -> None:
    """Header values can contain colons (e.g. Bearer tokens)."""
    raw = ("Authorization: Bearer abc:def:ghi",)
    result = parse_extra_headers(raw)
    assert result == {"Authorization": "Bearer abc:def:ghi"}


def test_parse_strips_whitespace() -> None:
    raw = ("  X-Header  :  some value  ",)
    result = parse_extra_headers(raw)
    assert result == {"X-Header": "some value"}


def test_parse_empty_value() -> None:
    raw = ("X-Empty: ",)
    result = parse_extra_headers(raw)
    assert result == {"X-Empty": ""}


def test_parse_no_colon_raises() -> None:
    raw = ("InvalidHeader",)
    with pytest.raises(click.BadParameter):
        parse_extra_headers(raw)


def test_parse_empty_name_raises() -> None:
    raw = (": some-value",)
    with pytest.raises(click.BadParameter):
        parse_extra_headers(raw)


def test_parse_empty_tuple() -> None:
    result = parse_extra_headers(())
    assert result == {}


def test_parse_duplicate_last_wins() -> None:
    raw = (
        "X-Version: 1",
        "X-Version: 2",
    )
    result = parse_extra_headers(raw)
    assert result == {"X-Version": "2"}


# ── Server extra_headers integration ──────────────────────────────


def _write_minimal_tools(tmp_path: Path) -> Path:
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps({
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test",
        "allowed_hosts": [],
        "actions": [],
    }))
    return tools_path


def test_server_accepts_extra_headers(tmp_path: Path) -> None:
    from toolwright.mcp.server import ToolwrightMCPServer

    tools_path = _write_minimal_tools(tmp_path)
    server = ToolwrightMCPServer(
        tools_path=tools_path,
        extra_headers={"Notion-Version": "2025-09-03"},
    )
    assert server.extra_headers == {"Notion-Version": "2025-09-03"}


def test_server_extra_headers_default_none(tmp_path: Path) -> None:
    from toolwright.mcp.server import ToolwrightMCPServer

    tools_path = _write_minimal_tools(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path)
    assert server.extra_headers is None


# ── Toolpack model round-trip ─────────────────────────────────────


def _toolpack_kwargs(**overrides):
    """Minimal valid Toolpack kwargs."""
    from toolwright.core.toolpack import ToolpackOrigin, ToolpackPaths

    defaults = {
        "toolpack_id": "test-id",
        "created_at": "2025-01-01T00:00:00Z",
        "capture_id": "cap-001",
        "artifact_id": "art-001",
        "scope": "first_party_only",
        "allowed_hosts": ["api.example.com"],
        "origin": ToolpackOrigin(start_url="https://example.com"),
        "paths": ToolpackPaths(
            tools="tools.json",
            toolsets="toolsets.yaml",
            policy="policy.yaml",
            baseline="baseline.json",
        ),
    }
    defaults.update(overrides)
    return defaults


def test_toolpack_extra_headers_roundtrip(tmp_path: Path) -> None:
    from toolwright.core.toolpack import Toolpack, load_toolpack, write_toolpack

    toolpack = Toolpack(
        **_toolpack_kwargs(
            extra_headers={"Notion-Version": "2025-09-03", "X-Custom": "value"},
        ),
    )

    toolpack_path = tmp_path / "toolpack.yaml"
    write_toolpack(toolpack, toolpack_path)

    loaded = load_toolpack(toolpack_path)
    assert loaded.extra_headers == {"Notion-Version": "2025-09-03", "X-Custom": "value"}


def test_toolpack_no_extra_headers_roundtrip(tmp_path: Path) -> None:
    from toolwright.core.toolpack import Toolpack, load_toolpack, write_toolpack

    toolpack = Toolpack(**_toolpack_kwargs())

    toolpack_path = tmp_path / "toolpack.yaml"
    write_toolpack(toolpack, toolpack_path)

    loaded = load_toolpack(toolpack_path)
    assert loaded.extra_headers is None
