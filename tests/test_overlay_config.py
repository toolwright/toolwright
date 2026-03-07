"""Tests for overlay config persistence and server name derivation."""

import pytest
import yaml


class TestDeriveServerName:
    def test_npx_modelcontextprotocol_github(self):
        from toolwright.overlay.config import derive_server_name

        name = derive_server_name("npx", ["-y", "@modelcontextprotocol/server-github"])
        assert name == "github"

    def test_npx_mcp_server_prefix(self):
        from toolwright.overlay.config import derive_server_name

        name = derive_server_name("npx", ["-y", "mcp-server-fetch"])
        assert name == "fetch"

    def test_npx_server_prefix(self):
        from toolwright.overlay.config import derive_server_name

        name = derive_server_name("npx", ["-y", "server-filesystem", "/tmp"])
        assert name == "filesystem"

    def test_npx_scoped_package(self):
        from toolwright.overlay.config import derive_server_name

        name = derive_server_name("npx", ["-y", "@anthropic/mcp-server-brave"])
        assert name == "brave"

    def test_python_script(self):
        from toolwright.overlay.config import derive_server_name

        name = derive_server_name("python", ["-m", "my_mcp_server"])
        assert name == "my-mcp-server"

    def test_docker_container(self):
        from toolwright.overlay.config import derive_server_name

        name = derive_server_name("docker", ["run", "-i", "mcp/postgres"])
        assert name == "postgres"

    def test_bare_command(self):
        from toolwright.overlay.config import derive_server_name

        name = derive_server_name("my-server", [])
        assert name == "my-server"

    def test_strips_at_prefix(self):
        """Should handle npm scoped packages like @foo/bar."""
        from toolwright.overlay.config import derive_server_name

        name = derive_server_name("npx", ["-y", "@foo/server-bar"])
        assert name == "bar"


class TestSaveLoadWrapConfig:
    def test_save_and_load_roundtrip(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.config import load_wrap_config, save_wrap_config

        state_dir = tmp_path / ".toolwright" / "wrap" / "github"
        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_TOKEN": "test"},
            state_dir=state_dir,
        )

        save_wrap_config(config)
        loaded = load_wrap_config(state_dir=state_dir)

        assert loaded is not None
        assert loaded.server_name == "github"
        assert loaded.target_type == TargetType.STDIO
        assert loaded.command == "npx"
        assert loaded.args == ["-y", "@modelcontextprotocol/server-github"]

    def test_save_http_config(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.config import load_wrap_config, save_wrap_config

        state_dir = tmp_path / ".toolwright" / "wrap" / "sentry"
        config = WrapConfig(
            server_name="sentry",
            target_type=TargetType.STREAMABLE_HTTP,
            url="https://mcp.sentry.dev/mcp",
            headers={"Authorization": "Bearer xxx"},
            state_dir=state_dir,
        )

        save_wrap_config(config)
        loaded = load_wrap_config(state_dir=state_dir)

        assert loaded is not None
        assert loaded.target_type == TargetType.STREAMABLE_HTTP
        assert loaded.url == "https://mcp.sentry.dev/mcp"

    def test_load_nonexistent_returns_none(self, tmp_path):
        from toolwright.overlay.config import load_wrap_config

        loaded = load_wrap_config(state_dir=tmp_path / "nonexistent")
        assert loaded is None

    def test_auto_detect_single_wrap(self, tmp_path):
        """When only one wrap config exists, auto-detect it."""
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.config import load_wrap_config, save_wrap_config

        state_dir = tmp_path / ".toolwright" / "wrap" / "github"
        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=[],
            state_dir=state_dir,
        )
        save_wrap_config(config)

        # Auto-detect from parent wrap directory
        wrap_root = tmp_path / ".toolwright" / "wrap"
        loaded = load_wrap_config(wrap_root=wrap_root)
        assert loaded is not None
        assert loaded.server_name == "github"


class TestClientConfigOutput:
    def test_stdio_config_output(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.config import build_client_config

        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=[],
            state_dir=tmp_path,
        )

        output = build_client_config(config)

        assert "claude_desktop" in output
        assert "claude_code" in output
        assert "github" in output["claude_desktop"]["mcpServers"]

    def test_http_config_output(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.config import build_client_config

        config = WrapConfig(
            server_name="sentry",
            target_type=TargetType.STREAMABLE_HTTP,
            url="https://mcp.sentry.dev/mcp",
            state_dir=tmp_path,
            proxy_transport="http",
        )

        output = build_client_config(config, proxy_port=8745)

        assert "claude_desktop" in output
        assert "claude_code" in output
