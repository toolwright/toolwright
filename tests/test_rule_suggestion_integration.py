"""Integration test: rule suggestion lifecycle.

Agent suggests -> DRAFT created -> human activates -> rule enforced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolwright.core.correct.engine import RuleEngine
from toolwright.core.correct.session import SessionHistory
from toolwright.mcp.meta_server import ToolwrightMetaMCPServer
from toolwright.models.rule import RuleStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_rule_id(result_text: str) -> str:
    """Extract rule_id from suggest_rule response text.

    Text format: "Rule suggested: rule_abc123 (prohibition, DRAFT)\n..."
    """
    first_line = result_text.split("\n")[0]
    # "Rule suggested: rule_abc123 (prohibition, DRAFT)"
    after_colon = first_line.split(":")[1]  # " rule_abc123 (prohibition, DRAFT)"
    rule_id = after_colon.split("(")[0].strip()  # "rule_abc123"
    return rule_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rules_path(tmp_path: Path) -> Path:
    """Empty rules file."""
    p = tmp_path / "rules.json"
    p.write_text("[]")
    return p


@pytest.fixture
def server(rules_path: Path, tmp_path: Path) -> ToolwrightMetaMCPServer:
    """Meta MCP server with a rule engine configured."""
    state_dir = tmp_path / ".toolwright" / "state"
    state_dir.mkdir(parents=True)
    return ToolwrightMetaMCPServer(rules_path=str(rules_path), state_dir=state_dir)


@pytest.fixture
def engine(rules_path: Path) -> RuleEngine:
    """Rule engine pointing at the same rules file as the server."""
    return RuleEngine(rules_path=rules_path)


@pytest.fixture
def session() -> SessionHistory:
    """Empty session history for evaluate() calls."""
    return SessionHistory()


@pytest.fixture
def prohibition_args() -> dict:
    """Arguments to suggest a prohibition rule that blocks delete_user."""
    return {
        "kind": "prohibition",
        "description": "Block delete_user",
        "config": {"always": True},
        "target_tool_ids": ["delete_user"],
    }


# ---------------------------------------------------------------------------
# TestRuleSuggestionLifecycle
# ---------------------------------------------------------------------------


class TestRuleSuggestionLifecycle:
    """End-to-end lifecycle: suggest -> draft -> activate -> enforce -> disable."""

    async def test_agent_suggests_draft_rule(
        self, server: ToolwrightMetaMCPServer, prohibition_args: dict
    ):
        """Agent calls suggest_rule; response contains rule_id and DRAFT."""
        result = await server._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        text = result[0].text

        # Response must mention a rule_id and DRAFT status
        assert "rule_" in text
        assert "DRAFT" in text

        # Extract and verify
        rule_id = _extract_rule_id(text)
        assert rule_id.startswith("rule_")

    async def test_draft_rule_not_enforced(
        self,
        server: ToolwrightMetaMCPServer,
        rules_path: Path,
        prohibition_args: dict,
        session: SessionHistory,
    ):
        """DRAFT rules are skipped during evaluation -- tool call is allowed."""
        # Suggest a prohibition rule (created as DRAFT)
        await server._handle_call_tool("toolwright_suggest_rule", prohibition_args)

        # Use a fresh RuleEngine that reads the same file (hot-reload)
        engine = RuleEngine(rules_path=rules_path)

        # Verify the rule exists and is DRAFT
        rules = engine.list_rules()
        assert len(rules) == 1
        assert rules[0].status == RuleStatus.DRAFT

        # Evaluate: DRAFT rules should NOT block the call
        result = engine.evaluate(
            tool_id="delete_user",
            method="DELETE",
            host="api.example.com",
            params={},
            session=session,
        )
        assert result.allowed is True
        assert len(result.violations) == 0

    async def test_human_activates_rule(
        self,
        server: ToolwrightMetaMCPServer,
        rules_path: Path,
        prohibition_args: dict,
    ):
        """Human activates a DRAFT rule; status becomes ACTIVE."""
        # Suggest the rule
        result = await server._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        rule_id = _extract_rule_id(result[0].text)

        # Simulate human activation via RuleEngine
        engine = RuleEngine(rules_path=rules_path)
        engine.update_rule(rule_id, status=RuleStatus.ACTIVE)

        # Verify
        rule = engine.get_rule(rule_id)
        assert rule is not None
        assert rule.status == RuleStatus.ACTIVE

    async def test_activated_rule_is_enforced(
        self,
        server: ToolwrightMetaMCPServer,
        rules_path: Path,
        prohibition_args: dict,
        session: SessionHistory,
    ):
        """After activation, the prohibition rule blocks the tool call."""
        # Suggest -> activate
        result = await server._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        rule_id = _extract_rule_id(result[0].text)

        engine = RuleEngine(rules_path=rules_path)
        engine.update_rule(rule_id, status=RuleStatus.ACTIVE)

        # Evaluate: ACTIVE prohibition with always=True should block
        eval_result = engine.evaluate(
            tool_id="delete_user",
            method="DELETE",
            host="api.example.com",
            params={},
            session=session,
        )
        assert eval_result.allowed is False
        assert len(eval_result.violations) == 1
        assert eval_result.violations[0].rule_id == rule_id

    async def test_full_lifecycle(
        self,
        server: ToolwrightMetaMCPServer,
        rules_path: Path,
        prohibition_args: dict,
        session: SessionHistory,
    ):
        """Full lifecycle: suggest -> not enforced -> activate -> enforced -> disable -> not enforced."""
        # 1. Agent suggests a rule (DRAFT)
        result = await server._handle_call_tool(
            "toolwright_suggest_rule", prohibition_args
        )
        rule_id = _extract_rule_id(result[0].text)

        engine = RuleEngine(rules_path=rules_path)

        # 2. DRAFT: not enforced
        eval1 = engine.evaluate(
            tool_id="delete_user",
            method="DELETE",
            host="api.example.com",
            params={},
            session=session,
        )
        assert eval1.allowed is True, "DRAFT rule should not block"

        # 3. Human activates
        engine.update_rule(rule_id, status=RuleStatus.ACTIVE)

        # 4. ACTIVE: enforced
        eval2 = engine.evaluate(
            tool_id="delete_user",
            method="DELETE",
            host="api.example.com",
            params={},
            session=session,
        )
        assert eval2.allowed is False, "ACTIVE rule should block"
        assert eval2.violations[0].rule_id == rule_id

        # 5. Human disables
        engine.update_rule(rule_id, status=RuleStatus.DISABLED)

        # 6. DISABLED: not enforced
        eval3 = engine.evaluate(
            tool_id="delete_user",
            method="DELETE",
            host="api.example.com",
            params={},
            session=session,
        )
        assert eval3.allowed is True, "DISABLED rule should not block"
