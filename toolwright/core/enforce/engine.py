"""Policy enforcement engine."""

from __future__ import annotations

import time
from typing import Any

import yaml

from toolwright.models.policy import (
    EvaluationResult,
    MatchCondition,
    Policy,
    PolicyRule,
    RuleType,
    StateChangingOverride,
)
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION, resolve_schema_version


class PolicyEngine:
    """Engine for evaluating requests against policy rules."""

    def __init__(self, policy: Policy) -> None:
        """Initialize the policy engine.

        Args:
            policy: Policy to enforce
        """
        self.policy = policy
        self._budgets: dict[str, BudgetTracker] = {}
        self._init_budgets()

    def _init_budgets(self) -> None:
        """Initialize budget trackers for budget rules."""
        for rule in self.policy.rules:
            if rule.type == RuleType.BUDGET:
                per_minute = rule.settings.get("per_minute")
                per_hour = rule.settings.get("per_hour")
                self._budgets[rule.id] = BudgetTracker(
                    per_minute=per_minute,
                    per_hour=per_hour,
                )

    def evaluate(
        self,
        method: str,
        path: str,
        host: str,
        headers: dict[str, str] | None = None,
        risk_tier: str | None = None,
        scope: str | None = None,
        *,
        dry_run: bool = False,
    ) -> EvaluationResult:
        """Evaluate a request against the policy.

        Args:
            method: HTTP method
            path: Request path
            host: Request host
            headers: Request headers
            risk_tier: Risk tier of the endpoint
            scope: Scope name

        Returns:
            EvaluationResult with decision and details
        """
        # Start with default redaction fields
        redact_fields = list(self.policy.redact_headers)

        # Track audit settings
        audit_level = "standard"
        should_audit = self.policy.audit_all

        # Track confirmation requirements
        requires_confirmation = False
        confirmation_message = None

        # Track budget state
        budget_exceeded = False
        budget_remaining = None
        budget_rule_matched = None

        # Get rules sorted by priority
        rules = self.policy.get_rules_by_priority()

        # First pass: check for audit rules and collect settings
        for rule in rules:
            if rule.type == RuleType.AUDIT and rule.match.matches(method, path, host, headers, risk_tier, scope):
                should_audit = True
                audit_level = rule.settings.get("level", "standard")

        # Second pass: check for allow/deny/confirm/budget rules
        matched_rule: PolicyRule | None = None
        for rule in rules:
            if rule.type == RuleType.AUDIT:
                continue  # Already processed

            if rule.match.matches(method, path, host, headers, risk_tier, scope):
                if rule.type == RuleType.ALLOW or rule.type == RuleType.DENY:
                    matched_rule = rule
                    break

                elif rule.type == RuleType.CONFIRM:
                    requires_confirmation = True
                    confirmation_message = rule.settings.get("message", "Confirmation required")
                    # Continue checking for allow/deny rules
                    if matched_rule is None:
                        matched_rule = rule

                elif rule.type == RuleType.BUDGET:
                    tracker = self._budgets.get(rule.id)
                    if tracker:
                        if not tracker.check():
                            budget_exceeded = True
                            budget_rule_matched = rule
                            matched_rule = rule
                            break
                        else:
                            if not dry_run:
                                tracker.consume()
                            budget_remaining = tracker.remaining
                            if matched_rule is None:
                                matched_rule = rule

                elif rule.type == RuleType.REDACT:
                    # Add redaction fields
                    redact_fields.extend(rule.settings.get("fields", []))

        # Determine final decision
        if budget_exceeded:
            return EvaluationResult(
                allowed=False,
                rule_id=budget_rule_matched.id if budget_rule_matched else None,
                rule_type=RuleType.BUDGET,
                budget_exceeded=True,
                budget_remaining=0,
                should_audit=should_audit,
                audit_level=audit_level,
                redact_fields=list(set(redact_fields)),
                reason="Budget exceeded",
            )

        if matched_rule is None:
            # No rule matched, use default action
            allowed = self.policy.default_action == RuleType.ALLOW
            return EvaluationResult(
                allowed=allowed,
                rule_id=None,
                rule_type=None,
                requires_confirmation=False,
                should_audit=should_audit,
                audit_level=audit_level,
                redact_fields=list(set(redact_fields)),
                reason=f"Default action: {self.policy.default_action.value}",
            )

        if matched_rule.type == RuleType.DENY:
            return EvaluationResult(
                allowed=False,
                rule_id=matched_rule.id,
                rule_type=RuleType.DENY,
                should_audit=should_audit,
                audit_level=audit_level,
                redact_fields=list(set(redact_fields)),
                reason=f"Denied by rule: {matched_rule.name}",
            )

        if matched_rule.type == RuleType.ALLOW:
            return EvaluationResult(
                allowed=True,
                rule_id=matched_rule.id,
                rule_type=RuleType.ALLOW,
                requires_confirmation=requires_confirmation,
                confirmation_message=confirmation_message,
                should_audit=should_audit,
                audit_level=audit_level,
                redact_fields=list(set(redact_fields)),
                reason=f"Allowed by rule: {matched_rule.name}",
            )

        if matched_rule.type == RuleType.CONFIRM:
            return EvaluationResult(
                allowed=True,
                rule_id=matched_rule.id,
                rule_type=RuleType.CONFIRM,
                requires_confirmation=True,
                confirmation_message=confirmation_message,
                should_audit=should_audit,
                audit_level=audit_level,
                redact_fields=list(set(redact_fields)),
                reason=f"Requires confirmation: {matched_rule.name}",
            )

        if matched_rule.type == RuleType.BUDGET:
            return EvaluationResult(
                allowed=True,
                rule_id=matched_rule.id,
                rule_type=RuleType.BUDGET,
                budget_exceeded=False,
                budget_remaining=budget_remaining,
                should_audit=should_audit,
                audit_level=audit_level,
                redact_fields=list(set(redact_fields)),
                reason=f"Within budget: {matched_rule.name}",
            )

        # Fallback
        return EvaluationResult(
            allowed=False,
            rule_id=matched_rule.id if matched_rule else None,
            rule_type=matched_rule.type if matched_rule else None,
            should_audit=should_audit,
            audit_level=audit_level,
            redact_fields=list(set(redact_fields)),
            reason="Unknown rule type",
        )

    def consume_budget(
        self,
        method: str,
        path: str,
        host: str,
        headers: dict[str, str] | None = None,
        risk_tier: str | None = None,
        scope: str | None = None,
    ) -> None:
        """Explicitly consume budget for matching rules.

        Called after a final ALLOW decision to debit the budget tracker.
        This is separate from evaluate() to support dry_run evaluation.
        """
        rules = self.policy.get_rules_by_priority()
        for rule in rules:
            if rule.type == RuleType.BUDGET and rule.match.matches(
                method, path, host, headers, risk_tier, scope
            ):
                tracker = self._budgets.get(rule.id)
                if tracker and tracker.check():
                    tracker.consume()

    def reset_budget(self, rule_id: str) -> None:
        """Reset the budget for a specific rule.

        Args:
            rule_id: ID of the budget rule to reset
        """
        if rule_id in self._budgets:
            self._budgets[rule_id].reset()

    def reset_all_budgets(self) -> None:
        """Reset all budget trackers."""
        for tracker in self._budgets.values():
            tracker.reset()

    @classmethod
    def from_yaml(cls, yaml_content: str) -> PolicyEngine:
        """Create a PolicyEngine from YAML string.

        Args:
            yaml_content: YAML policy content

        Returns:
            PolicyEngine instance
        """
        data = yaml.safe_load(yaml_content)
        policy = cls._parse_policy(data)
        return cls(policy)

    @classmethod
    def from_file(cls, file_path: str) -> PolicyEngine:
        """Create a PolicyEngine from YAML file.

        Args:
            file_path: Path to policy YAML file

        Returns:
            PolicyEngine instance
        """
        with open(file_path) as f:
            return cls.from_yaml(f.read())

    @classmethod
    def _parse_policy(cls, data: dict[str, Any]) -> Policy:
        """Parse policy data into Policy model.

        Args:
            data: Raw policy dict

        Returns:
            Policy instance
        """
        schema_version = resolve_schema_version(data, artifact="policy", allow_legacy=True)

        rules = []
        for rule_data in data.get("rules", []):
            match_data = rule_data.get("match", {})
            match = MatchCondition(
                hosts=match_data.get("hosts"),
                host_pattern=match_data.get("host_pattern"),
                paths=match_data.get("paths"),
                path_pattern=match_data.get("path_pattern"),
                methods=match_data.get("methods"),
                headers=match_data.get("headers"),
                risk_tiers=match_data.get("risk_tiers"),
                scopes=match_data.get("scopes"),
            )
            rule = PolicyRule(
                id=rule_data["id"],
                name=rule_data["name"],
                description=rule_data.get("description"),
                type=RuleType(rule_data["type"]),
                match=match,
                priority=rule_data.get("priority", 0),
                settings=rule_data.get("settings", {}),
            )
            rules.append(rule)

        default_action_str = data.get("default_action", "deny")
        default_action = RuleType(default_action_str)

        return Policy(
            version=data.get("version", "1.0.0"),
            schema_version=data.get("schema_version", schema_version or CURRENT_SCHEMA_VERSION),
            name=data["name"],
            description=data.get("description"),
            default_action=default_action,
            rules=rules,
            global_rate_limit=data.get("global_rate_limit"),
            audit_all=data.get("audit_all", True),
            redact_headers=data.get("redact_headers", [
                "authorization", "cookie", "set-cookie", "x-api-key"
            ]),
            redact_patterns=data.get("redact_patterns", []),
            scope=data.get("scope"),
            state_changing_overrides=[
                StateChangingOverride(**override)
                for override in data.get("state_changing_overrides", [])
            ],
        )


class BudgetTracker:
    """Track rate limit budget."""

    def __init__(
        self,
        per_minute: int | None = None,
        per_hour: int | None = None,
    ) -> None:
        """Initialize the budget tracker.

        Args:
            per_minute: Max requests per minute
            per_hour: Max requests per hour
        """
        self.per_minute = per_minute
        self.per_hour = per_hour
        self._minute_count = 0
        self._hour_count = 0
        self._minute_start = time.time()
        self._hour_start = time.time()

    @property
    def remaining(self) -> int:
        """Get remaining budget (minimum of minute/hour limits)."""
        self._check_reset()
        remaining = float("inf")
        if self.per_minute is not None:
            remaining = min(remaining, self.per_minute - self._minute_count)
        if self.per_hour is not None:
            remaining = min(remaining, self.per_hour - self._hour_count)
        return int(remaining) if remaining != float("inf") else 0

    def check(self) -> bool:
        """Check if request is within budget.

        Returns:
            True if within budget
        """
        self._check_reset()

        if self.per_minute is not None and self._minute_count >= self.per_minute:
            return False

        return not (self.per_hour is not None and self._hour_count >= self.per_hour)

    def consume(self) -> None:
        """Consume one unit of budget."""
        self._check_reset()
        self._minute_count += 1
        self._hour_count += 1

    def reset(self) -> None:
        """Reset all counters."""
        self._minute_count = 0
        self._hour_count = 0
        self._minute_start = time.time()
        self._hour_start = time.time()

    def _check_reset(self) -> None:
        """Check if counters should reset based on time."""
        now = time.time()

        # Reset minute counter
        if now - self._minute_start >= 60:
            self._minute_count = 0
            self._minute_start = now

        # Reset hour counter
        if now - self._hour_start >= 3600:
            self._hour_count = 0
            self._hour_start = now
