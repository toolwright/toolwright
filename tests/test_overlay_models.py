"""Tests for overlay mode data models."""




class TestTargetType:
    def test_stdio_value(self):
        from toolwright.models.overlay import TargetType

        assert TargetType.STDIO == "stdio"

    def test_streamable_http_value(self):
        from toolwright.models.overlay import TargetType

        assert TargetType.STREAMABLE_HTTP == "streamable_http"


class TestWrapConfig:
    def test_stdio_config(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig

        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            state_dir=tmp_path / ".toolwright" / "wrap" / "github",
        )
        assert config.server_name == "github"
        assert config.target_type == TargetType.STDIO
        assert config.command == "npx"
        assert config.url is None
        assert config.auto_approve_safe is False
        assert config.proxy_transport == "stdio"

    def test_http_config(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig

        config = WrapConfig(
            server_name="sentry",
            target_type=TargetType.STREAMABLE_HTTP,
            url="https://mcp.sentry.dev/mcp",
            headers={"Authorization": "Bearer xxx"},
            state_dir=tmp_path / ".toolwright" / "wrap" / "sentry",
        )
        assert config.target_type == TargetType.STREAMABLE_HTTP
        assert config.url == "https://mcp.sentry.dev/mcp"
        assert config.headers == {"Authorization": "Bearer xxx"}
        assert config.command is None

    def test_default_env_and_headers(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig

        config = WrapConfig(
            server_name="test",
            target_type=TargetType.STDIO,
            command="python",
            args=["server.py"],
            state_dir=tmp_path,
        )
        assert config.env == {}
        assert config.headers == {}

    def test_lockfile_path(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig

        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=[],
            state_dir=tmp_path / "wrap" / "github",
        )
        assert config.lockfile_path == tmp_path / "wrap" / "github" / "lockfile.yaml"


class TestWrappedTool:
    def test_basic_tool(self):
        from toolwright.models.overlay import WrappedTool

        tool = WrappedTool(
            name="list_repos",
            description="List repositories",
            input_schema={"type": "object", "properties": {"owner": {"type": "string"}}},
            annotations={},
            risk_tier="low",
            tool_def_digest="abc123def456gh78",
            confirmation_required="never",
        )
        assert tool.name == "list_repos"
        assert tool.risk_tier == "low"

    def test_critical_tool_requires_confirmation(self):
        from toolwright.models.overlay import WrappedTool

        tool = WrappedTool(
            name="delete_repo",
            description="Delete a repository",
            input_schema={"type": "object"},
            annotations={"destructiveHint": True},
            risk_tier="critical",
            tool_def_digest="xyz789",
            confirmation_required="always",
        )
        assert tool.confirmation_required == "always"
        assert tool.risk_tier == "critical"


class TestToolDefDigest:
    def test_deterministic(self):
        from toolwright.models.overlay import compute_tool_def_digest

        digest1 = compute_tool_def_digest(
            name="list_repos",
            description="List repos",
            input_schema={"type": "object"},
            annotations={},
        )
        digest2 = compute_tool_def_digest(
            name="list_repos",
            description="List repos",
            input_schema={"type": "object"},
            annotations={},
        )
        assert digest1 == digest2
        assert len(digest1) == 16  # truncated SHA256

    def test_different_name_different_digest(self):
        from toolwright.models.overlay import compute_tool_def_digest

        d1 = compute_tool_def_digest("list_repos", "desc", {}, {})
        d2 = compute_tool_def_digest("get_repos", "desc", {}, {})
        assert d1 != d2

    def test_different_schema_different_digest(self):
        from toolwright.models.overlay import compute_tool_def_digest

        d1 = compute_tool_def_digest("tool", "desc", {"type": "object"}, {})
        d2 = compute_tool_def_digest("tool", "desc", {"type": "string"}, {})
        assert d1 != d2

    def test_different_annotations_different_digest(self):
        from toolwright.models.overlay import compute_tool_def_digest

        d1 = compute_tool_def_digest("tool", "desc", {}, {})
        d2 = compute_tool_def_digest("tool", "desc", {}, {"readOnlyHint": True})
        assert d1 != d2


class TestDiscoveryResult:
    def test_basic(self):
        from toolwright.models.overlay import DiscoveryResult, WrappedTool

        result = DiscoveryResult(
            tools=[
                WrappedTool(
                    name="t1",
                    description="Tool 1",
                    input_schema={},
                    annotations={},
                    risk_tier="low",
                    tool_def_digest="abc123",
                    confirmation_required="never",
                ),
            ],
            server_name="test",
            server_version="1.0",
        )
        assert len(result.tools) == 1
        assert result.server_name == "test"


class TestSourceInfo:
    def test_vendored(self):
        from toolwright.models.overlay import SourceInfo

        info = SourceInfo(
            source_type="vendored",
            source_path="/path/to/vendor",
            editable=True,
        )
        assert info.editable is True
        assert info.source_type == "vendored"
