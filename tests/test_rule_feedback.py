"""Tests for violation feedback generation."""

from __future__ import annotations

from toolwright.core.correct.feedback import generate_feedback
from toolwright.models.rule import RuleKind, RuleViolation


class TestGenerateFeedback:
    def test_empty_violations(self) -> None:
        result = generate_feedback([])
        assert result == ""

    def test_single_violation(self) -> None:
        v = RuleViolation(
            rule_id="r1",
            rule_kind=RuleKind.PREREQUISITE,
            tool_id="update_user",
            description="Must call get_user before update_user",
            feedback="Call get_user first.",
            suggestion="Call get_user first.",
        )
        result = generate_feedback([v])
        assert "1 behavioral rule violation" in result
        assert "prerequisite" in result
        assert "Must call get_user before update_user" in result
        assert "Call get_user first." in result

    def test_multiple_violations(self) -> None:
        violations = [
            RuleViolation(
                rule_id="r1",
                rule_kind=RuleKind.PREREQUISITE,
                tool_id="update_user",
                description="Must call get_user first",
                feedback="Call get_user first.",
                suggestion="Call get_user.",
            ),
            RuleViolation(
                rule_id="r2",
                rule_kind=RuleKind.PARAMETER,
                tool_id="update_user",
                description="Limit out of range",
                feedback="Use a value between 1 and 100.",
            ),
        ]
        result = generate_feedback(violations)
        assert "2 behavioral rule violations" in result
        assert "1." in result
        assert "2." in result

    def test_feedback_is_structured(self) -> None:
        v = RuleViolation(
            rule_id="r1",
            rule_kind=RuleKind.PROHIBITION,
            tool_id="delete_user",
            description="Deletion prohibited",
            feedback="Cannot delete users.",
        )
        result = generate_feedback([v])
        # Should be agent-consumable structured text
        lines = result.strip().split("\n")
        assert len(lines) >= 2  # Header + at least one violation line

    def test_suggestion_included_when_present(self) -> None:
        v = RuleViolation(
            rule_id="r1",
            rule_kind=RuleKind.RATE,
            tool_id="list_items",
            description="Rate limit exceeded",
            feedback="Too many calls.",
            suggestion="Wait 30 seconds.",
        )
        result = generate_feedback([v])
        assert "Wait 30 seconds." in result
