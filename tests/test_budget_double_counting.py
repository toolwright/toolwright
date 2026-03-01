"""Tests for budget double-counting fix (F-039/F-040)."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.enforce import ConfirmationStore, DecisionEngine, PolicyEngine
from toolwright.models.decision import DecisionContext, DecisionRequest, DecisionType
from toolwright.models.policy import (
    MatchCondition,
    Policy,
    PolicyRule,
    RuleType,
)


def _budget_policy(max_per_minute: int = 3) -> Policy:
    """Policy with budget rule limiting calls per minute."""
    return Policy(
        name="budget_test",
        default_action=RuleType.DENY,
        rules=[
            PolicyRule(
                id="allow_gets",
                name="Allow GETs",
                type=RuleType.ALLOW,
                priority=100,
                match=MatchCondition(methods=["GET"]),
            ),
            PolicyRule(
                id="confirm_writes",
                name="Confirm writes",
                type=RuleType.CONFIRM,
                priority=90,
                match=MatchCondition(methods=["POST", "PUT", "PATCH", "DELETE"]),
                settings={"message": "Write requires confirmation"},
            ),
            PolicyRule(
                id="budget_writes",
                name="Budget for writes",
                type=RuleType.BUDGET,
                priority=80,
                match=MatchCondition(methods=["POST", "PUT", "PATCH", "DELETE"]),
                settings={"per_minute": max_per_minute},
            ),
        ],
    )


def _action(method: str = "POST") -> dict[str, object]:
    return {
        "name": "create_product",
        "tool_id": "sig_create_product",
        "signature_id": "sig_create_product",
        "method": method,
        "path": "/admin/api/2024-01/products.json",
        "host": "store.myshopify.com",
        "risk_tier": "medium",
    }


def _context(
    action: dict[str, object],
    policy: Policy,
    _confirmation_store: ConfirmationStore | None = None,  # noqa: ARG001
) -> DecisionContext:
    policy_engine = PolicyEngine(policy)
    return DecisionContext(
        manifest_view={
            "sig_create_product": action,
            "create_product": action,
        },
        policy=policy,
        policy_engine=policy_engine,
        lockfile=None,
        artifacts_digest_current="digest_current",
        lockfile_digest_current=None,
    )


def _make_request(
    confirmation_token_id: str | None = None,
) -> DecisionRequest:
    """Create a DecisionRequest for a POST write action."""
    return DecisionRequest(
        tool_id="sig_create_product",
        action_name="create_product",
        method="POST",
        path="/admin/api/2024-01/products.json",
        host="store.myshopify.com",
        mode="execute",
        params={},
        confirmation_token_id=confirmation_token_id,
    )


class TestBudgetDoubleCountingFix:
    """F-039/F-040: Confirmed calls should consume 1 budget unit, not 2."""

    def test_confirm_decision_consumes_zero_budget(self, tmp_path: Path):
        """Challenge creation (CONFIRM result) consumes 0 budget."""
        policy = _budget_policy(max_per_minute=3)
        store = ConfirmationStore(tmp_path / "confirmations.db")
        engine = DecisionEngine(store)
        action = _action("POST")
        ctx = _context(action, policy, store)

        # First call: should get CONFIRM (challenge creation)
        result = engine.evaluate(_make_request(), ctx)
        assert result.decision == DecisionType.CONFIRM

        # Budget should NOT have been consumed
        budget_tracker = ctx.policy_engine._budgets.get("budget_writes")
        assert budget_tracker is not None
        assert budget_tracker._minute_count == 0, (
            f"Challenge creation consumed {budget_tracker._minute_count} budget units, expected 0"
        )

    def test_confirmed_call_consumes_one_budget_unit(self, tmp_path: Path):
        """Full confirmed call (challenge + grant + redeem) consumes exactly 1 budget unit."""
        policy = _budget_policy(max_per_minute=3)
        store = ConfirmationStore(tmp_path / "confirmations.db")
        engine = DecisionEngine(store)
        action = _action("POST")
        ctx = _context(action, policy, store)

        # Step 1: Get challenge
        result1 = engine.evaluate(_make_request(), ctx)
        assert result1.decision == DecisionType.CONFIRM
        token_id = result1.confirmation_token_id
        assert token_id is not None

        # Step 2: Grant the challenge
        store.grant(token_id)

        # Step 3: Redeem with token
        result2 = engine.evaluate(_make_request(confirmation_token_id=token_id), ctx)
        assert result2.decision == DecisionType.ALLOW

        # Budget should have been consumed exactly once
        budget_tracker = ctx.policy_engine._budgets.get("budget_writes")
        assert budget_tracker is not None
        assert budget_tracker._minute_count == 1, (
            f"Full confirmed call consumed {budget_tracker._minute_count} budget units, expected 1"
        )

    def test_max_calls_3_allows_3_confirmed_calls(self, tmp_path: Path):
        """max_calls=3 allows exactly 3 confirmed calls, not 1-2."""
        policy = _budget_policy(max_per_minute=3)
        store = ConfirmationStore(tmp_path / "confirmations.db")
        engine = DecisionEngine(store)
        action = _action("POST")
        ctx = _context(action, policy, store)

        for i in range(3):
            # Challenge
            result = engine.evaluate(_make_request(), ctx)
            assert result.decision == DecisionType.CONFIRM, f"Call {i+1}: expected CONFIRM"
            token_id = result.confirmation_token_id

            # Grant and redeem
            store.grant(token_id)
            result = engine.evaluate(
                _make_request(confirmation_token_id=token_id), ctx
            )
            assert result.decision == DecisionType.ALLOW, f"Call {i+1}: expected ALLOW"

        budget_tracker = ctx.policy_engine._budgets.get("budget_writes")
        assert budget_tracker is not None
        assert budget_tracker._minute_count == 3

    def test_direct_allow_still_consumes_one_budget(self):
        """Direct ALLOW (no confirmation) still consumes 1 budget (no regression).

        BUDGET rules must be higher priority than ALLOW to be evaluated first,
        since ALLOW breaks the loop. This mirrors real configs where budget
        acts as a gate before the allow decision.
        """
        policy = Policy(
            name="direct_budget_test",
            default_action=RuleType.DENY,
            rules=[
                PolicyRule(
                    id="budget_all",
                    name="Budget all",
                    type=RuleType.BUDGET,
                    priority=100,
                    match=MatchCondition(),
                    settings={"per_minute": 5},
                ),
                PolicyRule(
                    id="allow_all",
                    name="Allow all",
                    type=RuleType.ALLOW,
                    priority=80,
                    match=MatchCondition(),
                ),
            ],
        )
        engine = PolicyEngine(policy)

        # Evaluate in default mode (no dry_run) for direct PolicyEngine usage
        result = engine.evaluate(
            method="GET",
            path="/api/products",
            host="example.com",
            risk_tier="low",
        )
        assert result.allowed

        budget_tracker = engine._budgets.get("budget_all")
        assert budget_tracker is not None
        assert budget_tracker._minute_count == 1
