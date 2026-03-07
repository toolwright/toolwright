"""Tests for overlay tool discovery, risk classification, and manifest generation."""

from unittest.mock import MagicMock

import pytest


def _mock_mcp_tool(name, description=None, input_schema=None, annotations=None):
    """Create a mock MCP Tool object."""
    tool = MagicMock()
    tool.name = name
    tool.description = description or ""
    tool.inputSchema = input_schema or {"type": "object", "properties": {}}
    # MCP annotations are an optional attribute
    if annotations is not None:
        tool.annotations = annotations
    else:
        tool.annotations = None
    return tool


class TestClassifyRisk:
    def test_delete_is_critical(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("delete_repository")
        assert classify_risk(tool) == "critical"

    def test_remove_is_critical(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("remove_user")
        assert classify_risk(tool) == "critical"

    def test_destroy_is_critical(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("destroy_database")
        assert classify_risk(tool) == "critical"

    def test_drop_is_critical(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("drop_table")
        assert classify_risk(tool) == "critical"

    def test_purge_is_critical(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("purge_cache")
        assert classify_risk(tool) == "critical"

    def test_revoke_is_critical(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("revoke_token")
        assert classify_risk(tool) == "critical"

    def test_create_is_high(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("create_issue")
        assert classify_risk(tool) == "high"

    def test_update_is_high(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("update_profile")
        assert classify_risk(tool) == "high"

    def test_send_is_high(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("send_message")
        assert classify_risk(tool) == "high"

    def test_execute_is_high(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("execute_query")
        assert classify_risk(tool) == "high"

    def test_list_is_low_with_readonly_hint(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool(
            "list_repos",
            annotations=MagicMock(readOnlyHint=True, destructiveHint=None),
        )
        assert classify_risk(tool) == "low"

    def test_list_is_low_without_destructive_hint(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool(
            "list_repos",
            annotations=MagicMock(readOnlyHint=None, destructiveHint=False),
        )
        assert classify_risk(tool) == "low"

    def test_list_is_low_with_no_annotations(self):
        """list_* with no annotations defaults to low (heuristic only)."""
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("list_repos")
        assert classify_risk(tool) == "low"

    def test_get_is_low(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("get_user")
        assert classify_risk(tool) == "low"

    def test_search_is_low(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("search_files")
        assert classify_risk(tool) == "low"

    def test_read_heuristic_with_destructive_hint_is_medium(self):
        """When name says read but hints say destructive → medium (cautious)."""
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool(
            "read_data",
            annotations=MagicMock(readOnlyHint=False, destructiveHint=True),
        )
        assert classify_risk(tool) == "medium"

    def test_unknown_name_defaults_to_high(self):
        from toolwright.overlay.discovery import classify_risk

        tool = _mock_mcp_tool("do_something")
        assert classify_risk(tool) == "high"


class TestToolDefDigest:
    def test_uses_model_function(self):
        from toolwright.overlay.discovery import tool_def_digest

        tool = _mock_mcp_tool(
            "list_repos",
            description="List repositories",
            input_schema={"type": "object"},
        )
        digest = tool_def_digest(tool)
        assert len(digest) == 16
        assert isinstance(digest, str)

    def test_deterministic(self):
        from toolwright.overlay.discovery import tool_def_digest

        tool = _mock_mcp_tool("list_repos", description="List repos")
        assert tool_def_digest(tool) == tool_def_digest(tool)


class TestBuildSyntheticManifest:
    def test_builds_actions_from_discovery(self, tmp_path):
        from toolwright.models.overlay import DiscoveryResult, TargetType, WrapConfig, WrappedTool
        from toolwright.overlay.discovery import build_synthetic_manifest

        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=[],
            state_dir=tmp_path,
        )
        discovery = DiscoveryResult(
            tools=[
                WrappedTool(
                    name="list_repos",
                    description="List repositories",
                    input_schema={"type": "object", "properties": {"owner": {"type": "string"}}},
                    annotations={},
                    risk_tier="low",
                    tool_def_digest="abc123def456gh78",
                    confirmation_required="never",
                ),
                WrappedTool(
                    name="delete_repo",
                    description="Delete a repository",
                    input_schema={"type": "object"},
                    annotations={},
                    risk_tier="critical",
                    tool_def_digest="xyz789abcdef1234",
                    confirmation_required="always",
                ),
            ],
            server_name="github",
            server_version="1.0",
        )

        manifest = build_synthetic_manifest(discovery, config)

        assert "actions" in manifest
        actions = manifest["actions"]
        assert len(actions) == 2

        # Check first action
        list_action = next(a for a in actions if a["name"] == "list_repos")
        assert list_action["method"] == "MCP"
        assert list_action["path"] == "mcp://github/list_repos"
        assert list_action["host"] == "github"
        assert list_action["risk_tier"] == "low"
        assert list_action["signature_id"] == "abc123def456gh78"
        assert list_action["tool_id"] == "list_repos"
        assert list_action["confirmation_required"] == "never"

        # Check critical action
        delete_action = next(a for a in actions if a["name"] == "delete_repo")
        assert delete_action["risk_tier"] == "critical"
        assert delete_action["confirmation_required"] == "always"

    def test_manifest_has_schema_version(self, tmp_path):
        from toolwright.models.overlay import DiscoveryResult, TargetType, WrapConfig
        from toolwright.overlay.discovery import build_synthetic_manifest

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="test",
            args=[],
            state_dir=tmp_path,
        )
        discovery = DiscoveryResult(tools=[], server_name="test")
        manifest = build_synthetic_manifest(discovery, config)

        assert "schema_version" in manifest


class TestDiscoverTools:
    @pytest.mark.asyncio
    async def test_discover_from_connection(self, tmp_path):
        from unittest.mock import AsyncMock

        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.discovery import discover_tools

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="test",
            args=[],
            state_dir=tmp_path,
        )

        mock_conn = AsyncMock()
        mock_conn.list_tools = AsyncMock(
            return_value=[
                _mock_mcp_tool("list_files", "List files in directory"),
                _mock_mcp_tool("delete_file", "Delete a file"),
            ]
        )

        result = await discover_tools(mock_conn, config)

        assert len(result.tools) == 2
        assert result.server_name == "test"

        list_tool = next(t for t in result.tools if t.name == "list_files")
        assert list_tool.risk_tier == "low"

        delete_tool = next(t for t in result.tools if t.name == "delete_file")
        assert delete_tool.risk_tier == "critical"
        assert delete_tool.confirmation_required == "always"
