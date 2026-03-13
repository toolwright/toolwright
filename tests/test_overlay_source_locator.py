"""Tests for source locator - finding editable source for HEAL."""



class TestSourceLocator:
    def test_vendored_path_takes_priority(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.source_locator import SourceLocator

        state_dir = tmp_path / "wrap" / "github"
        vendor_dir = state_dir / "vendor"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / "index.js").write_text("// vendored")

        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            state_dir=state_dir,
        )

        locator = SourceLocator()
        info = locator.locate(config)

        assert info is not None
        assert info.source_type == "vendored"
        assert info.editable is True

    def test_python_script_found(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.source_locator import SourceLocator

        script = tmp_path / "server.py"
        script.write_text("# python server")

        config = WrapConfig(
            server_name="custom",
            target_type=TargetType.STDIO,
            command="python",
            args=[str(script)],
            state_dir=tmp_path / "wrap" / "custom",
        )

        locator = SourceLocator()
        info = locator.locate(config)

        assert info is not None
        assert info.source_type == "python_script"
        assert info.editable is True

    def test_node_script_found(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.source_locator import SourceLocator

        script = tmp_path / "server.js"
        script.write_text("// node server")

        config = WrapConfig(
            server_name="custom",
            target_type=TargetType.STDIO,
            command="node",
            args=[str(script)],
            state_dir=tmp_path / "wrap" / "custom",
        )

        locator = SourceLocator()
        info = locator.locate(config)

        assert info is not None
        assert info.source_type == "node_script"
        assert info.editable is True

    def test_npx_without_vendor_returns_none(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.source_locator import SourceLocator

        config = WrapConfig(
            server_name="github",
            target_type=TargetType.STDIO,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            state_dir=tmp_path / "wrap" / "github",
        )

        locator = SourceLocator()
        info = locator.locate(config)

        assert info is None

    def test_http_target_returns_none(self, tmp_path):
        from toolwright.models.overlay import TargetType, WrapConfig
        from toolwright.overlay.source_locator import SourceLocator

        config = WrapConfig(
            server_name="sentry",
            target_type=TargetType.STREAMABLE_HTTP,
            url="https://mcp.sentry.dev/mcp",
            state_dir=tmp_path / "wrap" / "sentry",
        )

        locator = SourceLocator()
        info = locator.locate(config)

        assert info is None
