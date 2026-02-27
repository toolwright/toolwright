"""Parity tests for decision outputs across enforce/mcp call sources."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.enforce import ConfirmationStore, DecisionEngine, PolicyEngine
from toolwright.models.decision import DecisionContext, DecisionRequest
from toolwright.models.policy import MatchCondition, Policy, PolicyRule, RuleType


def test_same_request_has_identical_decision_for_enforce_and_mcp_sources(tmp_path: Path) -> None:
    policy = Policy(
        name="parity",
        rules=[
            PolicyRule(
                id="allow_get",
                name="Allow GET",
                type=RuleType.ALLOW,
                priority=100,
                match=MatchCondition(methods=["GET"]),
            )
        ],
    )
    action = {
        "name": "get_user",
        "tool_id": "sig_get_user",
        "signature_id": "sig_get_user",
        "method": "GET",
        "path": "/api/users/{id}",
        "host": "api.example.com",
    }

    engine = DecisionEngine(ConfirmationStore(tmp_path / "confirmations.db"))
    context = DecisionContext(
        manifest_view={"sig_get_user": action, "get_user": action},
        policy=policy,
        policy_engine=PolicyEngine(policy),
        artifacts_digest_current="digest",
    )

    enforce_result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_get_user",
            action_name="get_user",
            method="GET",
            path="/api/users/{id}",
            host="api.example.com",
            params={"id": "123"},
            source="enforce",
            mode="execute",
        ),
        context,
    )
    mcp_result = engine.evaluate(
        DecisionRequest(
            tool_id="sig_get_user",
            action_name="get_user",
            method="GET",
            path="/api/users/{id}",
            host="api.example.com",
            params={"id": "123"},
            source="mcp",
            mode="execute",
        ),
        context,
    )

    assert enforce_result.model_dump() == mcp_result.model_dump()
