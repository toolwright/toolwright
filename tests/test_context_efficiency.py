"""Tests for context efficiency features (Sprint 2).

TDD RED phase: tests define expected behavior before implementation.

Covers:
- DescriptionOptimizer: compact tool descriptions
- ToolFilter: glob and risk-tier filtering
- Token counting: approximate token budget
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    name: str = "get_users",
    method: str = "GET",
    path: str = "/api/users",
    host: str = "api.example.com",
    risk_tier: str = "low",
    description: str = "Retrieve a list of all users with their profiles and associated metadata",
) -> dict:
    return {
        "name": name,
        "description": description,
        "method": method,
        "path": path,
        "host": host,
        "risk_tier": risk_tier,
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "Page number"},
                "limit": {"type": "integer", "description": "Results per page"},
            },
        },
    }


def _tools_manifest(tmp_path: Path, actions: list[dict] | None = None) -> Path:
    """Create a tools.json manifest with given actions."""
    if actions is None:
        actions = [_make_action()]
    manifest = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test",
        "actions": actions,
    }
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(json.dumps(manifest))
    return tools_path


# ---------------------------------------------------------------------------
# DescriptionOptimizer
# ---------------------------------------------------------------------------


class TestDescriptionOptimizer:
    """optimize_description produces compact tool descriptions."""

    def test_compact_shorter_than_original(self) -> None:
        from toolwright.mcp.description import optimize_description

        action = _make_action(
            description="Retrieve a list of all users with their profiles, email addresses, and associated metadata from the system database"
        )
        compact = optimize_description(action, compact=True)
        assert len(compact) < len(action["description"])

    def test_compact_includes_method_and_path(self) -> None:
        from toolwright.mcp.description import optimize_description

        action = _make_action(method="POST", path="/api/users")
        compact = optimize_description(action, compact=True)
        assert "POST" in compact
        assert "/api/users" in compact

    def test_compact_preserves_risk_annotation(self) -> None:
        from toolwright.mcp.description import optimize_description

        action = _make_action(risk_tier="critical")
        compact = optimize_description(action, compact=True)
        assert "critical" in compact.lower()

    def test_verbose_returns_full_description(self) -> None:
        from toolwright.mcp.description import optimize_description

        action = _make_action(description="Full verbose description here")
        verbose = optimize_description(action, compact=False)
        assert "Full verbose description here" in verbose

    def test_compact_includes_param_names(self) -> None:
        from toolwright.mcp.description import optimize_description

        action = _make_action()
        compact = optimize_description(action, compact=True)
        # Should mention parameter names
        assert "page" in compact or "limit" in compact


# ---------------------------------------------------------------------------
# ToolFilter
# ---------------------------------------------------------------------------


class TestToolFilter:
    """filter_actions applies glob and risk-tier filtering."""

    def test_glob_filter_matches(self) -> None:
        from toolwright.mcp.description import filter_actions

        actions = {
            "get_users": _make_action(name="get_users"),
            "get_posts": _make_action(name="get_posts"),
            "delete_user": _make_action(name="delete_user"),
        }
        result = filter_actions(actions, tools_glob="get_*")
        assert "get_users" in result
        assert "get_posts" in result
        assert "delete_user" not in result

    def test_risk_ceiling_filter(self) -> None:
        from toolwright.mcp.description import filter_actions

        actions = {
            "read_data": _make_action(name="read_data", risk_tier="low"),
            "update_data": _make_action(name="update_data", risk_tier="medium"),
            "delete_data": _make_action(name="delete_data", risk_tier="high"),
            "nuke_all": _make_action(name="nuke_all", risk_tier="critical"),
        }
        result = filter_actions(actions, max_risk="medium")
        assert "read_data" in result
        assert "update_data" in result
        assert "delete_data" not in result
        assert "nuke_all" not in result

    def test_combined_filters(self) -> None:
        from toolwright.mcp.description import filter_actions

        actions = {
            "get_users": _make_action(name="get_users", risk_tier="low"),
            "get_secrets": _make_action(name="get_secrets", risk_tier="high"),
            "delete_user": _make_action(name="delete_user", risk_tier="critical"),
        }
        result = filter_actions(actions, tools_glob="get_*", max_risk="medium")
        assert "get_users" in result
        assert "get_secrets" not in result
        assert "delete_user" not in result

    def test_no_filters_returns_all(self) -> None:
        from toolwright.mcp.description import filter_actions

        actions = {
            "a": _make_action(name="a"),
            "b": _make_action(name="b"),
        }
        result = filter_actions(actions)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


class TestTokenCounting:
    """Approximate token counting for context budget."""

    def test_word_based_approximation(self) -> None:
        from toolwright.utils.token_count import estimate_tokens

        text = "This is a simple test string with ten words here."
        count = estimate_tokens(text)
        # ~10 words * 1.3 = ~13 tokens
        assert 8 <= count <= 20

    def test_empty_string(self) -> None:
        from toolwright.utils.token_count import estimate_tokens

        assert estimate_tokens("") == 0

    def test_context_budget_string(self) -> None:
        from toolwright.utils.token_count import format_context_budget

        result = format_context_budget(total_tokens=1440, tool_count=12)
        assert "1,440" in result or "1440" in result
        assert "12" in result


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestServeCLIFlags:
    """The serve command should accept --verbose-tools, --tools (glob), --max-risk."""

    def test_serve_help_shows_verbose_tools(self) -> None:
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "--verbose-tools" in result.output

    def test_serve_help_shows_max_risk(self) -> None:
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "--max-risk" in result.output

    def test_serve_help_shows_tools_filter(self) -> None:
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert "--tool-filter" in result.output
