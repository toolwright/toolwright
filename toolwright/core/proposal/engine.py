"""ProposalEngine — create, list, review, and promote draft proposals."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from toolwright.models.proposal import (
    DraftProposal,
    MissingCapability,
    ProposalStatus,
)


class ProposalEngine:
    """Manages draft proposals for agent-requested capabilities.

    Proposals are stored under <root>/drafts/<proposal_id>.json.
    Runtime MUST ignore this directory — only `approve` can promote.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.drafts_dir = root / "drafts"
        self.published_dir = root / "published"

    def create_proposal(
        self,
        capability: MissingCapability,
    ) -> DraftProposal:
        """Create a new draft proposal from a MissingCapability."""
        proposal = DraftProposal(capability=capability)
        self._save_proposal(proposal)
        return proposal

    def create_from_denial(
        self,
        *,
        reason_code: str,
        tool_id: str,
        action_name: str = "",
        host: str = "",
        method: str = "",
        agent_context: str | None = None,
    ) -> DraftProposal:
        """Convenience: create proposal from a DecisionEngine denial."""
        # Conservative risk guess based on method
        risk_guess = "high" if method.upper() in ("POST", "PUT", "PATCH", "DELETE") else "medium"

        capability = MissingCapability(
            reason_code=reason_code,
            attempted_action=action_name or tool_id,
            suggested_tool=tool_id,
            suggested_host=host or None,
            risk_guess=risk_guess,
            agent_context=agent_context,
        )
        return self.create_proposal(capability)

    def list_proposals(
        self,
        status: ProposalStatus | None = None,
    ) -> list[DraftProposal]:
        """List all proposals, optionally filtered by status."""
        if not self.drafts_dir.exists():
            return []

        proposals: list[DraftProposal] = []
        for path in sorted(self.drafts_dir.glob("*.json")):
            proposal = self._load_proposal(path)
            if proposal is None:
                continue
            if status is not None and proposal.status != status:
                continue
            proposals.append(proposal)
        return proposals

    def get_proposal(self, proposal_id: str) -> DraftProposal | None:
        """Get a single proposal by ID."""
        path = self.drafts_dir / f"{proposal_id}.json"
        return self._load_proposal(path)

    def approve(
        self,
        proposal_id: str,
        *,
        reviewed_by: str = "human",
    ) -> DraftProposal | None:
        """Approve a proposal — moves it to approved status.

        Note: This marks the proposal as approved but does NOT automatically
        add the capability to any toolpack. That requires a separate
        capture/compile cycle. The approved proposal serves as a record
        that a human reviewed and authorized this capability.
        """
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return None

        proposal.status = ProposalStatus.APPROVED
        proposal.reviewed_at = datetime.now(UTC).isoformat()
        proposal.reviewed_by = reviewed_by
        self._save_proposal(proposal)

        # Also save to published/ as a record
        self.published_dir.mkdir(parents=True, exist_ok=True)
        published_path = self.published_dir / f"{proposal_id}.json"
        published_path.write_text(
            proposal.model_dump_json(indent=2),
            encoding="utf-8",
        )

        return proposal

    def reject(
        self,
        proposal_id: str,
        *,
        reason: str = "",
        reviewed_by: str = "human",
    ) -> DraftProposal | None:
        """Reject a proposal with an optional reason."""
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return None

        proposal.status = ProposalStatus.REJECTED
        proposal.reviewed_at = datetime.now(UTC).isoformat()
        proposal.reviewed_by = reviewed_by
        proposal.rejection_reason = reason
        self._save_proposal(proposal)
        return proposal

    def _save_proposal(self, proposal: DraftProposal) -> Path:
        """Save a proposal to the drafts directory."""
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        path = self.drafts_dir / f"{proposal.proposal_id}.json"
        path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _load_proposal(self, path: Path) -> DraftProposal | None:
        """Load a proposal from a JSON file."""
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return DraftProposal(**data)
        except (json.JSONDecodeError, ValueError):
            return None
