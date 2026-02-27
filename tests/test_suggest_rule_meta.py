"""Tests for the toolwright_suggest_rule meta-tool.

Agent calls toolwright_suggest_rule to suggest a new behavioral rule.
The rule is created with status=DRAFT and created_by="agent".
Only humans can activate agent-suggested rules.
"""

from __future__ import annotations

import pytest

from toolwright.mcp.meta_server import ToolwrightMetaMCPServer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server_with_rules(tmp_path):
    """Server with a rules engine configured (empty rules file)."""
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("[]")
    state_dir = tmp_path / ".toolwright" / "state"
    state_dir.mkdir(parents=True)
    return ToolwrightMetaMCPServer(rules_path=str(rules_path), state_dir=state_dir)


@pytest.fixture
def server_without_rules():
    """Server without a rules engine configured."""
    return ToolwrightMetaMCPServer()


# ---------------------------------------------------------------------------
# TestSuggestRuleRegistration
# ---------------------------------------------------------------------------


class TestSuggestRuleRegistration:
    """Tool must appear in _handle_list_tools and have a description."""

    @pytest.mark.asyncio
    async def test_tool_listed(self, server_with_rules):
        tools = await server_with_rules._handle_list_tools()
        tool_names = [t.name for t in tools]
        assert "toolwright_suggest_rule" in tool_names

    @pytest.mark.asyncio
    async def test_tool_has_description(self, server_with_rules):
        tools = await server_with_rules._handle_list_tools()
        tool = next(t for t in tools if t.name == "toolwright_suggest_rule")
        desc = tool.description.lower()
        assert "rule" in desc or "suggest" in desc


# ---------------------------------------------------------------------------
# TestSuggestRuleSuccess
# ---------------------------------------------------------------------------


class TestSuggestRuleSuccess:
    """Successful suggest_rule calls create DRAFT rules by the agent."""

    @pytest.fixture
    def prohibition_args(self):
        return {
            "kind": "prohibition",
            "description": "Never call delete_user directly",
            "config": {"always": True},
        }

    @pytest.mark.asyncio
    async def test_returns_rule_id(self, server_with_rules, prohibition_args):
        result = await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        text = result[0].text
        assert "rule_" in text

    @pytest.mark.asyncio
    async def test_returns_draft_status(self, server_with_rules, prohibition_args):
        result = await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        text = result[0].text
        assert "DRAFT" in text

    @pytest.mark.asyncio
    async def test_returns_next_steps(self, server_with_rules, prohibition_args):
        result = await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        text = result[0].text
        assert "toolwright rules activate" in text

    @pytest.mark.asyncio
    async def test_rule_created_as_draft(self, server_with_rules, prohibition_args):
        await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        rules = server_with_rules.rule_engine.list_rules()
        assert len(rules) == 1
        assert rules[0].status.value == "draft"

    @pytest.mark.asyncio
    async def test_rule_created_by_agent(self, server_with_rules, prohibition_args):
        await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        rules = server_with_rules.rule_engine.list_rules()
        assert len(rules) == 1
        assert rules[0].created_by == "agent"


# ---------------------------------------------------------------------------
# TestSuggestRuleParameters
# ---------------------------------------------------------------------------


class TestSuggestRuleParameters:
    """Different rule kinds and config shapes are handled correctly."""

    @pytest.mark.asyncio
    async def test_prohibition_rule(self, server_with_rules):
        result = await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule",
            {
                "kind": "prohibition",
                "description": "Block dangerous tool",
                "config": {"always": True},
            },
        )
        text = result[0].text
        assert "rule_" in text

        rules = server_with_rules.rule_engine.list_rules()
        assert len(rules) == 1
        assert rules[0].kind.value == "prohibition"

    @pytest.mark.asyncio
    async def test_parameter_rule(self, server_with_rules):
        result = await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule",
            {
                "kind": "parameter",
                "description": "Only allow safe roles",
                "config": {"param_name": "role", "allowed_values": ["viewer", "editor"]},
            },
        )
        text = result[0].text
        assert "rule_" in text

        rules = server_with_rules.rule_engine.list_rules()
        assert len(rules) == 1
        assert rules[0].kind.value == "parameter"

    @pytest.mark.asyncio
    async def test_custom_target_tool_ids(self, server_with_rules):
        await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule",
            {
                "kind": "prohibition",
                "description": "Block get_users",
                "config": {"always": True},
                "target_tool_ids": ["get_users"],
            },
        )
        rules = server_with_rules.rule_engine.list_rules()
        assert len(rules) == 1
        assert rules[0].target_tool_ids == ["get_users"]


# ---------------------------------------------------------------------------
# TestSuggestRuleErrors
# ---------------------------------------------------------------------------


class TestSuggestRuleErrors:
    """Error paths return descriptive error messages."""

    @pytest.mark.asyncio
    async def test_missing_kind_returns_error(self, server_with_rules):
        result = await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule",
            {"description": "Some rule", "config": {"always": True}},
        )
        text = result[0].text.lower()
        assert "error" in text

    @pytest.mark.asyncio
    async def test_no_rule_engine_returns_error(self, server_without_rules):
        result = await server_without_rules._handle_call_tool(
            "toolwright_suggest_rule",
            {
                "kind": "prohibition",
                "description": "Test rule",
                "config": {"always": True},
            },
        )
        text = result[0].text.lower()
        assert "error" in text


# ---------------------------------------------------------------------------
# TestSuggestRuleConcise
# ---------------------------------------------------------------------------


class TestSuggestRuleConcise:
    """Output must be concise for agent consumption."""

    @pytest.mark.asyncio
    async def test_output_under_300_chars(self, server_with_rules):
        result = await server_with_rules._handle_call_tool(
            "toolwright_suggest_rule",
            {
                "kind": "prohibition",
                "description": "Block dangerous tool",
                "config": {"always": True},
            },
        )
        text = result[0].text
        assert len(text) < 300
