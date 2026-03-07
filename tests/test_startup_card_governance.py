"""Tests for governance layers display in the startup card."""

from __future__ import annotations

from toolwright.mcp.startup_card import render_startup_card


def _base_card_kwargs() -> dict:
    """Base kwargs for render_startup_card."""
    return {
        "name": "test-api",
        "tools": {"read": 5, "write": 3},
        "risk_counts": {"low": 3, "medium": 4, "high": 1},
        "context_tokens": 15000,
        "tokens_per_tool": 1875,
    }


class TestGovernanceLayers:
    """Test governance layer rendering in the startup card."""

    def test_governance_renders_checkmarks_when_configured(self) -> None:
        """Active governance layers should show checkmarks."""
        card = render_startup_card(
            **_base_card_kwargs(),
            governance={
                "lockfile": "active",
                "rules": "crud-safety (3 rules)",
                "policy": None,
                "breakers": None,
                "watch": None,
            },
        )

        assert "\u2713" in card  # checkmark
        assert "Lockfile" in card
        assert "crud-safety (3 rules)" in card

    def test_governance_renders_circles_when_not_configured(self) -> None:
        """Unconfigured governance layers should show circles."""
        card = render_startup_card(
            **_base_card_kwargs(),
            governance={
                "lockfile": "active",
                "rules": None,
                "policy": None,
                "breakers": None,
                "watch": None,
            },
        )

        assert "\u25CB" in card  # empty circle
        assert "not configured" in card

    def test_governance_none_produces_no_governance_section(self) -> None:
        """governance=None should produce no governance section (backward compat)."""
        card = render_startup_card(**_base_card_kwargs())

        assert "Governance" not in card
        assert "Lockfile" not in card

    def test_all_governance_layers_active(self) -> None:
        """All governance layers active should show all checkmarks."""
        card = render_startup_card(
            **_base_card_kwargs(),
            governance={
                "lockfile": "active",
                "rules": "crud-safety (3 rules)",
                "policy": "strict",
                "breakers": "3 configured",
                "watch": "on",
            },
        )

        # Count checkmarks (should be 5)
        checkmarks = card.count("\u2713")
        assert checkmarks == 5

    def test_governance_with_watch_off(self) -> None:
        """Watch mode 'off' should render as unconfigured."""
        card = render_startup_card(
            **_base_card_kwargs(),
            governance={
                "lockfile": "active",
                "rules": "crud-safety (3 rules)",
                "policy": None,
                "breakers": None,
                "watch": None,
            },
        )

        assert "Watch" in card
