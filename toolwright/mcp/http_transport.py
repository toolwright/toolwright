"""HTTP transport for the Toolwright MCP server.

Uses StreamableHTTPSessionManager from the MCP SDK to serve MCP over HTTP.
Also provides a health endpoint and extensible routes for the dashboard API.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from toolwright.mcp._compat import (
    InMemoryEventStore,
    StreamableHTTPSessionManager,
)

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8745  # T=8, W=7, 45


class ToolwrightHTTPApp:
    """Starlette ASGI application wrapping the MCP StreamableHTTP transport.

    Provides:
      - /mcp — StreamableHTTP MCP endpoint
      - /health — Unauthenticated health check
    """

    def __init__(
        self,
        mcp_server: Any,
        *,
        port: int = DEFAULT_PORT,
        host: str = "127.0.0.1",
    ) -> None:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route
        from starlette.types import Receive, Scope, Send

        self._mcp_server = mcp_server
        self._start_time = time.monotonic()
        self._port = port
        self._host = host

        event_store = InMemoryEventStore()

        self._session_manager = StreamableHTTPSessionManager(
            app=mcp_server.server,
            event_store=event_store,
        )

        async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
            await self._session_manager.handle_request(scope, receive, send)

        async def handle_health(request: Request) -> JSONResponse:  # noqa: ARG001
            uptime = time.monotonic() - self._start_time
            return JSONResponse({
                "status": "healthy",
                "tools": len(mcp_server.actions),
                "uptime": round(uptime, 1),
            })

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:  # noqa: ARG001
            async with self._session_manager.run():
                logger.info("Toolwright HTTP server started")
                try:
                    yield
                finally:
                    logger.info("Toolwright HTTP server shutting down")

        self.starlette_app = Starlette(
            debug=False,
            routes=[
                Route("/health", handle_health),
                Mount("/mcp", app=handle_mcp),
            ],
            lifespan=lifespan,
        )

    def run(self) -> None:
        """Start the HTTP server with uvicorn."""
        import uvicorn

        uvicorn.run(
            self.starlette_app,
            host=self._host,
            port=self._port,
            log_level="info",
        )
