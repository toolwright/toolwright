"""HTTP transport for the Toolwright MCP server.

Uses StreamableHTTPSessionManager from the MCP SDK to serve MCP over HTTP.
Also provides a health endpoint, dashboard JSON API, and SSE live feed.
"""

from __future__ import annotations

import contextlib
import json
import logging
import pathlib
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
      - /api/overview — Toolpack metadata
      - /api/tools — Tool list with risk, status
      - /api/events — Recent events (JSON)
      - /api/events/stream — SSE live feed
    """

    def __init__(
        self,
        mcp_server: Any,
        *,
        port: int = DEFAULT_PORT,
        host: str = "127.0.0.1",
        event_bus: Any | None = None,
    ) -> None:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse, StreamingResponse
        from starlette.routing import Mount, Route
        from starlette.types import Receive, Scope, Send

        self._mcp_server = mcp_server
        self._start_time = time.monotonic()
        self._port = port
        self._host = host
        self._event_bus = event_bus

        event_store = InMemoryEventStore()

        self._session_manager = StreamableHTTPSessionManager(
            app=mcp_server.server,
            event_store=event_store,
        )

        async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
            await self._session_manager.handle_request(scope, receive, send)

        async def handle_health(_request: Request) -> JSONResponse:
            uptime = time.monotonic() - self._start_time
            return JSONResponse({
                "status": "healthy",
                "tools": len(mcp_server.actions),
                "uptime": round(uptime, 1),
            })

        async def handle_overview(_request: Request) -> JSONResponse:
            manifest = getattr(mcp_server, "manifest", {})
            return JSONResponse({
                "name": manifest.get("name", "Toolwright"),
                "tools": len(mcp_server.actions),
                "uptime": round(time.monotonic() - self._start_time, 1),
            })

        async def handle_tools(_request: Request) -> JSONResponse:
            tools_list = []
            for name, action in mcp_server.actions.items():
                tools_list.append({
                    "name": name,
                    "description": action.get("description", ""),
                    "method": action.get("method", "GET"),
                    "path": action.get("path", "/"),
                    "host": action.get("host", ""),
                    "risk_tier": action.get("risk_tier", "low"),
                })
            return JSONResponse(tools_list)

        async def handle_events(request: Request) -> JSONResponse:  # noqa: ARG001
            if self._event_bus is None:
                return JSONResponse([])
            events = self._event_bus.recent(100)
            return JSONResponse([e.to_dict() for e in events])

        async def handle_events_stream(request: Request) -> StreamingResponse:  # noqa: ARG001
            async def event_generator() -> AsyncIterator[str]:
                if self._event_bus is None:
                    return
                async for event in self._event_bus.subscribe():
                    data = json.dumps(event.to_dict())
                    yield f"data: {data}\n\n"

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        @contextlib.asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            async with self._session_manager.run():
                logger.info("Toolwright HTTP server started")
                try:
                    yield
                finally:
                    logger.info("Toolwright HTTP server shutting down")

        # Static dashboard files
        dashboard_dir = pathlib.Path(__file__).resolve().parent.parent / "assets" / "dashboard"

        routes: list[Route | Mount] = [
            Route("/health", handle_health),
            Route("/api/overview", handle_overview),
            Route("/api/tools", handle_tools),
            Route("/api/events", handle_events),
            Route("/api/events/stream", handle_events_stream),
            Mount("/mcp", app=handle_mcp),
        ]

        if dashboard_dir.is_dir():
            from starlette.staticfiles import StaticFiles

            routes.append(Mount("/", app=StaticFiles(directory=str(dashboard_dir), html=True)))

        self.starlette_app = Starlette(
            debug=False,
            routes=routes,
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
