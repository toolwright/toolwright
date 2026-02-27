"""Compatibility helpers for optional `mcp` dependency.

When the `mcp` package is unavailable (for example in offline test environments),
provide a minimal shim that supports Toolwright unit tests.
"""
# mypy: ignore-errors

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

try:  # pragma: no cover - exercised when optional dependency exists
    import mcp.server.stdio as mcp_stdio
    import mcp.types as mcp_types
    from mcp.server.lowlevel import NotificationOptions, Server
    from mcp.server.models import InitializationOptions
except ModuleNotFoundError:  # pragma: no cover - exercised in offline environments
    @dataclass
    class Tool:
        name: str
        description: str
        inputSchema: dict[str, Any]
        outputSchema: dict[str, Any] | None = None

    @dataclass
    class TextContent:
        type: str
        text: str

    @dataclass
    class ImageContent:
        type: str
        data: str | None = None

    @dataclass
    class EmbeddedResource:
        type: str
        data: dict[str, Any] | None = None

    class Server:
        def __init__(self, name: str) -> None:
            self.name = name
            self._list_tools_handler: Any = None
            self._call_tool_handler: Any = None

        def list_tools(self):
            def decorator(func):
                self._list_tools_handler = func
                return func

            return decorator

        def call_tool(self):
            def decorator(func):
                self._call_tool_handler = func
                return func

            return decorator

        def get_capabilities(self, notification_options: Any | None = None, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG002
            return {}

        async def run(self, read_stream: Any, write_stream: Any, init_options: Any) -> None:  # noqa: ARG002
            return None

    @dataclass
    class NotificationOptions:
        pass

    @dataclass
    class InitializationOptions:
        server_name: str
        server_version: str
        capabilities: dict[str, Any]

    @asynccontextmanager
    async def stdio_server():
        yield (SimpleNamespace(), SimpleNamespace())

    mcp_types = ModuleType("mcp.types")
    mcp_types.Tool = Tool
    mcp_types.TextContent = TextContent
    mcp_types.ImageContent = ImageContent
    mcp_types.EmbeddedResource = EmbeddedResource

    mcp_stdio = ModuleType("mcp.server.stdio")
    mcp_stdio.stdio_server = stdio_server

    mcp_server_lowlevel = ModuleType("mcp.server.lowlevel")
    mcp_server_lowlevel.Server = Server
    mcp_server_lowlevel.NotificationOptions = NotificationOptions

    mcp_server_models = ModuleType("mcp.server.models")
    mcp_server_models.InitializationOptions = InitializationOptions

    mcp_server_pkg = ModuleType("mcp.server")
    mcp_server_pkg.stdio = mcp_stdio
    mcp_server_pkg.lowlevel = mcp_server_lowlevel
    mcp_server_pkg.models = mcp_server_models

    mcp_pkg = ModuleType("mcp")
    mcp_pkg.server = mcp_server_pkg
    mcp_pkg.types = mcp_types

    sys.modules.setdefault("mcp", mcp_pkg)
    sys.modules.setdefault("mcp.types", mcp_types)
    sys.modules.setdefault("mcp.server", mcp_server_pkg)
    sys.modules.setdefault("mcp.server.stdio", mcp_stdio)
    sys.modules.setdefault("mcp.server.lowlevel", mcp_server_lowlevel)
    sys.modules.setdefault("mcp.server.models", mcp_server_models)

__all__ = [
    "mcp_stdio",
    "mcp_types",
    "NotificationOptions",
    "Server",
    "InitializationOptions",
]
