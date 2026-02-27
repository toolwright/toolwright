"""Tests for CORRECT meta-tools exposed via the Meta MCP server.

Tests that the meta server exposes toolwright_add_rule,
toolwright_list_rules, toolwright_remove_rule, and toolwright_update_rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolwright.mcp.meta_server import ToolwrightMetaMCPServer


@pytest.fixture
def tools_manifest(tmp_path: Path) -> Path:
    manifest = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test Tools",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {
                "name": "get_user",
                "method": "GET",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "low",
            },
        ],
    }
    p = tmp_path / "tools.json"
    p.write_text(json.dumps(manifest))
    return p


@pytest.fixture
def meta_server(tools_manifest: Path, tmp_path: Path) -> ToolwrightMetaMCPServer:
    return ToolwrightMetaMCPServer(
        tools_path=str(tools_manifest),
        rules_path=str(tmp_path / "rules.json"),
    )


class TestCorrectMetaToolsRegistered:
    """CORRECT meta-tools should be listed."""

    @pytest.mark.asyncio
    async def test_add_rule_listed(self, meta_server: ToolwrightMetaMCPServer):
        tools = await meta_server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_add_rule" in names

    @pytest.mark.asyncio
    async def test_list_rules_listed(self, meta_server: ToolwrightMetaMCPServer):
        tools = await meta_server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_list_rules" in names

    @pytest.mark.asyncio
    async def test_remove_rule_listed(self, meta_server: ToolwrightMetaMCPServer):
        tools = await meta_server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_remove_rule" in names


class TestAddRule:
    """toolwright_add_rule creates a behavioral rule."""

    @pytest.mark.asyncio
    async def test_add_prerequisite_rule(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_add_rule",
            {
                "kind": "prerequisite",
                "target_tool_id": "update_user",
                "description": "Must call get_user first",
                "required_tool_ids": ["get_user"],
            },
        )
        data = json.loads(result[0].text)
        assert "rule_id" in data
        assert data["kind"] == "prerequisite"

    @pytest.mark.asyncio
    async def test_add_prohibition_rule(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_add_rule",
            {
                "kind": "prohibition",
                "target_tool_id": "delete_user",
                "description": "Never delete users",
            },
        )
        data = json.loads(result[0].text)
        assert "rule_id" in data
        assert data["kind"] == "prohibition"

    @pytest.mark.asyncio
    async def test_add_rule_requires_kind(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_add_rule", {"target_tool_id": "x"}
        )
        data = json.loads(result[0].text)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_add_rule_without_rules_engine(self, tools_manifest: Path):
        server = ToolwrightMetaMCPServer(tools_path=str(tools_manifest))
        result = await server._handle_call_tool(
            "toolwright_add_rule",
            {"kind": "prohibition", "target_tool_id": "x", "description": "test"},
        )
        data = json.loads(result[0].text)
        assert "error" in data


class TestListRules:
    """toolwright_list_rules returns all rules."""

    @pytest.mark.asyncio
    async def test_empty_rules(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_list_rules", {}
        )
        data = json.loads(result[0].text)
        assert data["total"] == 0
        assert data["rules"] == []

    @pytest.mark.asyncio
    async def test_list_after_add(self, meta_server: ToolwrightMetaMCPServer):
        await meta_server._handle_call_tool(
            "toolwright_add_rule",
            {
                "kind": "prohibition",
                "target_tool_id": "delete_user",
                "description": "No deletes",
            },
        )
        result = await meta_server._handle_call_tool(
            "toolwright_list_rules", {}
        )
        data = json.loads(result[0].text)
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_filter_by_kind(self, meta_server: ToolwrightMetaMCPServer):
        await meta_server._handle_call_tool(
            "toolwright_add_rule",
            {"kind": "prohibition", "target_tool_id": "a", "description": "x"},
        )
        await meta_server._handle_call_tool(
            "toolwright_add_rule",
            {
                "kind": "prerequisite",
                "target_tool_id": "b",
                "description": "y",
                "required_tool_ids": ["a"],
            },
        )
        result = await meta_server._handle_call_tool(
            "toolwright_list_rules", {"kind": "prohibition"}
        )
        data = json.loads(result[0].text)
        assert data["total"] == 1


class TestRemoveRule:
    """toolwright_remove_rule removes a rule by ID."""

    @pytest.mark.asyncio
    async def test_remove_rule(self, meta_server: ToolwrightMetaMCPServer):
        add_result = await meta_server._handle_call_tool(
            "toolwright_add_rule",
            {"kind": "prohibition", "target_tool_id": "x", "description": "test"},
        )
        rule_id = json.loads(add_result[0].text)["rule_id"]

        result = await meta_server._handle_call_tool(
            "toolwright_remove_rule", {"rule_id": rule_id}
        )
        data = json.loads(result[0].text)
        assert data["removed"] is True

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_remove_rule", {"rule_id": "nonexistent"}
        )
        data = json.loads(result[0].text)
        assert data["removed"] is False

    @pytest.mark.asyncio
    async def test_remove_requires_rule_id(self, meta_server: ToolwrightMetaMCPServer):
        result = await meta_server._handle_call_tool(
            "toolwright_remove_rule", {}
        )
        data = json.loads(result[0].text)
        assert "error" in data
