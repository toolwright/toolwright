"""Tests for OpenAPI discovery (probing hosts for OpenAPI specs)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx

from toolwright.core.discover.openapi import OpenAPIDiscovery
from toolwright.models.capture import CaptureSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_OPENAPI_SPEC = json.dumps(
    {
        "openapi": "3.0.3",
        "info": {"title": "Test API", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "summary": "List users",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer", "example": 1},
                                                "name": {"type": "string", "example": "Alice"},
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
)


def _make_response(status_code: int = 200, text: str = "", content_type: str = "application/json") -> httpx.Response:
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://api.example.com"),
    )


def _mock_client_factory(responses: dict[str, httpx.Response], *, default_status: int = 404):
    """Return a context-manager mock for httpx.AsyncClient.

    `responses` maps URL suffixes (path portion) to Response objects.
    Any path not in the map returns a response with `default_status`.
    """

    async def _mock_get(url: str, **kwargs):  # noqa: ARG001
        for suffix, resp in responses.items():
            if url.endswith(suffix):
                return resp
        return _make_response(status_code=default_status, text="Not found")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=_mock_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# TestDiscoverSuccess
# ---------------------------------------------------------------------------


class TestDiscoverSuccess:
    """Tests for successful spec discovery."""

    def test_returns_capture_session_when_spec_found(self):
        """Should return a CaptureSession when a valid spec is at /openapi.json."""
        mock_client = _mock_client_factory(
            {"/openapi.json": _make_response(200, VALID_OPENAPI_SPEC)}
        )
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("https://api.example.com"))

        assert result is not None
        assert isinstance(result, CaptureSession)

    def test_capture_session_has_exchanges(self):
        """CaptureSession.exchanges should be non-empty."""
        mock_client = _mock_client_factory(
            {"/openapi.json": _make_response(200, VALID_OPENAPI_SPEC)}
        )
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("https://api.example.com"))

        assert result is not None
        assert len(result.exchanges) > 0

    def test_capture_session_has_host(self):
        """CaptureSession.allowed_hosts should contain the probed host."""
        mock_client = _mock_client_factory(
            {"/openapi.json": _make_response(200, VALID_OPENAPI_SPEC)}
        )
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("https://api.example.com"))

        assert result is not None
        assert "api.example.com" in result.allowed_hosts

    def test_tries_multiple_paths(self):
        """Should keep trying paths after 404s and succeed on a later one."""
        mock_client = _mock_client_factory(
            {"/swagger.json": _make_response(200, VALID_OPENAPI_SPEC)}
        )
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("https://api.example.com"))

        assert result is not None
        assert isinstance(result, CaptureSession)
        assert len(result.exchanges) > 0


# ---------------------------------------------------------------------------
# TestDiscoverFailure
# ---------------------------------------------------------------------------


class TestDiscoverFailure:
    """Tests for failed discovery attempts."""

    def test_returns_none_when_all_paths_404(self):
        """Should return None when every well-known path returns 404."""
        mock_client = _mock_client_factory({})  # no success mappings
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("https://api.example.com"))

        assert result is None

    def test_returns_none_when_timeout(self):
        """Should return None when all paths time out."""

        async def _timeout_get(url: str, **kwargs):  # noqa: ARG001
            raise httpx.ReadTimeout("timeout")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_timeout_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("https://api.example.com"))

        assert result is None

    def test_returns_none_when_invalid_spec(self):
        """Should return None when the response is 200 but not valid JSON."""
        mock_client = _mock_client_factory(
            {"/openapi.json": _make_response(200, "this is not json!!!")}
        )
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("https://api.example.com"))

        assert result is None


# ---------------------------------------------------------------------------
# TestDiscoverURLHandling
# ---------------------------------------------------------------------------


class TestDiscoverURLHandling:
    """Tests for host URL normalisation."""

    def test_strips_trailing_slash_from_host(self):
        """Trailing slash should be stripped so paths join correctly."""
        mock_client = _mock_client_factory(
            {"/openapi.json": _make_response(200, VALID_OPENAPI_SPEC)}
        )
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("https://api.example.com/"))

        assert result is not None
        # Verify the GET calls don't have double slashes
        for call in mock_client.get.call_args_list:
            url = call.args[0] if call.args else call.kwargs.get("url", "")
            assert "//" not in url.split("://", 1)[-1]

    def test_adds_https_if_missing(self):
        """Bare hostnames should get https:// prepended."""
        mock_client = _mock_client_factory(
            {"/openapi.json": _make_response(200, VALID_OPENAPI_SPEC)}
        )
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("api.example.com"))

        assert result is not None
        # All requests should have used https://
        for call in mock_client.get.call_args_list:
            url = call.args[0] if call.args else call.kwargs.get("url", "")
            assert url.startswith("https://")

    def test_preserves_existing_scheme(self):
        """An explicit http:// scheme should not be overwritten."""
        mock_client = _mock_client_factory(
            {"/openapi.json": _make_response(200, VALID_OPENAPI_SPEC)}
        )
        with patch("toolwright.core.discover.openapi.httpx.AsyncClient", return_value=mock_client):
            disco = OpenAPIDiscovery()
            result = asyncio.run(disco.discover("http://localhost:8080"))

        assert result is not None
        for call in mock_client.get.call_args_list:
            url = call.args[0] if call.args else call.kwargs.get("url", "")
            assert url.startswith("http://localhost:8080")
