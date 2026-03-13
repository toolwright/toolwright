"""Upstream MCP server connection management.

WrappedConnection provides a unified interface to connect to, query, and
call tools on an upstream MCP server (stdio or Streamable HTTP).

Uses AsyncExitStack to hold MCP client context managers open for the
server's full lifetime while guaranteeing cleanup on close.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from toolwright.models.overlay import TargetType, WrapConfig

logger = logging.getLogger(__name__)


async def _connect_stdio(config: WrapConfig, stack: AsyncExitStack) -> Any:
    """Connect to a stdio-based MCP server. Returns a ClientSession."""
    from mcp import StdioServerParameters
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=config.command or "",
        args=config.args,
        env={**config.env} if config.env else None,
    )
    read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
    await session.initialize()
    return session


async def _connect_http(config: WrapConfig, stack: AsyncExitStack) -> Any:
    """Connect to a Streamable HTTP MCP server. Returns a ClientSession."""
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = config.url or ""
    headers = dict(config.headers) if config.headers else {}
    read_stream, write_stream, _ = await stack.enter_async_context(
        streamablehttp_client(url, headers=headers)
    )
    session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
    await session.initialize()
    return session


class WrappedConnection:
    """Unified interface to an upstream MCP server."""

    def __init__(self, config: WrapConfig) -> None:
        self.config = config
        self._session: Any | None = None
        self._stack: AsyncExitStack | None = None
        self._call_semaphore = asyncio.Semaphore(10)

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> None:
        """Connect to the upstream MCP server."""
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        if self.config.target_type == TargetType.STDIO:
            self._session = await _connect_stdio(self.config, self._stack)
        elif self.config.target_type == TargetType.STREAMABLE_HTTP:
            self._session = await _connect_http(self.config, self._stack)
        else:
            raise ValueError(f"Unsupported target type: {self.config.target_type}")

        logger.info("Connected to upstream server: %s", self.config.server_name)

    async def list_tools(self) -> list[Any]:
        """Enumerate tools from the upstream server."""
        if self._session is None:
            raise RuntimeError("Connection not connected")
        result = await self._session.list_tools()
        return list(result.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the upstream server, bounded by semaphore."""
        if self._session is None:
            raise RuntimeError("Connection not connected")
        async with self._call_semaphore:
            return await self._session.call_tool(name, arguments)

    async def reconnect(self) -> None:
        """Close current connection and reconnect."""
        await self.close()
        await self.connect()

    async def close(self) -> None:
        """Close the connection and clean up resources."""
        self._session = None
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        logger.info("Disconnected from upstream server: %s", self.config.server_name)
