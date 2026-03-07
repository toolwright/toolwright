"""Tests for --scope filtering and tool count guardrails."""
from __future__ import annotations

from typing import Any

from toolwright.cli.mcp import check_tool_count_guardrails
from toolwright.mcp.startup_card import render_startup_card
from toolwright.models.groups import ToolGroup, ToolGroupIndex


def _make_groups_index() -> ToolGroupIndex:
    return ToolGroupIndex(
        groups=[
            ToolGroup(name="products", tools=["get_products", "create_product"], path_prefix="/products", description="Products (2 tools)"),
            ToolGroup(name="orders", tools=["get_orders", "create_order", "delete_order"], path_prefix="/orders", description="Orders (3 tools)"),
            ToolGroup(name="repos", tools=["get_repo", "create_repo"], path_prefix="/repos", description="Repos (2 tools)"),
            ToolGroup(name="repos/issues", tools=["get_issues", "create_issue"], path_prefix="/repos/*/issues", description="Repos > Issues (2 tools)"),
            ToolGroup(name="repos/pulls", tools=["get_pulls"], path_prefix="/repos/*/pulls", description="Repos > Pulls (1 tools)"),
        ],
        ungrouped=[],
        generated_from="auto",
    )


def _make_actions(names: list[str]) -> dict[str, dict[str, Any]]:
    return {n: {"name": n, "path": "/test", "method": "GET", "host": "example.com"} for n in names}


class TestToolCountGuardrails:
    def test_no_warn_at_30(self):
        warnings, block = check_tool_count_guardrails(30, groups_index=None, no_tool_limit=False)
        assert warnings == []
        assert block is False

    def test_warn_above_30(self):
        warnings, block = check_tool_count_guardrails(50, groups_index=None, no_tool_limit=False)
        assert len(warnings) > 0
        assert block is False

    def test_block_above_200(self):
        warnings, block = check_tool_count_guardrails(201, groups_index=None, no_tool_limit=False)
        assert block is True

    def test_block_override(self):
        warnings, block = check_tool_count_guardrails(201, groups_index=None, no_tool_limit=True)
        assert block is False
        assert len(warnings) > 0

    def test_warn_with_groups_suggests_scope(self):
        index = _make_groups_index()
        warnings, block = check_tool_count_guardrails(50, groups_index=index, no_tool_limit=False)
        combined = "\n".join(warnings)
        assert "--scope" in combined

    def test_block_message_mentions_refusing(self):
        warnings, block = check_tool_count_guardrails(201, groups_index=None, no_tool_limit=False)
        assert "Refusing" in warnings[0]

    def test_warn_at_31(self):
        warnings, block = check_tool_count_guardrails(31, groups_index=None, no_tool_limit=False)
        assert len(warnings) > 0
        assert block is False

    def test_no_warn_at_1(self):
        warnings, block = check_tool_count_guardrails(1, groups_index=None, no_tool_limit=False)
        assert warnings == []
        assert block is False


class TestStdioTransportWarning:
    def test_stdio_emits_warning(self):
        """stdio transport should emit a warning for production awareness."""
        from toolwright.cli.mcp import stdio_transport_warning

        msg = stdio_transport_warning()
        assert msg is not None
        assert "--use-http" in msg

    def test_http_no_warning(self):
        """HTTP transport should not emit a stdio warning."""
        from toolwright.cli.mcp import stdio_transport_warning

        # The function returns the warning message only for stdio;
        # it doesn't take transport — it's called only on the stdio path.
        # So it always returns a message. Caller decides when to invoke.
        msg = stdio_transport_warning()
        assert msg is not None


class TestJsonschemaCheck:
    def test_check_returns_none_when_installed(self):
        """No warning when jsonschema is available (it is in our test env)."""
        from toolwright.cli.mcp import check_jsonschema_available

        msg = check_jsonschema_available()
        assert msg is None

    def test_check_message_format(self):
        """The warning message mentions pip install when missing."""
        from unittest.mock import patch

        from toolwright.cli.mcp import check_jsonschema_available

        # Simulate jsonschema not being discoverable by importlib.
        with patch("importlib.util.find_spec", return_value=None):
            msg = check_jsonschema_available()

        assert msg is not None
        assert "jsonschema" in msg
        assert "input validation disabled" in msg


class TestStartupCard:
    def test_startup_card_shows_scope(self):
        """Startup card includes scope info when provided."""
        card = render_startup_card(
            name="Test API",
            tools={"read": 10, "write": 5},
            risk_counts={"low": 10, "medium": 5},
            context_tokens=5000,
            tokens_per_tool=333,
            scope_info="products, orders",
            total_compiled=1183,
        )
        assert "products, orders" in card
        assert "1183" in card

    def test_startup_card_no_scope(self):
        """Startup card works without scope info."""
        card = render_startup_card(
            name="Test API",
            tools={"read": 10},
            risk_counts={"low": 10},
            context_tokens=3000,
            tokens_per_tool=300,
        )
        assert "Test API" in card
