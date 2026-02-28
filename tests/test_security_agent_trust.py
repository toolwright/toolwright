"""Security tests: agent trust boundary enforcement.

Phase 1.1: _add_rule() must force status=DRAFT and created_by="agent"
Phase 1.2: toolwright_enable_tool must NOT appear in meta-tool list
Phase 8.1: Agent cannot read signing keys or auth tokens via meta-tools.
           Agent meta-tool responses are reasonably sized.
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


# ------------------------------------------------------------------
# Phase 8.1  Agent cannot read signing keys via meta-tools
# ------------------------------------------------------------------

SENSITIVE_FRAGMENTS = [
    "PRIVATE KEY",
    "private_key",
    "signing_key",
    "_signing_key",
    "confirmation_signing",
    "ed25519",
    "BEGIN PRIVATE",
    "BEGIN RSA",
    "BEGIN EC",
    "secret_key",
]


@pytest.fixture
def full_server(tmp_path: Path) -> ToolwrightMetaMCPServer:
    """Server with all pillars configured on disk so every handler can respond."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    cb_path = tmp_path / "circuit_breaker.json"
    cb_path.write_text("{}")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return ToolwrightMetaMCPServer(
        rules_path=str(rules_path),
        circuit_breaker_path=str(cb_path),
        state_dir=str(state_dir),
    )


@pytest.mark.asyncio
async def test_no_signing_keys_in_meta_tool_responses(full_server: ToolwrightMetaMCPServer) -> None:
    """No meta-tool response should contain signing key material."""
    # Gather responses from every tool that can respond without a manifest
    tool_calls = [
        ("toolwright_quarantine_report", {}),
        ("toolwright_list_rules", {}),
        ("toolwright_reconcile_status", {}),
        ("toolwright_pending_repairs", {}),
    ]

    for tool_name, args in tool_calls:
        result = await full_server._handle_call_tool(tool_name, args)
        for content in result:
            text = content.text
            for fragment in SENSITIVE_FRAGMENTS:
                assert fragment.lower() not in text.lower(), (
                    f"Signing key fragment '{fragment}' found in response of {tool_name}: {text[:200]}"
                )


@pytest.mark.asyncio
async def test_no_auth_tokens_in_meta_tool_responses(full_server: ToolwrightMetaMCPServer) -> None:
    """No meta-tool response should leak confirmation tokens or signing material."""
    # Create a rule and then list rules to check output
    await full_server._add_rule({
        "kind": "prohibition",
        "target_tool_id": "test_tool",
        "description": "test rule",
    })

    result = await full_server._handle_call_tool("toolwright_list_rules", {})
    for content in result:
        text = content.text
        # Ensure no signing key material leaks
        for fragment in SENSITIVE_FRAGMENTS:
            assert fragment.lower() not in text.lower(), (
                f"Auth/signing fragment '{fragment}' found in list_rules response"
            )


# ------------------------------------------------------------------
# Phase 8.1  Agent meta-tool responses are reasonably sized
# ------------------------------------------------------------------

MAX_RESPONSE_CHARS = 800  # ~200 tokens


@pytest.mark.asyncio
async def test_meta_tool_responses_under_size_limit(full_server: ToolwrightMetaMCPServer) -> None:
    """Every meta-tool response must be under 800 chars (~200 tokens) when data is minimal."""
    tool_calls = [
        ("toolwright_quarantine_report", {}),
        ("toolwright_list_rules", {}),
        ("toolwright_reconcile_status", {}),
        ("toolwright_pending_repairs", {}),
    ]

    for tool_name, args in tool_calls:
        result = await full_server._handle_call_tool(tool_name, args)
        total_chars = sum(len(c.text) for c in result)
        assert total_chars <= MAX_RESPONSE_CHARS, (
            f"{tool_name} response is {total_chars} chars, exceeds {MAX_RESPONSE_CHARS} limit"
        )
