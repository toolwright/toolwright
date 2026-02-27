"""Integration test: capability expansion lifecycle.

Agent requests → OpenAPI discovered → draft created → human approves.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from toolwright.core.discover.draft_toolpack import DraftToolpackCreator
from toolwright.core.proposal.engine import ProposalEngine
from toolwright.mcp.meta_server import ToolwrightMetaMCPServer
from toolwright.models.capture import (
    CaptureSession,
    CaptureSource,
    HttpExchange,
    HTTPMethod,
)
from toolwright.models.proposal import ProposalStatus

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _mock_capture_session() -> CaptureSession:
    """Create a minimal CaptureSession for testing."""
    return CaptureSession(
        id="cap_test_123",
        name="Test API",
        description=None,
        created_at=datetime.now(UTC),
        source=CaptureSource.MANUAL,
        source_file=None,
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                id="ex_1",
                url="https://api.example.com/users",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/users",
                request_headers={},
                request_body=None,
                request_body_json=None,
                response_status=200,
                response_headers={},
                response_body=None,
                response_body_json=None,
                response_content_type=None,
                timestamp=None,
                duration_ms=None,
                source=CaptureSource.MANUAL,
                redacted_fields=[],
                notes={},
            ),
            HttpExchange(
                id="ex_2",
                url="https://api.example.com/items",
                method=HTTPMethod.POST,
                host="api.example.com",
                path="/items",
                request_headers={},
                request_body=None,
                request_body_json=None,
                response_status=201,
                response_headers={},
                response_body=None,
                response_body_json=None,
                response_content_type=None,
                timestamp=None,
                duration_ms=None,
                source=CaptureSource.MANUAL,
                redacted_fields=[],
                notes={},
            ),
        ],
        total_requests=2,
        filtered_requests=0,
        redacted_count=0,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# TestCapabilityExpansionLifecycle
# ---------------------------------------------------------------------------


class TestCapabilityExpansionLifecycle:
    """Integration tests covering the full capability expansion flow:

    1. Agent calls toolwright_request_capability with a host
    2. OpenAPI spec is discovered (mocked)
    3. Draft proposal is created (PENDING)
    4. Draft toolpack is created
    5. Human approves → proposal moves to APPROVED
    """

    @pytest.mark.asyncio
    async def test_agent_request_creates_proposal(self, tmp_path: Path) -> None:
        """Agent request via meta-tool creates a proposal file on disk."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            result = await server._handle_call_tool(
                "toolwright_request_capability",
                {"host": "https://api.example.com"},
            )

        # Response should mention a proposal ID
        text = result[0].text
        assert "prop_" in text

        # Proposal JSON file should exist on disk
        proposals_dir = tmp_path / "proposals" / "drafts"
        json_files = list(proposals_dir.glob("*.json"))
        assert len(json_files) == 1

    @pytest.mark.asyncio
    async def test_proposal_is_pending(self, tmp_path: Path) -> None:
        """After requesting, the proposal status is PENDING."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            await server._handle_call_tool(
                "toolwright_request_capability",
                {"host": "https://api.example.com"},
            )

        # Load via ProposalEngine and verify status
        engine = ProposalEngine(root=tmp_path / "proposals")
        proposals = engine.list_proposals()
        assert len(proposals) == 1
        assert proposals[0].status == ProposalStatus.PENDING

    def test_draft_toolpack_can_be_created(self, tmp_path: Path) -> None:
        """DraftToolpackCreator produces a draft with draft: true in toolpack.yaml."""
        session = _mock_capture_session()
        drafts_root = tmp_path / "draft_toolpacks"
        creator = DraftToolpackCreator(drafts_root=drafts_root)
        draft_id = creator.create(session, label="example-api")

        draft_dir = drafts_root / draft_id

        # toolpack.yaml exists with draft: true
        toolpack_yaml = draft_dir / "toolpack.yaml"
        assert toolpack_yaml.is_file()
        content = yaml.safe_load(toolpack_yaml.read_text())
        assert content["draft"] is True

        # tools.json exists with actions
        tools_json = draft_dir / "tools.json"
        assert tools_json.is_file()
        data = json.loads(tools_json.read_text())
        assert "actions" in data
        assert len(data["actions"]) == 2  # GET /users + POST /items

    @pytest.mark.asyncio
    async def test_human_approves_proposal(self, tmp_path: Path) -> None:
        """After agent request, human can approve and status becomes APPROVED."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            await server._handle_call_tool(
                "toolwright_request_capability",
                {"host": "https://api.example.com"},
            )

        # Find proposal ID
        engine = ProposalEngine(root=tmp_path / "proposals")
        proposals = engine.list_proposals(status=ProposalStatus.PENDING)
        assert len(proposals) == 1
        proposal_id = proposals[0].proposal_id

        # Human approves
        approved = engine.approve(proposal_id)
        assert approved is not None
        assert approved.status == ProposalStatus.APPROVED
        assert approved.reviewed_by == "human"

        # Re-load from disk to confirm persistence
        reloaded = engine.get_proposal(proposal_id)
        assert reloaded is not None
        assert reloaded.status == ProposalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_full_flow_end_to_end(self, tmp_path: Path) -> None:
        """Full lifecycle: agent requests → proposal → draft toolpack → human approves.

        All artifacts exist on disk and states are correct.
        """
        session = _mock_capture_session()

        # Step 1: Agent requests capability via meta-tool
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=session,
        ):
            result = await server._handle_call_tool(
                "toolwright_request_capability",
                {"host": "https://api.example.com"},
            )
        text = result[0].text
        assert "prop_" in text
        assert "PENDING" in text

        # Step 2: Verify proposal on disk
        engine = ProposalEngine(root=tmp_path / "proposals")
        proposals = engine.list_proposals()
        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.status == ProposalStatus.PENDING
        assert proposal.capability.suggested_host == "https://api.example.com"

        # Step 3: Create draft toolpack from the same session
        drafts_root = tmp_path / "draft_toolpacks"
        creator = DraftToolpackCreator(drafts_root=drafts_root)
        draft_id = creator.create(session, label="example-api")

        draft_dir = drafts_root / draft_id
        assert (draft_dir / "tools.json").is_file()
        assert (draft_dir / "toolpack.yaml").is_file()
        assert (draft_dir / "manifest.json").is_file()

        tools_data = json.loads((draft_dir / "tools.json").read_text())
        assert len(tools_data["actions"]) == 2

        toolpack_data = yaml.safe_load((draft_dir / "toolpack.yaml").read_text())
        assert toolpack_data["draft"] is True
        assert toolpack_data["host"] == "api.example.com"

        # Step 4: Human approves the proposal
        approved = engine.approve(proposal.proposal_id)
        assert approved is not None
        assert approved.status == ProposalStatus.APPROVED

        # Approved proposal also saved to published/
        published_path = (
            tmp_path / "proposals" / "published" / f"{proposal.proposal_id}.json"
        )
        assert published_path.is_file()
        published_data = json.loads(published_path.read_text())
        assert published_data["status"] == ProposalStatus.APPROVED.value
