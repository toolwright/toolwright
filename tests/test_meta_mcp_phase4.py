"""Tests for inspect MCP read-only tooling."""

from __future__ import annotations

class TestMetaServerReadOnlyTools:
    """`mcp inspect` must remain introspection-only."""

    def test_meta_server_does_not_expose_helper_mutation_methods(self):
        from toolwright.mcp.meta_server import ToolwrightMetaMCPServer

        server = ToolwrightMetaMCPServer()
        assert not hasattr(server, "_capture_har")
        assert not hasattr(server, "_compile_capture")
        assert not hasattr(server, "_drift_check")
