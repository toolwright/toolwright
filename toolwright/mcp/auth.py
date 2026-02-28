"""Token authentication for the Toolwright MCP HTTP transport.

Provides token generation, validation, masking, and ASGI middleware
for bearer token auth on protected routes.
"""

from __future__ import annotations

import os
import re
import secrets
from typing import Any
from urllib.parse import parse_qs

TOKEN_RE = re.compile(r"^tw_[a-f0-9]{32}$")
_EXEMPT_PATHS = frozenset({"/health"})


def generate_token() -> str:
    """Generate a new Toolwright auth token (tw_ + 32 hex chars)."""
    return f"tw_{secrets.token_hex(16)}"


def validate_token(provided: str | None, *, expected: str) -> bool:
    """Check if provided token matches expected.

    Accepts raw token or Bearer-prefixed.
    """
    if not provided:
        return False
    value = provided
    if value.startswith("Bearer "):
        value = value[7:]
    return secrets.compare_digest(value, expected)


def mask_token(token: str) -> str:
    """Mask a token for display, showing prefix and last 4 chars."""
    if len(token) <= 7:
        return "tw_***"
    return f"{token[:3]}***{token[-4:]}"


def resolve_token(explicit_token: str | None = None) -> str:
    """Resolve the auth token from explicit value, env var, or auto-generate."""
    if explicit_token:
        return explicit_token
    env_token = os.environ.get("TOOLWRIGHT_TOKEN")
    if env_token:
        return env_token
    return generate_token()


class TokenAuthMiddleware:
    """ASGI middleware that enforces bearer token auth.

    Exempt paths (e.g. /health) pass through without auth.
    Protected paths require Authorization: Bearer <token> header
    or ?t=<token> query parameter.
    """

    def __init__(self, app: Any, *, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Check Authorization header
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="replace")

        # Check query param ?t=<token>
        query_string = scope.get("query_string", b"").decode("utf-8", errors="replace")
        query_params = parse_qs(query_string)
        query_token = query_params.get("t", [None])[0]

        if validate_token(auth_header, expected=self.token) or validate_token(
            query_token, expected=self.token
        ):
            await self.app(scope, receive, send)
            return

        # Reject with 401
        await self._send_401(send)

    @staticmethod
    async def _send_401(send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"www-authenticate", b"Bearer"],
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error": "Unauthorized", "hint": "Provide Authorization: Bearer <token> header"}',
            }
        )
