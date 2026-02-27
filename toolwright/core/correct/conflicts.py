"""Conflict detection for behavioral rules.

Detects contradictions between a new rule and existing rules:
- Circular prerequisite/prohibition dependencies
- Parameter whitelist/blacklist overlaps
- Contradictory sequence orders
"""

from __future__ import annotations

from toolwright.models.rule import (
    BehavioralRule,
    ParameterConfig,
    PrerequisiteConfig,
    ProhibitionConfig,
    RuleConflict,
    RuleKind,
    SequenceConfig,
)


def _targets_overlap(a: BehavioralRule, b: BehavioralRule) -> bool:
    """Check if two rules share any target tool_ids.

    Empty target_tool_ids means the rule applies to ALL tools,
    so it overlaps with everything.
    """
    if not a.target_tool_ids or not b.target_tool_ids:
        return True  # Wildcard (empty) targets overlap with everything
    return bool(set(a.target_tool_ids) & set(b.target_tool_ids))


def detect_conflicts(
    new_rule: BehavioralRule,
    existing_rules: list[BehavioralRule],
) -> list[RuleConflict]:
    """Detect conflicts between a new rule and existing rules."""
    conflicts: list[RuleConflict] = []

    for existing in existing_rules:
        conflicts.extend(_check_pair(new_rule, existing))

    return conflicts


def _check_pair(a: BehavioralRule, b: BehavioralRule) -> list[RuleConflict]:
    """Check a pair of rules for conflicts."""
    results: list[RuleConflict] = []

    # Circular prerequisite/prohibition
    if a.kind == RuleKind.PREREQUISITE and b.kind == RuleKind.PROHIBITION:
        results.extend(_check_circular(a, b))
    elif a.kind == RuleKind.PROHIBITION and b.kind == RuleKind.PREREQUISITE:
        results.extend(_check_circular(b, a))

    # Parameter contradictions
    if a.kind == RuleKind.PARAMETER and b.kind == RuleKind.PARAMETER:
        results.extend(_check_param_contradiction(a, b))

    # Sequence contradictions
    if a.kind == RuleKind.SEQUENCE and b.kind == RuleKind.SEQUENCE:
        results.extend(_check_sequence_contradiction(a, b))

    return results


def _check_circular(
    prereq_rule: BehavioralRule,
    prohib_rule: BehavioralRule,
) -> list[RuleConflict]:
    """A requires B + B prohibited after A = circular."""
    assert isinstance(prereq_rule.config, PrerequisiteConfig)
    assert isinstance(prohib_rule.config, ProhibitionConfig)

    required_ids = set(prereq_rule.config.required_tool_ids)
    prohibited_targets = set(prohib_rule.target_tool_ids)
    after_ids = set(prohib_rule.config.after_tool_ids)
    prereq_targets = set(prereq_rule.target_tool_ids)

    # If the prerequisite requires calling tools that are prohibited
    # after the prerequisite's own targets are called
    if (required_ids & prohibited_targets) and (after_ids & prereq_targets):
        return [
            RuleConflict(
                rule_a_id=prereq_rule.rule_id,
                rule_b_id=prohib_rule.rule_id,
                conflict_type="circular_dependency",
                description=(
                    f"Rule {prereq_rule.rule_id} requires {required_ids & prohibited_targets} "
                    f"but rule {prohib_rule.rule_id} prohibits them after {after_ids & prereq_targets}"
                ),
            )
        ]
    return []


def _check_param_contradiction(
    a: BehavioralRule,
    b: BehavioralRule,
) -> list[RuleConflict]:
    """Detect overlapping allowed/blocked values for the same param on same targets."""
    if not _targets_overlap(a, b):
        return []

    assert isinstance(a.config, ParameterConfig)
    assert isinstance(b.config, ParameterConfig)

    if a.config.param_name != b.config.param_name:
        return []

    # Check allowed vs blocked overlap
    a_allowed = set(a.config.allowed_values or [])
    a_blocked = set(a.config.blocked_values or [])
    b_allowed = set(b.config.allowed_values or [])
    b_blocked = set(b.config.blocked_values or [])

    overlap = (a_allowed & b_blocked) | (b_allowed & a_blocked)
    if overlap:
        return [
            RuleConflict(
                rule_a_id=a.rule_id,
                rule_b_id=b.rule_id,
                conflict_type="parameter_contradiction",
                description=(
                    f"Parameter '{a.config.param_name}': values {overlap} are both "
                    f"allowed and blocked across rules {a.rule_id} and {b.rule_id}"
                ),
            )
        ]
    return []


def _check_sequence_contradiction(
    a: BehavioralRule,
    b: BehavioralRule,
) -> list[RuleConflict]:
    """Detect contradictory sequence orders on overlapping targets."""
    if not _targets_overlap(a, b):
        return []

    assert isinstance(a.config, SequenceConfig)
    assert isinstance(b.config, SequenceConfig)

    order_a = a.config.required_order
    order_b = b.config.required_order

    # Find common elements and check if their relative order differs
    common = [x for x in order_a if x in order_b]
    if len(common) < 2:
        return []

    # Check if the order of common elements is reversed
    order_in_a = [order_a.index(x) for x in common]
    order_in_b = [order_b.index(x) for x in common]

    # If one is increasing and the other is not monotonic in the same way
    if order_in_a != order_in_b:
        return [
            RuleConflict(
                rule_a_id=a.rule_id,
                rule_b_id=b.rule_id,
                conflict_type="sequence_contradiction",
                description=(
                    f"Rules {a.rule_id} and {b.rule_id} require contradictory "
                    f"orderings for tools {common}"
                ),
            )
        ]
    return []
