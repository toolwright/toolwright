"""Tests for toolwright_request_capability meta-tool."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from toolwright.mcp.meta_server import ToolwrightMetaMCPServer
from toolwright.models.capture import (
    CaptureSession,
    CaptureSource,
    HttpExchange,
    HTTPMethod,
)
from toolwright.models.proposal import ProposalStatus


def _mock_capture_session() -> CaptureSession:
    """Create a minimal CaptureSession for testing."""
    exchanges = [
        HttpExchange(
            id=f"ex_{i}",
            url=f"https://api.example.com/{path}",
            method=HTTPMethod.GET,
            host="api.example.com",
            path=f"/{path}",
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
        )
        for i, path in enumerate(["users", "posts", "comments"])
    ]
    return CaptureSession(
        id="cap_test_123",
        name="Test API",
        description=None,
        created_at=datetime.now(UTC),
        source=CaptureSource.MANUAL,
        source_file=None,
        allowed_hosts=["api.example.com"],
        exchanges=exchanges,
        total_requests=3,
        filtered_requests=0,
        redacted_count=0,
        warnings=[],
    )


class TestRequestCapabilityRegistration:
    """Verify tool is registered correctly."""

    @pytest.mark.asyncio
    async def test_tool_listed(self, tmp_path: Path) -> None:
        """Tool appears in _handle_list_tools()."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        tools = await server._handle_list_tools()
        names = [t.name for t in tools]
        assert "toolwright_request_capability" in names

    @pytest.mark.asyncio
    async def test_tool_has_description(self, tmp_path: Path) -> None:
        """Description mentions 'capability' or 'request'."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        tools = await server._handle_list_tools()
        tool = next(t for t in tools if t.name == "toolwright_request_capability")
        desc_lower = tool.description.lower()
        assert "capability" in desc_lower or "request" in desc_lower


class TestRequestCapabilitySuccess:
    """Verify behaviour when OpenAPI spec is discovered."""

    @pytest.mark.asyncio
    async def test_returns_proposal_id(self, tmp_path: Path) -> None:
        """Response text contains a proposal ID (prop_ prefix)."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            result = await server._handle_call_tool(
                "toolwright_request_capability", {"host": "https://api.example.com"}
            )
        text = result[0].text
        assert "prop_" in text

    @pytest.mark.asyncio
    async def test_returns_tools_discovered_count(self, tmp_path: Path) -> None:
        """Response mentions the number of exchanges found (3)."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            result = await server._handle_call_tool(
                "toolwright_request_capability", {"host": "https://api.example.com"}
            )
        text = result[0].text
        assert "3" in text

    @pytest.mark.asyncio
    async def test_returns_next_steps(self, tmp_path: Path) -> None:
        """Response contains guidance that human must review/approve."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            result = await server._handle_call_tool(
                "toolwright_request_capability", {"host": "https://api.example.com"}
            )
        text = result[0].text.lower()
        assert "review" in text or "approve" in text or "human" in text

    @pytest.mark.asyncio
    async def test_creates_proposal_on_disk(self, tmp_path: Path) -> None:
        """Proposal JSON file exists under state_dir after success."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            await server._handle_call_tool(
                "toolwright_request_capability", {"host": "https://api.example.com"}
            )
        # ProposalEngine saves under <root>/drafts/<proposal_id>.json
        proposals_dir = tmp_path / "proposals" / "drafts"
        json_files = list(proposals_dir.glob("*.json"))
        assert len(json_files) == 1

    @pytest.mark.asyncio
    async def test_proposal_status_is_pending(self, tmp_path: Path) -> None:
        """Created proposal has PENDING status (trust boundary)."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            await server._handle_call_tool(
                "toolwright_request_capability", {"host": "https://api.example.com"}
            )
        proposals_dir = tmp_path / "proposals" / "drafts"
        json_files = list(proposals_dir.glob("*.json"))
        data = json.loads(json_files[0].read_text())
        assert data["status"] == ProposalStatus.PENDING.value


class TestRequestCapabilityNoSpec:
    """Verify behaviour when no OpenAPI spec is found."""

    @pytest.mark.asyncio
    async def test_returns_not_found_message(self, tmp_path: Path) -> None:
        """When discovery returns None, message says no spec found."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await server._handle_call_tool(
                "toolwright_request_capability", {"host": "https://api.example.com"}
            )
        text = result[0].text.lower()
        assert "no" in text and ("spec" in text or "found" in text)

    @pytest.mark.asyncio
    async def test_no_proposal_created(self, tmp_path: Path) -> None:
        """No proposal file on disk when spec not found."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await server._handle_call_tool(
                "toolwright_request_capability", {"host": "https://api.example.com"}
            )
        proposals_dir = tmp_path / "proposals" / "drafts"
        if proposals_dir.exists():
            assert list(proposals_dir.glob("*.json")) == []


class TestRequestCapabilityMissingHost:
    """Verify error handling for missing parameters."""

    @pytest.mark.asyncio
    async def test_error_when_no_host(self, tmp_path: Path) -> None:
        """Call without host param returns error message."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        result = await server._handle_call_tool(
            "toolwright_request_capability", {}
        )
        text = result[0].text.lower()
        assert "error" in text or "required" in text


class TestRequestCapabilityConcise:
    """Verify output stays concise for agent consumption."""

    @pytest.mark.asyncio
    async def test_output_under_300_chars(self, tmp_path: Path) -> None:
        """Response is under 300 characters."""
        server = ToolwrightMetaMCPServer(state_dir=tmp_path)
        with patch(
            "toolwright.core.discover.openapi.OpenAPIDiscovery.discover",
            new_callable=AsyncMock,
            return_value=_mock_capture_session(),
        ):
            result = await server._handle_call_tool(
                "toolwright_request_capability", {"host": "https://api.example.com"}
            )
        text = result[0].text
        assert len(text) < 300, f"Response too long ({len(text)} chars): {text}"
