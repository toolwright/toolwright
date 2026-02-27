"""Tests for agent proposal wiring into DecisionEngine denials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from toolwright.core.enforce.decision_engine import DecisionEngine
from toolwright.core.proposal.engine import ProposalEngine
from toolwright.models.decision import (
    DecisionContext,
    DecisionRequest,
    DecisionType,
    ReasonCode,
)


def _make_context(*, manifest: dict[str, dict[str, Any]] | None = None) -> DecisionContext:
    return DecisionContext(
        manifest_view=manifest or {},
        lockfile=None,
        require_signed_approvals=False,
    )


class TestDecisionEngineProposalWiring:
    def test_deny_unknown_action_creates_proposal(self, tmp_path: Path) -> None:
        """When a tool is denied (unknown action), a proposal should be created."""
        engine = DecisionEngine()
        proposal_engine = ProposalEngine(root=tmp_path)
        request = DecisionRequest(
            tool_id="get_secret_data",
            method="GET",
            path="/api/secret",
            host="api.example.com",
        )
        context = _make_context()
        result = engine.evaluate(request, context)
        assert result.decision == DecisionType.DENY
        assert result.reason_code == ReasonCode.DENIED_UNKNOWN_ACTION

        # Now create proposal from the denial
        proposal = proposal_engine.create_from_denial(
            reason_code=result.reason_code.value,
            tool_id=request.tool_id,
            action_name=request.action_name or "",
            host=request.host,
            method=request.method,
        )
        assert proposal.capability.reason_code == "denied_unknown_action"
        assert proposal.capability.suggested_tool == "get_secret_data"
        assert proposal.capability.suggested_host == "api.example.com"

        # Verify it was persisted
        proposals = proposal_engine.list_proposals()
        assert len(proposals) == 1
        assert proposals[0].proposal_id == proposal.proposal_id

    def test_deny_not_approved_creates_proposal(self, tmp_path: Path) -> None:
        """When a tool is denied (not approved), a proposal with correct risk."""
        proposal_engine = ProposalEngine(root=tmp_path)
        # Simulate a POST denial
        proposal = proposal_engine.create_from_denial(
            reason_code="denied_not_approved",
            tool_id="create_user",
            action_name="create_user",
            host="api.example.com",
            method="POST",
        )
        assert proposal.capability.risk_guess == "high"  # POST = high risk

    def test_deny_get_has_medium_risk(self, tmp_path: Path) -> None:
        """GET denials should have medium risk."""
        proposal_engine = ProposalEngine(root=tmp_path)
        proposal = proposal_engine.create_from_denial(
            reason_code="denied_not_approved",
            tool_id="get_users",
            method="GET",
        )
        assert proposal.capability.risk_guess == "medium"

    def test_evaluate_with_auto_propose(self, tmp_path: Path) -> None:
        """Integration: evaluate + auto-propose on denial."""
        engine = DecisionEngine()
        proposal_engine = ProposalEngine(root=tmp_path)
        request = DecisionRequest(
            tool_id="delete_account",
            method="DELETE",
            path="/api/account",
            host="api.example.com",
        )
        context = _make_context()
        result = engine.evaluate(request, context)

        # Auto-propose on any denial
        if result.decision == DecisionType.DENY:
            proposal = proposal_engine.create_from_denial(
                reason_code=result.reason_code.value,
                tool_id=request.tool_id,
                action_name=request.action_name or "",
                host=request.host,
                method=request.method,
            )
            assert proposal.capability.risk_guess == "high"  # DELETE = high

        # Verify draft file exists
        drafts = list((tmp_path / "drafts").glob("*.json"))
        assert len(drafts) == 1

        # Verify file content is valid JSON
        data = json.loads(drafts[0].read_text())
        assert data["capability"]["suggested_tool"] == "delete_account"
