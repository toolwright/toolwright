"""Security tests: agent-created rules must be DRAFT, enable_tool must not be exposed.

Phase 1.1: _add_rule() must force status=DRAFT and created_by="agent"
Phase 1.2: toolwright_enable_tool must NOT appear in meta-tool list
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolwright.mcp.meta_server import ToolwrightMetaMCPServer
from toolwright.models.rule import RuleStatus


@pytest.fixture
def rules_server(tmp_path: Path) -> ToolwrightMetaMCPServer:
    """Server with a rule engine configured (no manifest needed)."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    return ToolwrightMetaMCPServer(rules_path=str(rules_path))


# ------------------------------------------------------------------
# Phase 1.1  _add_rule forces DRAFT + created_by="agent"
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_rule_forces_draft_status(rules_server: ToolwrightMetaMCPServer) -> None:
    """_add_rule must create rules with status=DRAFT, never ACTIVE."""
    result = await rules_server._add_rule(
        {
            "kind": "prohibition",
            "target_tool_id": "some_tool",
            "description": "test rule",
        }
    )

    # Parse out the rule_id from the response
    payload = json.loads(result[0].text)
    assert "error" not in payload, f"Unexpected error: {payload}"
    rule_id = payload["rule_id"]

    # Fetch the rule from the engine and check status
    rule = rules_server.rule_engine.get_rule(rule_id)
    assert rule is not None, "Rule was not persisted"
    assert rule.status == RuleStatus.DRAFT, (
        f"Agent-created rule must be DRAFT, got {rule.status}"
    )


@pytest.mark.asyncio
async def test_add_rule_sets_created_by_agent(rules_server: ToolwrightMetaMCPServer) -> None:
    """_add_rule must tag rules with created_by='agent'."""
    result = await rules_server._add_rule(
        {
            "kind": "prohibition",
            "target_tool_id": "some_tool",
            "description": "test rule",
        }
    )

    payload = json.loads(result[0].text)
    assert "error" not in payload, f"Unexpected error: {payload}"
    rule_id = payload["rule_id"]

    rule = rules_server.rule_engine.get_rule(rule_id)
    assert rule is not None, "Rule was not persisted"
    assert rule.created_by == "agent", (
        f"Agent-created rule must have created_by='agent', got '{rule.created_by}'"
    )


# ------------------------------------------------------------------
# Phase 1.2  toolwright_enable_tool must NOT be exposed
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enable_tool_not_in_meta_tool_list(rules_server: ToolwrightMetaMCPServer) -> None:
    """toolwright_enable_tool must NOT appear in the tool list (agents must not re-enable killed tools)."""
    tools = await rules_server._handle_list_tools()
    tool_names = [t.name for t in tools]
    assert "toolwright_enable_tool" not in tool_names, (
        "toolwright_enable_tool should be removed from meta-tool list"
    )


@pytest.mark.asyncio
async def test_kill_tool_still_in_meta_tool_list(rules_server: ToolwrightMetaMCPServer) -> None:
    """toolwright_kill_tool must remain in the tool list (agents can still kill tools)."""
    tools = await rules_server._handle_list_tools()
    tool_names = [t.name for t in tools]
    assert "toolwright_kill_tool" in tool_names, (
        "toolwright_kill_tool should remain in meta-tool list"
    )
