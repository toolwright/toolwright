"""Tests for per-host auth header name resolution."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.core.toolpack import ToolpackAuthRequirement
from toolwright.mcp.server import ToolwrightMCPServer

# ------------------------------------------------------------------
# Model-level tests (ToolpackAuthRequirement field)
# ------------------------------------------------------------------


def test_auth_requirement_stores_header_name():
    """ToolpackAuthRequirement should store custom header names."""
    req = ToolpackAuthRequirement(
        host="shop.myshopify.com",
        scheme="api_key",
        location="header",
        header_name="X-Shopify-Access-Token",
        env_var_name="TOOLWRIGHT_AUTH_SHOP_MYSHOPIFY_COM",
    )
    assert req.header_name == "X-Shopify-Access-Token"


def test_auth_requirement_defaults_to_none():
    """header_name should default to None."""
    req = ToolpackAuthRequirement(
        host="api.github.com",
        scheme="bearer",
        location="header",
        env_var_name="TOOLWRIGHT_AUTH_API_GITHUB_COM",
    )
    assert req.header_name is None


# ------------------------------------------------------------------
# Server-level tests (_resolve_auth_header_name)
# ------------------------------------------------------------------


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


def test_resolve_auth_header_name_custom(tmp_path: Path) -> None:
    """When auth_requirements has a custom header_name for a host,
    _resolve_auth_header_name should return it."""
    tools_path = _write_minimal_tools(tmp_path)
    reqs = [
        ToolpackAuthRequirement(
            host="shop.myshopify.com",
            scheme="api_key",
            location="header",
            header_name="X-Shopify-Access-Token",
            env_var_name="TOOLWRIGHT_AUTH_SHOP_MYSHOPIFY_COM",
        ),
    ]
    server = ToolwrightMCPServer(
        tools_path=tools_path,
        auth_requirements=reqs,
    )
    assert server._resolve_auth_header_name("shop.myshopify.com") == "X-Shopify-Access-Token"


def test_resolve_auth_header_name_fallback(tmp_path: Path) -> None:
    """When no auth_requirements match the host,
    _resolve_auth_header_name should return 'Authorization'."""
    tools_path = _write_minimal_tools(tmp_path)
    server = ToolwrightMCPServer(tools_path=tools_path)
    assert server._resolve_auth_header_name("api.example.com") == "Authorization"


def test_resolve_auth_header_name_none_header_name(tmp_path: Path) -> None:
    """When auth_requirements entry has header_name=None,
    _resolve_auth_header_name should fallback to 'Authorization'."""
    tools_path = _write_minimal_tools(tmp_path)
    reqs = [
        ToolpackAuthRequirement(
            host="api.github.com",
            scheme="bearer",
            location="header",
            header_name=None,
            env_var_name="TOOLWRIGHT_AUTH_API_GITHUB_COM",
        ),
    ]
    server = ToolwrightMCPServer(
        tools_path=tools_path,
        auth_requirements=reqs,
    )
    assert server._resolve_auth_header_name("api.github.com") == "Authorization"


def test_resolve_auth_header_name_multiple_hosts(tmp_path: Path) -> None:
    """When multiple auth_requirements exist, the correct host's header is used."""
    tools_path = _write_minimal_tools(tmp_path)
    reqs = [
        ToolpackAuthRequirement(
            host="shop.myshopify.com",
            scheme="api_key",
            location="header",
            header_name="X-Shopify-Access-Token",
            env_var_name="TOOLWRIGHT_AUTH_SHOP_MYSHOPIFY_COM",
        ),
        ToolpackAuthRequirement(
            host="api.stripe.com",
            scheme="bearer",
            location="header",
            header_name=None,
            env_var_name="TOOLWRIGHT_AUTH_API_STRIPE_COM",
        ),
    ]
    server = ToolwrightMCPServer(
        tools_path=tools_path,
        auth_requirements=reqs,
    )
    assert server._resolve_auth_header_name("shop.myshopify.com") == "X-Shopify-Access-Token"
    assert server._resolve_auth_header_name("api.stripe.com") == "Authorization"
    assert server._resolve_auth_header_name("unknown.host.com") == "Authorization"
