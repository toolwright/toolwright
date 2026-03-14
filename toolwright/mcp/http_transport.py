"""HTTP transport for the Toolwright MCP server.

Uses StreamableHTTPSessionManager from the MCP SDK to serve MCP over HTTP.
Also provides a health endpoint, dashboard/console JSON API, SSE live feed,
and control plane action endpoints.
"""

from __future__ import annotations

import asyncio
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
      - /api/events/stream — SSE live feed (legacy)
      - /api/stream — Console SSE stream (resumable, with work items)
      - /api/act/* — Control plane action endpoints
      - /api/work-items — Work item listing
      - /api/status — Status bar counts
    """

    def __init__(
        self,
        mcp_server: Any,
        *,
        port: int = DEFAULT_PORT,
        host: str = "127.0.0.1",
        event_bus: Any | None = None,
        console_event_store: Any | None = None,
        confirmation_store: Any | None = None,
        lockfile_manager: Any | None = None,
        circuit_breaker: Any | None = None,
        rule_engine: Any | None = None,
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
        self._console_event_store = console_event_store
        self._confirmation_store = confirmation_store
        self._expiration_task: asyncio.Task[None] | None = None

        mcp_event_store = InMemoryEventStore()

        self._session_manager = StreamableHTTPSessionManager(
            app=mcp_server.server,
            event_store=mcp_event_store,
        )

        # Set up action handler context if console event store is available
        if console_event_store is not None:
            from toolwright.mcp.action_handlers import ActionContext, set_context

            ctx = ActionContext(
                event_store=console_event_store,
                lockfile_manager=lockfile_manager,
                confirmation_store=confirmation_store,
                circuit_breaker=circuit_breaker,
                rule_engine=rule_engine,
            )
            set_context(ctx)

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
                    "Referrer-Policy": "no-referrer",
                },
            )

        # -- Console SSE stream (resumable) --------------------------------

        async def handle_console_stream(request: Request) -> StreamingResponse:
            """Resumable SSE stream with Last-Event-ID support."""
            if console_event_store is None:
                return StreamingResponse(
                    _empty_generator(),
                    media_type="text/event-stream",
                )

            last_event_id = request.headers.get("Last-Event-ID", "")

            async def console_generator() -> AsyncIterator[str]:
                # 1. Replay missed events
                if last_event_id:
                    for event in console_event_store.events_since(last_event_id):
                        yield _format_sse_event(event, console_event_store)

                # 2. Send current open work items (replaces client's open set)
                open_items = console_event_store.open_work_items()
                if open_items:
                    yield _format_sse_sync(open_items)

                # 3. Send status bar counts
                yield _format_sse_status(console_event_store.work_item_counts())

                # 4. Stream live events
                queue = console_event_store.subscribe()
                try:
                    while True:
                        try:
                            event = await asyncio.wait_for(queue.get(), timeout=30)
                            yield _format_sse_event(event, console_event_store)
                        except TimeoutError:
                            yield ": keepalive\n\n"
                finally:
                    console_event_store.unsubscribe(queue)

            return StreamingResponse(
                console_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "Referrer-Policy": "no-referrer",
                },
            )

        @contextlib.asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            async with self._session_manager.run():
                logger.info("Toolwright HTTP server started")
                # Start expiration loop if we have a console event store
                if console_event_store is not None and confirmation_store is not None:
                    self._expiration_task = asyncio.create_task(
                        self._run_expiration_loop(console_event_store, confirmation_store)
                    )
                try:
                    yield
                finally:
                    if self._expiration_task is not None:
                        self._expiration_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await self._expiration_task
                    if console_event_store is not None:
                        console_event_store.close()
                    logger.info("Toolwright HTTP server shutting down")

        # Build routes
        routes: list[Route | Mount] = [
            Route("/health", handle_health),
            Route("/api/overview", handle_overview),
            Route("/api/tools", handle_tools),
            Route("/api/events", handle_events),
            Route("/api/events/stream", handle_events_stream),
            Route("/api/stream", handle_console_stream),
            Mount("/mcp", app=handle_mcp),
        ]

        # Add action routes if console is enabled
        if console_event_store is not None:
            from toolwright.mcp.action_handlers import (
                handle_confirm_deny,
                handle_confirm_grant,
                handle_enable_tool,
                handle_gate_allow,
                handle_gate_block,
                handle_get_work_item,
                handle_kill_tool,
                handle_list_work_items,
                handle_repair_apply,
                handle_repair_dismiss,
                handle_rule_activate,
                handle_rule_dismiss,
                handle_status_counts,
            )

            routes.extend([
                Route("/api/act/gate/allow", handle_gate_allow, methods=["POST"]),
                Route("/api/act/gate/block", handle_gate_block, methods=["POST"]),
                Route("/api/act/confirm/grant", handle_confirm_grant, methods=["POST"]),
                Route("/api/act/confirm/deny", handle_confirm_deny, methods=["POST"]),
                Route("/api/act/kill", handle_kill_tool, methods=["POST"]),
                Route("/api/act/enable", handle_enable_tool, methods=["POST"]),
                Route("/api/act/rules/activate", handle_rule_activate, methods=["POST"]),
                Route("/api/act/rules/dismiss", handle_rule_dismiss, methods=["POST"]),
                Route("/api/act/repair/apply", handle_repair_apply, methods=["POST"]),
                Route("/api/act/repair/dismiss", handle_repair_dismiss, methods=["POST"]),
                Route("/api/work-items", handle_list_work_items),
                Route("/api/work-items/{item_id:path}", handle_get_work_item),
                Route("/api/status", handle_status_counts),
            ])

        # Static files: console first, then dashboard as fallback
        console_dir = pathlib.Path(__file__).resolve().parent.parent / "assets" / "console"
        dashboard_dir = pathlib.Path(__file__).resolve().parent.parent / "assets" / "dashboard"

        static_dir = console_dir if console_dir.is_dir() else dashboard_dir
        if static_dir.is_dir():
            from starlette.staticfiles import StaticFiles

            routes.append(Mount("/", app=StaticFiles(directory=str(static_dir), html=True)))

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

    @staticmethod
    async def _run_expiration_loop(
        console_event_store: Any, confirmation_store: Any
    ) -> None:
        """Background task that checks for expired work items every 30s."""
        from toolwright.mcp.event_store import ConsoleEvent

        while True:
            await asyncio.sleep(30)
            try:
                expired = console_event_store.check_expirations(confirmation_store)
                for item in expired:
                    console_event_store.publish_event(
                        ConsoleEvent(
                            id="",
                            timestamp=time.time(),
                            event_type="confirmation_expired",
                            severity="warn",
                            summary=f"Confirmation expired for {item.subject_label}",
                            tool_id=item.evidence.get("tool_id", item.subject_id),
                            work_item_id=item.id,
                        )
                    )
            except Exception:
                logger.exception("Error in expiration loop")


# ---------------------------------------------------------------------------
# SSE formatting helpers
# ---------------------------------------------------------------------------


def _format_sse_event(event: Any, event_store: Any) -> str:
    """Format a ConsoleEvent as an SSE message event."""
    data: dict[str, Any] = {
        "type": "event",
        "event": {
            "id": event.id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "severity": event.severity,
            "summary": event.summary,
            "detail": event.detail,
            "tool_id": event.tool_id,
            "session_id": event.session_id,
            "work_item_id": event.work_item_id,
        },
    }
    if event.work_item_id:
        item = event_store.get_work_item(event.work_item_id)
        if item:
            data["work_item"] = item.to_dict()
    return f"id: {event.id}\nevent: message\ndata: {json.dumps(data)}\n\n"


def _format_sse_sync(items: list[Any]) -> str:
    """Format a work items sync as an SSE sync event."""
    data = {"type": "work_items_sync", "items": [i.to_dict() for i in items]}
    return f"event: sync\ndata: {json.dumps(data)}\n\n"


def _format_sse_status(counts: dict[str, Any]) -> str:
    """Format status bar counts as an SSE status event."""
    data = {"type": "status", "counts": counts}
    return f"event: status\ndata: {json.dumps(data)}\n\n"


async def _empty_generator() -> AsyncIterator[str]:
    """Empty async generator for when console is not enabled."""
    return
    yield  # noqa: RET504 — required to make this a generator
