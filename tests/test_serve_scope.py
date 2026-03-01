"""Tests for --scope filtering and tool count guardrails."""
from __future__ import annotations

from typing import Any

import pytest

from toolwright.cli.mcp import check_tool_count_guardrails
from toolwright.core.compile.grouper import filter_by_scope
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
