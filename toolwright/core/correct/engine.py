"""Behavioral rule engine for the CORRECT pillar.

Evaluates 6 rule types against tool calls, supports CRUD,
JSON persistence, and hot-reload on file changes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from toolwright.core.correct.feedback import generate_feedback
from toolwright.core.correct.session import SessionHistory
from toolwright.models.rule import (
    ApprovalConfig,
    BehavioralRule,
    ParameterConfig,
    PrerequisiteConfig,
    ProhibitionConfig,
    RuleEvaluation,
    RuleKind,
    RuleStatus,
    RuleViolation,
    SequenceConfig,
    SessionRateConfig,
)


class RuleEngine:
    """Evaluate behavioral rules against tool calls.

    Loads rules from a JSON file, supports CRUD operations,
    and hot-reloads when the file changes on disk.
    """

    def __init__(self, rules_path: Path) -> None:
        self._rules_path = rules_path
        self._rules: dict[str, BehavioralRule] = {}
        self._mtime: float = 0.0

        if self._rules_path.exists():
            self._load_rules()
        else:
            self._rules_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_rules()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_rule(self, rule: BehavioralRule) -> None:
        """Add a new rule. Raises ValueError if rule_id already exists."""
        if rule.rule_id in self._rules:
            raise ValueError(f"Rule '{rule.rule_id}' already exists")
        self._rules[rule.rule_id] = rule
        self._save_rules()

    def remove_rule(self, rule_id: str) -> None:
        """Remove a rule by ID. Raises KeyError if not found."""
        if rule_id not in self._rules:
            raise KeyError(f"Rule '{rule_id}' not found")
        del self._rules[rule_id]
        self._save_rules()

    def update_rule(self, rule_id: str, **kwargs: Any) -> None:
        """Update fields on an existing rule. Raises KeyError if not found."""
        if rule_id not in self._rules:
            raise KeyError(f"Rule '{rule_id}' not found")
        rule = self._rules[rule_id]
        for key, value in kwargs.items():
            if hasattr(rule, key):
                setattr(rule, key, value)
        self._save_rules()

    def get_rule(self, rule_id: str) -> BehavioralRule | None:
        """Get a rule by ID, or None if not found."""
        return self._rules.get(rule_id)

    def list_rules(self) -> list[BehavioralRule]:
        """Return all rules."""
        return list(self._rules.values())

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        tool_id: str,
        method: str,
        host: str,
        params: dict[str, Any],
        session: SessionHistory,
    ) -> RuleEvaluation:
        """Evaluate all applicable rules for a tool call."""
        self._check_hot_reload()

        applicable = self._applicable_rules(tool_id, method, host)
        violations: list[RuleViolation] = []

        for rule in applicable:
            violation = self._evaluate_rule(rule, tool_id, params, session)
            if violation is not None:
                violations.append(violation)

        feedback = generate_feedback(violations)
        return RuleEvaluation(
            allowed=len(violations) == 0,
            violations=violations,
            feedback=feedback,
        )

    def _applicable_rules(
        self, tool_id: str, method: str, host: str
    ) -> list[BehavioralRule]:
        """Filter rules by targets, skip disabled, sort by priority."""
        result = []
        for rule in self._rules.values():
            if rule.status != RuleStatus.ACTIVE:
                continue
            if not self._matches_targets(rule, tool_id, method, host):
                continue
            result.append(rule)
        result.sort(key=lambda r: r.priority)
        return result

    @staticmethod
    def _matches_targets(
        rule: BehavioralRule, tool_id: str, method: str, host: str
    ) -> bool:
        """Check if a tool call matches rule targeting fields.

        match="all": tool must match ALL non-empty targeting fields (AND).
        match="any": tool matches if ANY non-empty targeting field hits (OR).
        Empty fields are ignored.
        """
        from fnmatch import fnmatch

        checks: list[bool] = []

        if rule.target_tool_ids:
            checks.append(tool_id in rule.target_tool_ids)
        if rule.target_name_patterns:
            checks.append(
                any(fnmatch(tool_id, pat) for pat in rule.target_name_patterns)
            )
        if rule.target_methods:
            checks.append(method in rule.target_methods)
        if rule.target_hosts:
            checks.append(host in rule.target_hosts)

        if not checks:
            return True  # no targeting = matches all

        if rule.match == "any":
            return any(checks)
        return all(checks)

    # ------------------------------------------------------------------
    # Per-kind evaluators
    # ------------------------------------------------------------------

    def _evaluate_rule(
        self,
        rule: BehavioralRule,
        tool_id: str,
        params: dict[str, Any],
        session: SessionHistory,
    ) -> RuleViolation | None:
        """Dispatch to the correct evaluator for this rule kind."""
        evaluators = {
            RuleKind.PREREQUISITE: self._evaluate_prerequisite,
            RuleKind.PROHIBITION: self._evaluate_prohibition,
            RuleKind.PARAMETER: self._evaluate_parameter,
            RuleKind.SEQUENCE: self._evaluate_sequence,
            RuleKind.RATE: self._evaluate_rate,
            RuleKind.APPROVAL: self._evaluate_approval,
        }
        evaluator = evaluators.get(rule.kind)
        if evaluator is None:
            return None
        return evaluator(rule, tool_id, params, session)

    def _evaluate_prerequisite(
        self,
        rule: BehavioralRule,
        tool_id: str,
        _params: dict[str, Any],
        session: SessionHistory,
    ) -> RuleViolation | None:
        from fnmatch import fnmatch

        config: PrerequisiteConfig = rule.config  # type: ignore[assignment]
        required_args = config.required_args or {}

        for req_tool in config.required_tool_ids:
            if required_args:
                if not session.has_called(req_tool, with_args=required_args):
                    return RuleViolation(
                        rule_id=rule.rule_id,
                        rule_kind=rule.kind,
                        tool_id=tool_id,
                        description=rule.description,
                        feedback=f"Prerequisite not met: {req_tool} with args {required_args}",
                        suggestion=f"Call {req_tool} with {required_args} first.",
                    )
            else:
                if not session.has_called(req_tool):
                    return RuleViolation(
                        rule_id=rule.rule_id,
                        rule_kind=rule.kind,
                        tool_id=tool_id,
                        description=rule.description,
                        feedback=f"Prerequisite not met: {req_tool} not called",
                        suggestion=f"Call {req_tool} first.",
                    )

        # Check glob pattern prerequisites (any pattern match satisfies)
        if config.required_tool_patterns:
            called_ids = session.call_sequence()
            if not any(
                fnmatch(cid, pattern)
                for pattern in config.required_tool_patterns
                for cid in called_ids
            ):
                patterns_str = ", ".join(config.required_tool_patterns)
                return RuleViolation(
                    rule_id=rule.rule_id,
                    rule_kind=rule.kind,
                    tool_id=tool_id,
                    description=rule.description,
                    feedback=f"Prerequisite not met: no tool matching '{patterns_str}' called",
                    suggestion=f"Call a tool matching one of [{patterns_str}] first.",
                )

        return None

    def _evaluate_prohibition(
        self,
        rule: BehavioralRule,
        tool_id: str,
        _params: dict[str, Any],
        session: SessionHistory,
    ) -> RuleViolation | None:
        config: ProhibitionConfig = rule.config  # type: ignore[assignment]

        if config.always:
            return RuleViolation(
                rule_id=rule.rule_id,
                rule_kind=rule.kind,
                tool_id=tool_id,
                description=rule.description,
                feedback=f"Tool {tool_id} is unconditionally prohibited.",
                suggestion=None,
            )

        if config.after_tool_ids:
            for trigger in config.after_tool_ids:
                if session.has_called(trigger):
                    return RuleViolation(
                        rule_id=rule.rule_id,
                        rule_kind=rule.kind,
                        tool_id=tool_id,
                        description=rule.description,
                        feedback=f"Tool {tool_id} is prohibited after {trigger}.",
                        suggestion=f"Avoid calling {tool_id} after {trigger}.",
                    )

        return None

    def _evaluate_parameter(
        self,
        rule: BehavioralRule,
        tool_id: str,
        params: dict[str, Any],
        _session: SessionHistory,
    ) -> RuleViolation | None:
        config: ParameterConfig = rule.config  # type: ignore[assignment]

        if config.param_name not in params:
            return None  # param not present, rule doesn't apply

        value = params[config.param_name]

        if config.allowed_values is not None and value not in config.allowed_values:
            return RuleViolation(
                rule_id=rule.rule_id,
                rule_kind=rule.kind,
                tool_id=tool_id,
                description=rule.description,
                feedback=f"Parameter '{config.param_name}' value '{value}' not in allowed: {config.allowed_values}",
                suggestion=f"Use one of: {config.allowed_values}",
            )

        if config.blocked_values is not None and value in config.blocked_values:
            return RuleViolation(
                rule_id=rule.rule_id,
                rule_kind=rule.kind,
                tool_id=tool_id,
                description=rule.description,
                feedback=f"Parameter '{config.param_name}' value '{value}' is blocked.",
                suggestion=f"Avoid values: {config.blocked_values}",
            )

        if config.max_value is not None:
            try:
                if float(value) > config.max_value:
                    return RuleViolation(
                        rule_id=rule.rule_id,
                        rule_kind=rule.kind,
                        tool_id=tool_id,
                        description=rule.description,
                        feedback=f"Parameter '{config.param_name}' value {value} exceeds max {config.max_value}.",
                        suggestion=f"Use a value <= {config.max_value}.",
                    )
            except (TypeError, ValueError):
                pass

        if config.min_value is not None:
            try:
                if float(value) < config.min_value:
                    return RuleViolation(
                        rule_id=rule.rule_id,
                        rule_kind=rule.kind,
                        tool_id=tool_id,
                        description=rule.description,
                        feedback=f"Parameter '{config.param_name}' value {value} below min {config.min_value}.",
                        suggestion=f"Use a value >= {config.min_value}.",
                    )
            except (TypeError, ValueError):
                pass

        if config.pattern is not None and not re.match(config.pattern, str(value)):
                return RuleViolation(
                    rule_id=rule.rule_id,
                    rule_kind=rule.kind,
                    tool_id=tool_id,
                    description=rule.description,
                    feedback=f"Parameter '{config.param_name}' value '{value}' doesn't match pattern '{config.pattern}'.",
                    suggestion=f"Value must match: {config.pattern}",
                )

        return None

    def _evaluate_sequence(
        self,
        rule: BehavioralRule,
        tool_id: str,
        _params: dict[str, Any],
        session: SessionHistory,
    ) -> RuleViolation | None:
        config: SequenceConfig = rule.config  # type: ignore[assignment]
        required = config.required_order
        call_seq = session.call_sequence()

        # The current tool_id is the last in the required order
        # Check that all prior steps appear in the correct order in session history
        # We need to verify that the required tools (excluding the current one) appear
        # as a subsequence of the call history in the right order.
        prior_required = [t for t in required if t != tool_id]

        if not prior_required:
            return None

        # Check subsequence: all prior_required must appear in call_seq in order
        seq_idx = 0
        for call in call_seq:
            if seq_idx < len(prior_required) and call == prior_required[seq_idx]:
                seq_idx += 1

        if seq_idx < len(prior_required):
            missing = prior_required[seq_idx:]
            return RuleViolation(
                rule_id=rule.rule_id,
                rule_kind=rule.kind,
                tool_id=tool_id,
                description=rule.description,
                feedback=f"Sequence violation: expected order {required}, missing or out-of-order: {missing}",
                suggestion=f"Follow the required call order: {' -> '.join(required)}",
            )

        return None

    def _evaluate_rate(
        self,
        rule: BehavioralRule,
        tool_id: str,
        _params: dict[str, Any],
        session: SessionHistory,
    ) -> RuleViolation | None:
        config: SessionRateConfig = rule.config  # type: ignore[assignment]

        if config.window_seconds is not None:
            recent = session.calls_since(config.window_seconds)
            if config.per_tool:
                count = sum(1 for c in recent if c.tool_id == tool_id)
            else:
                count = len(recent)
        else:
            count = session.call_count(tool_id) if config.per_tool else session.call_count()

        if count >= config.max_calls:
            return RuleViolation(
                rule_id=rule.rule_id,
                rule_kind=rule.kind,
                tool_id=tool_id,
                description=rule.description,
                feedback=f"Rate limit exceeded: {count}/{config.max_calls} calls.",
                suggestion="Wait before making more calls.",
            )

        return None

    def _evaluate_approval(
        self,
        rule: BehavioralRule,
        tool_id: str,
        params: dict[str, Any],
        session: SessionHistory,
    ) -> RuleViolation | None:
        config: ApprovalConfig = rule.config  # type: ignore[assignment]

        triggered = False

        if config.when_param_matches and all(
            params.get(k) == v for k, v in config.when_param_matches.items()
        ):
            triggered = True

        if config.when_after_tool and session.has_called(config.when_after_tool):
            triggered = True

        if not config.when_param_matches and not config.when_after_tool:
            # No conditions specified -- always require approval
            triggered = True

        if triggered:
            return RuleViolation(
                rule_id=rule.rule_id,
                rule_kind=rule.kind,
                tool_id=tool_id,
                description=f"Approval required: {config.approval_message}",
                feedback=config.approval_message,
                suggestion="Request approval before proceeding.",
                severity="warning",
            )

        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_rules(self) -> None:
        """Load rules from the JSON file."""
        try:
            data = json.loads(self._rules_path.read_text())
            self._rules = {}
            for item in data:
                rule = BehavioralRule.model_validate(item)
                self._rules[rule.rule_id] = rule
            self._mtime = self._rules_path.stat().st_mtime
        except (json.JSONDecodeError, OSError):
            self._rules = {}

    def _save_rules(self) -> None:
        """Save rules to the JSON file."""
        data = [r.model_dump(mode="json") for r in self._rules.values()]
        self._rules_path.write_text(json.dumps(data, indent=2, default=str))
        self._mtime = self._rules_path.stat().st_mtime

    def _check_hot_reload(self) -> None:
        """Reload rules if the file has been modified externally."""
        try:
            current_mtime = self._rules_path.stat().st_mtime
            if current_mtime != self._mtime:
                self._load_rules()
        except OSError:
            pass
