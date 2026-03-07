"""Tests for probe_executor — async shape probe executor.

Covers: successful probe, non-200 error, timeout, non-JSON error,
response size limit, auth injection, extra headers, base URL,
query params, and non-GET rejection.

Uses unittest.mock to patch httpx.AsyncClient — no external test deps needed.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from toolwright.models.probe_template import ProbeTemplate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _template(
    method: str = "GET",
    path: str = "/products",
    query_params: dict | None = None,
    headers: dict | None = None,
) -> ProbeTemplate:
    return ProbeTemplate(
        method=method,
        path=path,
        query_params=query_params or {},
        headers=headers or {},
    )


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    headers: dict | None = None,
) -> httpx.Response:
    """Build a real httpx.Response with controlled content."""
    resp_headers = headers or {}
    if json_data is not None:
        content = json.dumps(json_data).encode()
        resp_headers.setdefault("content-type", "application/json")
    else:
        content = text.encode()
        resp_headers.setdefault("content-type", "text/html")

    return httpx.Response(
        status_code=status_code,
        headers=resp_headers,
        content=content,
        request=httpx.Request("GET", "https://example.com"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProbeExecutorSuccess:
    @pytest.mark.asyncio
    async def test_successful_probe_returns_json_body(self):
        """Probe a healthy endpoint -> ProbeResult with parsed JSON."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=_mock_response(
            status_code=200,
            json_data={"products": [{"id": 1}]},
        ))

        result = await execute_probe(
            template=_template(),
            host="api.example.com",
            client=mock_client,
        )

        assert result.ok is True
        assert result.status_code == 200
        assert result.body == {"products": [{"id": 1}]}
        assert result.error is None


class TestProbeExecutorNon200:
    @pytest.mark.asyncio
    async def test_non_200_returns_error(self):
        """Non-200 status -> ProbeResult with ok=False and error message."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=_mock_response(
            status_code=500,
            text="Internal Server Error",
        ))

        result = await execute_probe(
            template=_template(),
            host="api.example.com",
            client=mock_client,
        )

        assert result.ok is False
        assert result.status_code == 500
        assert result.body is None
        assert "500" in (result.error or "")


class TestProbeExecutorTimeout:
    @pytest.mark.asyncio
    async def test_timeout_produces_graceful_error(self):
        """Timeout -> ProbeResult with ok=False and timeout error."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.ReadTimeout("read timed out"))

        result = await execute_probe(
            template=_template(),
            host="api.example.com",
            client=mock_client,
            timeout=1.0,
        )

        assert result.ok is False
        assert result.status_code is None
        assert "timeout" in (result.error or "").lower()


class TestProbeExecutorNonJSON:
    @pytest.mark.asyncio
    async def test_non_json_content_type_returns_error(self):
        """Non-JSON content-type -> ProbeResult with ok=False."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=_mock_response(
            status_code=200,
            text="<html>Not JSON</html>",
            headers={"content-type": "text/html"},
        ))

        result = await execute_probe(
            template=_template(),
            host="api.example.com",
            client=mock_client,
        )

        assert result.ok is False
        assert result.body is None
        assert "json" in (result.error or "").lower()


class TestProbeExecutorSizeLimit:
    @pytest.mark.asyncio
    async def test_oversized_response_returns_error(self):
        """Response exceeding max_response_bytes -> error."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=_mock_response(
            status_code=200,
            json_data={"data": "x" * 1000},
            headers={"content-type": "application/json", "content-length": "999999999"},
        ))

        result = await execute_probe(
            template=_template(),
            host="api.example.com",
            client=mock_client,
            max_response_bytes=1024,
        )

        assert result.ok is False
        assert "size" in (result.error or "").lower() or "limit" in (result.error or "").lower()


class TestProbeExecutorAuth:
    @pytest.mark.asyncio
    async def test_auth_header_injected(self):
        """Auth header is added to outgoing request."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=_mock_response(
            status_code=200,
            json_data={"ok": True},
        ))

        await execute_probe(
            template=_template(),
            host="api.example.com",
            client=mock_client,
            auth_header="Bearer sk-test-123",
        )

        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer sk-test-123"


class TestProbeExecutorExtraHeaders:
    @pytest.mark.asyncio
    async def test_extra_headers_merged(self):
        """Extra headers from template and caller are merged."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=_mock_response(
            status_code=200,
            json_data={"ok": True},
        ))

        await execute_probe(
            template=_template(headers={"Accept": "application/json"}),
            host="api.example.com",
            client=mock_client,
            extra_headers={"X-Custom": "value"},
        )

        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Accept") == "application/json"
        assert headers.get("X-Custom") == "value"


class TestProbeExecutorBaseURL:
    @pytest.mark.asyncio
    async def test_base_url_used(self):
        """When base_url is provided, it overrides the host."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=_mock_response(
            status_code=200,
            json_data={"ok": True},
        ))

        result = await execute_probe(
            template=_template(),
            host="api.example.com",
            client=mock_client,
            base_url="http://localhost:8080",
        )

        assert result.ok is True
        call_args = mock_client.request.call_args
        url = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("url", "")
        assert "localhost:8080" in str(url)


class TestProbeExecutorQueryParams:
    @pytest.mark.asyncio
    async def test_query_params_appended(self):
        """Query params from template are appended to URL."""
        from toolwright.core.drift.probe_executor import execute_probe

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=_mock_response(
            status_code=200,
            json_data={"ok": True},
        ))

        await execute_probe(
            template=_template(query_params={"limit": "50", "fields": "id,title"}),
            host="api.example.com",
            client=mock_client,
        )

        call_args = mock_client.request.call_args
        url = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("url", "")
        url_str = str(url)
        assert "limit=50" in url_str
        assert "fields=" in url_str


class TestProbeExecutorNonGET:
    @pytest.mark.asyncio
    async def test_non_get_rejected(self):
        """Non-GET method in template -> immediate error, no HTTP call."""
        from toolwright.core.drift.probe_executor import execute_probe

        result = await execute_probe(
            template=_template(method="POST"),
            host="api.example.com",
        )

        assert result.ok is False
        assert "GET" in (result.error or "")
