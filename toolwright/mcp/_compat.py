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

    # HTTP transport classes (available in mcp>=1.8.0)
    try:
        from mcp.server.streamable_http import EventStore as _EventStoreBase
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        class InMemoryEventStore(_EventStoreBase):
            """Minimal in-memory event store for SSE resumability."""

            def __init__(self, max_events_per_stream: int = 100) -> None:
                from collections import deque
                self._max = max_events_per_stream
                self._streams: dict[str, deque] = {}
                self._index: dict[str, tuple[str, Any]] = {}

            async def store_event(self, stream_id: str, message: Any) -> str:
                from collections import deque
                from uuid import uuid4
                event_id = str(uuid4())
                if stream_id not in self._streams:
                    self._streams[stream_id] = deque(maxlen=self._max)
                q = self._streams[stream_id]
                if len(q) == self._max:
                    oldest = q[0]
                    self._index.pop(oldest[0], None)
                q.append((event_id, message))
                self._index[event_id] = (stream_id, message)
                return event_id

            async def replay_events_after(self, last_event_id: str, send_callback: Any) -> str | None:
                if last_event_id not in self._index:
                    return None
                stream_id = self._index[last_event_id][0]
                events = self._streams.get(stream_id, [])
                found = False
                for eid, msg in events:
                    if found and msg is not None:
                        await send_callback(msg)
                    elif eid == last_event_id:
                        found = True
                return stream_id

    except ImportError:
        StreamableHTTPSessionManager = None  # type: ignore[assignment,misc]
        InMemoryEventStore = None  # type: ignore[assignment,misc]
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

    StreamableHTTPSessionManager = None  # type: ignore[assignment]
    InMemoryEventStore = None  # type: ignore[assignment]

__all__ = [
    "InMemoryEventStore",
    "InitializationOptions",
    "NotificationOptions",
    "Server",
    "StreamableHTTPSessionManager",
    "mcp_stdio",
    "mcp_types",
]
