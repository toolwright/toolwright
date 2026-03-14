"""Tests for endpoint re-discovery — fetch current API state for drift comparison."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolwright.models.endpoint import Endpoint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_openapi_spec(
    *,
    host: str = "api.example.com",
    paths: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal OpenAPI 3.0 spec."""
    default_paths = {
        "/users": {
            "get": {
                "operationId": "get_users",
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/users/{id}": {
            "get": {
                "operationId": "get_user",
                "responses": {"200": {"description": "OK"}},
            }
        },
    }
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0"},
        "servers": [{"url": f"https://{host}"}],
        "paths": paths or default_paths,
    }


# ---------------------------------------------------------------------------
# Tests: rediscover_endpoints
# ---------------------------------------------------------------------------


class TestRediscoverEndpoints:
    """Tests for async endpoint re-discovery."""

    @pytest.mark.asyncio
    async def test_returns_endpoints_from_openapi_spec(self):
        """When host has an OpenAPI spec, return parsed endpoints."""
        from toolwright.core.reconcile.rediscovery import rediscover_endpoints

        spec = _make_openapi_spec()
        spec_json = json.dumps(spec)

        # Mock httpx to return the spec
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = spec_json
        mock_response.json.return_value = spec

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = rediscover_endpoints(
                host="api.example.com",
                timeout=5.0,
            )
            endpoints = await result

        assert endpoints is not None
        assert len(endpoints) > 0
        assert all(isinstance(ep, Endpoint) for ep in endpoints)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_spec_found(self):
        """When host has no OpenAPI spec, return None."""
        from toolwright.core.reconcile.rediscovery import rediscover_endpoints

        # Mock httpx to return 404 for all probed paths
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await rediscover_endpoints(
                host="api.example.com",
                timeout=5.0,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        """Network errors should return None, not raise."""
        from toolwright.core.reconcile.rediscovery import rediscover_endpoints

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await rediscover_endpoints(
                host="api.example.com",
                timeout=5.0,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_respects_timeout(self):
        """Rediscovery should have its own timeout."""
        from toolwright.core.reconcile.rediscovery import rediscover_endpoints

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            result = await rediscover_endpoints(
                host="api.example.com",
                timeout=15.0,
            )
            # Verify timeout was passed to httpx client
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs.get("timeout") == 15.0

        assert result is None

    @pytest.mark.asyncio
    async def test_probes_well_known_paths(self):
        """Should probe standard OpenAPI spec locations."""
        from toolwright.core.reconcile.rediscovery import (
            WELL_KNOWN_SPEC_PATHS,
            rediscover_endpoints,
        )

        # Verify constant exists and has expected paths
        assert "/openapi.json" in WELL_KNOWN_SPEC_PATHS
        assert "/openapi.yaml" in WELL_KNOWN_SPEC_PATHS

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await rediscover_endpoints(
                host="api.example.com",
                timeout=5.0,
            )

        # Should have tried multiple well-known paths
        assert mock_client.get.call_count >= 2

    @pytest.mark.asyncio
    async def test_stops_probing_after_first_success(self):
        """Once a spec is found, stop probing other paths."""
        from toolwright.core.reconcile.rediscovery import rediscover_endpoints

        spec = _make_openapi_spec()
        spec_json = json.dumps(spec)

        # First call returns spec, subsequent calls would return 404
        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 200
        mock_response_ok.text = spec_json
        mock_response_ok.json.return_value = spec

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response_ok)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await rediscover_endpoints(
                host="api.example.com",
                timeout=5.0,
            )

        assert result is not None
        # Should stop after finding the first spec
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_default_timeout(self):
        """Default timeout should be used when not specified."""
        from toolwright.core.reconcile.rediscovery import (
            DEFAULT_REDISCOVERY_TIMEOUT,
            rediscover_endpoints,
        )

        assert DEFAULT_REDISCOVERY_TIMEOUT > 0

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            await rediscover_endpoints(host="api.example.com")
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs.get("timeout") == DEFAULT_REDISCOVERY_TIMEOUT

    @pytest.mark.asyncio
    async def test_handles_malformed_spec(self):
        """Malformed JSON/YAML in response should return None, not crash."""
        from toolwright.core.reconcile.rediscovery import rediscover_endpoints

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "this is not valid json or yaml {{{{"
        mock_response.json.side_effect = ValueError("Invalid JSON")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await rediscover_endpoints(
                host="api.example.com",
                timeout=5.0,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_builds_correct_urls_from_host(self):
        """URLs should be built using https and the provided host."""
        from toolwright.core.reconcile.rediscovery import rediscover_endpoints

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await rediscover_endpoints(
                host="myapi.io",
                timeout=5.0,
            )

        # All URLs should start with https://myapi.io
        for call in mock_client.get.call_args_list:
            url = call.args[0] if call.args else call.kwargs.get("url", "")
            assert url.startswith("https://myapi.io/"), f"Unexpected URL: {url}"

    @pytest.mark.asyncio
    async def test_parses_yaml_spec(self):
        """Should handle YAML-format OpenAPI specs."""
        import yaml

        from toolwright.core.reconcile.rediscovery import rediscover_endpoints

        spec = _make_openapi_spec()
        spec_yaml = yaml.dump(spec)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = spec_yaml
        mock_response.json.side_effect = ValueError("Not JSON")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await rediscover_endpoints(
                host="api.example.com",
                timeout=5.0,
            )

        assert result is not None
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: parse_spec_to_endpoints
# ---------------------------------------------------------------------------


class TestParseSpecToEndpoints:
    """Tests for the spec-to-endpoints parser used by rediscovery."""

    def test_extracts_endpoints_from_spec(self):
        from toolwright.core.reconcile.rediscovery import parse_spec_to_endpoints

        spec = _make_openapi_spec()
        endpoints = parse_spec_to_endpoints(spec, host="api.example.com")

        assert len(endpoints) == 2
        paths = {ep.path for ep in endpoints}
        assert "/users" in paths
        assert "/users/{id}" in paths

    def test_extracts_methods(self):
        from toolwright.core.reconcile.rediscovery import parse_spec_to_endpoints

        spec = _make_openapi_spec(
            paths={
                "/items": {
                    "get": {"responses": {"200": {"description": "OK"}}},
                    "post": {"responses": {"201": {"description": "Created"}}},
                }
            }
        )
        endpoints = parse_spec_to_endpoints(spec, host="api.example.com")

        methods = {ep.method for ep in endpoints}
        assert "GET" in methods
        assert "POST" in methods

    def test_uses_provided_host(self):
        from toolwright.core.reconcile.rediscovery import parse_spec_to_endpoints

        spec = _make_openapi_spec()
        endpoints = parse_spec_to_endpoints(spec, host="custom.api.io")

        assert all(ep.host == "custom.api.io" for ep in endpoints)

    def test_empty_spec_returns_empty(self):
        from toolwright.core.reconcile.rediscovery import parse_spec_to_endpoints

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Empty", "version": "1.0"},
            "paths": {},
        }
        endpoints = parse_spec_to_endpoints(spec, host="api.example.com")
        assert endpoints == []

    def test_returns_endpoint_models(self):
        from toolwright.core.reconcile.rediscovery import parse_spec_to_endpoints

        spec = _make_openapi_spec()
        endpoints = parse_spec_to_endpoints(spec, host="api.example.com")

        assert all(isinstance(ep, Endpoint) for ep in endpoints)
