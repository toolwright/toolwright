"""Tests for agent draft proposals — create, list, approve, reject, storage."""

from __future__ import annotations

from pathlib import Path

from toolwright.core.proposal.engine import ProposalEngine
from toolwright.models.proposal import (
    MissingCapability,
    ProposalStatus,
)


def _make_capability(**kwargs) -> MissingCapability:
    defaults = {
        "reason_code": "DENIED_UNKNOWN_ACTION",
        "attempted_action": "create_user",
        "suggested_tool": "create_user",
        "suggested_host": "api.example.com",
    }
    defaults.update(kwargs)
    return MissingCapability(**defaults)


# --- Creation ---

def test_create_proposal(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    cap = _make_capability()
    proposal = engine.create_proposal(cap)
    assert proposal.proposal_id.startswith("prop_")
    assert proposal.status == ProposalStatus.PENDING
    assert proposal.capability.suggested_tool == "create_user"


def test_create_from_denial(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    proposal = engine.create_from_denial(
        reason_code="DENIED_UNKNOWN_ACTION",
        tool_id="delete_user",
        action_name="delete_user",
        host="api.example.com",
        method="DELETE",
        agent_context="Need to remove inactive users",
    )
    assert proposal.capability.risk_guess == "high"  # DELETE = high risk
    assert proposal.capability.agent_context == "Need to remove inactive users"


def test_create_from_denial_get_is_medium_risk(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    proposal = engine.create_from_denial(
        reason_code="DENIED_UNKNOWN_ACTION",
        tool_id="search_users",
        method="GET",
    )
    assert proposal.capability.risk_guess == "medium"


def test_proposal_persisted_to_disk(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    proposal = engine.create_proposal(_make_capability())
    path = tmp_path / "drafts" / f"{proposal.proposal_id}.json"
    assert path.exists()


# --- Listing ---

def test_list_empty(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    assert engine.list_proposals() == []


def test_list_all(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    engine.create_proposal(_make_capability(attempted_action="a"))
    engine.create_proposal(_make_capability(attempted_action="b"))
    proposals = engine.list_proposals()
    assert len(proposals) == 2


def test_list_by_status(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    p1 = engine.create_proposal(_make_capability(attempted_action="a"))
    engine.create_proposal(_make_capability(attempted_action="b"))
    engine.approve(p1.proposal_id)

    pending = engine.list_proposals(status=ProposalStatus.PENDING)
    assert len(pending) == 1

    approved = engine.list_proposals(status=ProposalStatus.APPROVED)
    assert len(approved) == 1


# --- Get ---

def test_get_proposal(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    created = engine.create_proposal(_make_capability())
    loaded = engine.get_proposal(created.proposal_id)
    assert loaded is not None
    assert loaded.proposal_id == created.proposal_id


def test_get_nonexistent(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    assert engine.get_proposal("prop_nonexistent") is None


# --- Approve ---

def test_approve_proposal(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    proposal = engine.create_proposal(_make_capability())
    result = engine.approve(proposal.proposal_id, reviewed_by="admin")
    assert result is not None
    assert result.status == ProposalStatus.APPROVED
    assert result.reviewed_by == "admin"
    assert result.reviewed_at is not None


def test_approve_creates_published_record(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    proposal = engine.create_proposal(_make_capability())
    engine.approve(proposal.proposal_id)
    published_path = tmp_path / "published" / f"{proposal.proposal_id}.json"
    assert published_path.exists()


def test_approve_nonexistent(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    assert engine.approve("prop_nope") is None


# --- Reject ---

def test_reject_proposal(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    proposal = engine.create_proposal(_make_capability())
    result = engine.reject(proposal.proposal_id, reason="Too risky")
    assert result is not None
    assert result.status == ProposalStatus.REJECTED
    assert result.rejection_reason == "Too risky"


def test_reject_nonexistent(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    assert engine.reject("prop_nope") is None


# --- Storage isolation ---

def test_drafts_dir_separate_from_published(tmp_path: Path) -> None:
    engine = ProposalEngine(tmp_path)
    proposal = engine.create_proposal(_make_capability())
    engine.approve(proposal.proposal_id)

    # Both dirs should exist
    assert (tmp_path / "drafts").exists()
    assert (tmp_path / "published").exists()

    # Draft should still be in drafts dir (marked approved)
    draft_path = tmp_path / "drafts" / f"{proposal.proposal_id}.json"
    assert draft_path.exists()


def test_runtime_should_ignore_drafts(tmp_path: Path) -> None:
    """Verify that drafts directory is clearly separate from runtime artifacts."""
    engine = ProposalEngine(tmp_path)
    engine.create_proposal(_make_capability())

    # The runtime looks at toolpacks/, artifacts/, etc.
    # drafts/ must NOT be in any of those paths
    assert (tmp_path / "drafts").exists()
    assert not (tmp_path / "toolpacks").exists()
    assert not (tmp_path / "artifacts").exists()
