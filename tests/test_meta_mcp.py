"""Tests for Toolwright Meta MCP server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolwright.core.approval import LockfileManager
from toolwright.mcp.meta_server import ToolwrightMetaMCPServer


@pytest.fixture
def sample_manifest(tmp_path: Path) -> Path:
    """Create a sample tools manifest."""
    manifest = {
        "actions": [
            {
                "name": "get_users",
                "method": "GET",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "low",
                "description": "List all users",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "create_user",
                "method": "POST",
                "path": "/api/users",
                "host": "api.example.com",
                "risk_tier": "high",
                "description": "Create a new user",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
            {
                "name": "delete_user",
                "method": "DELETE",
                "path": "/api/users/{id}",
                "host": "api.example.com",
                "risk_tier": "critical",
                "description": "Delete a user",
                "input_schema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
            },
        ]
    }
    tools_path = tmp_path / "tools.json"
    with open(tools_path, "w") as f:
        json.dump(manifest, f)
    return tools_path


@pytest.fixture
def sample_lockfile(tmp_path: Path, sample_manifest: Path) -> Path:
    """Create a sample lockfile with some approvals."""
    lockfile_path = tmp_path / "toolwright.lock.yaml"

    # Load manifest and sync
    with open(sample_manifest) as f:
        manifest = json.load(f)

    manager = LockfileManager(lockfile_path)
    manager.load()
    manager.sync_from_manifest(manifest)

    # Approve one tool
    manager.approve("get_users", "test@example.com")
    manager.save()

    return lockfile_path


class TestToolwrightMetaMCPServer:
    """Tests for ToolwrightMetaMCPServer."""

    def test_init_with_tools_path(self, sample_manifest: Path) -> None:
        """Test initialization with tools path."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)
        assert server.manifest is not None
        assert len(server.manifest["actions"]) == 3

    def test_init_without_manifest(self) -> None:
        """Test initialization without manifest."""
        server = ToolwrightMetaMCPServer()
        assert server.manifest is None

    def test_server_initialized(self, sample_manifest: Path) -> None:
        """Test that server is properly initialized with handlers."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)

        # Verify server is created
        assert server.server is not None
        assert server.server.name == "toolwright-meta"

    @pytest.mark.asyncio
    async def test_list_actions(self, sample_manifest: Path) -> None:
        """Test listing actions from manifest."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)
        result = await server._list_actions({})

        data = json.loads(result[0].text)
        assert data["total"] == 3
        assert len(data["actions"]) == 3

        # Check action details
        action_names = [a["name"] for a in data["actions"]]
        assert "get_users" in action_names
        assert "create_user" in action_names
        assert "delete_user" in action_names

    @pytest.mark.asyncio
    async def test_list_actions_filter_by_risk(self, sample_manifest: Path) -> None:
        """Test filtering actions by risk tier."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)
        result = await server._list_actions({"filter_risk": "high"})

        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert data["actions"][0]["name"] == "create_user"

    @pytest.mark.asyncio
    async def test_list_actions_filter_by_method(self, sample_manifest: Path) -> None:
        """Test filtering actions by HTTP method."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)
        result = await server._list_actions({"filter_method": "GET"})

        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert data["actions"][0]["name"] == "get_users"

    @pytest.mark.asyncio
    async def test_get_action_details(self, sample_manifest: Path) -> None:
        """Test getting action details."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)
        result = await server._get_action_details({"action_name": "get_users"})

        data = json.loads(result[0].text)
        assert data["name"] == "get_users"
        assert data["method"] == "GET"
        assert data["path"] == "/api/users"
        assert data["risk_tier"] == "low"

    @pytest.mark.asyncio
    async def test_get_action_details_not_found(self, sample_manifest: Path) -> None:
        """Test getting details for nonexistent action."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)
        result = await server._get_action_details({"action_name": "nonexistent"})

        data = json.loads(result[0].text)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_risk_summary(self, sample_manifest: Path) -> None:
        """Test risk summary."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)
        result = await server._risk_summary()

        data = json.loads(result[0].text)
        assert data["total_actions"] == 3
        assert data["by_risk_tier"]["low"]["count"] == 1
        assert data["by_risk_tier"]["high"]["count"] == 1
        assert data["by_risk_tier"]["critical"]["count"] == 1

    @pytest.mark.asyncio
    async def test_get_approval_status_with_lockfile(
        self, sample_manifest: Path, sample_lockfile: Path
    ) -> None:
        """Test getting approval status with lockfile."""
        server = ToolwrightMetaMCPServer(
            tools_path=sample_manifest,
            lockfile_path=sample_lockfile,
        )
        result = await server._get_approval_status({"action_name": "get_users"})

        data = json.loads(result[0].text)
        assert data["action"] == "get_users"
        assert data["status"] == "approved"
        assert data["approved_by"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_get_approval_status_pending(
        self, sample_manifest: Path, sample_lockfile: Path
    ) -> None:
        """Test getting approval status for pending action."""
        server = ToolwrightMetaMCPServer(
            tools_path=sample_manifest,
            lockfile_path=sample_lockfile,
        )
        result = await server._get_approval_status({"action_name": "create_user"})

        data = json.loads(result[0].text)
        assert data["action"] == "create_user"
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_pending_approvals(
        self, sample_manifest: Path, sample_lockfile: Path
    ) -> None:
        """Test listing pending approvals."""
        server = ToolwrightMetaMCPServer(
            tools_path=sample_manifest,
            lockfile_path=sample_lockfile,
        )
        result = await server._list_pending_approvals()

        data = json.loads(result[0].text)
        assert data["total_pending"] == 2  # create_user and delete_user

        pending_names = [a["name"] for a in data["pending_actions"]]
        assert "create_user" in pending_names
        assert "delete_user" in pending_names
        assert "get_users" not in pending_names  # Already approved

    @pytest.mark.asyncio
    async def test_check_policy_no_policy(self, sample_manifest: Path) -> None:
        """Test policy check without policy loaded."""
        server = ToolwrightMetaMCPServer(tools_path=sample_manifest)
        result = await server._check_policy({"action_name": "get_users"})

        data = json.loads(result[0].text)
        assert data["action"] == "get_users"
        assert data["policy_loaded"] is False
