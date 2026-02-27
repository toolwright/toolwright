"""Violation feedback generator for behavioral rules.

Produces structured, agent-consumable text from a list of violations.
"""

from __future__ import annotations

from toolwright.models.rule import RuleViolation


def generate_feedback(violations: list[RuleViolation]) -> str:
    """Generate structured feedback text from rule violations.

    Returns empty string for no violations.
    """
    if not violations:
        return ""

    count = len(violations)
    header = f"Blocked: {count} behavioral rule violation{'s' if count != 1 else ''}."
    lines = [header]

    for i, v in enumerate(violations, 1):
        lines.append(f"{i}. [{v.rule_kind}] {v.description}")
        if v.suggestion:
            lines.append(f"   Suggestion: {v.suggestion}")

    return "\n".join(lines)
