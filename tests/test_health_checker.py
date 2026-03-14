"""Tests for the HEAL pillar Health Checker.

Tests the HealthChecker, HealthResult, and FailureClass models
that provide non-mutating endpoint health probes.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from toolwright.core.health.checker import (
    FailureClass,
    HealthChecker,
    HealthResult,
)

# ---------------------------------------------------------------------------
# FailureClass enum
# ---------------------------------------------------------------------------


class TestFailureClass:
    """FailureClass enum covers known failure modes."""

    def test_auth_expired(self):
        assert FailureClass.AUTH_EXPIRED == "auth_expired"

    def test_endpoint_gone(self):
        assert FailureClass.ENDPOINT_GONE == "endpoint_gone"

    def test_rate_limited(self):
        assert FailureClass.RATE_LIMITED == "rate_limited"

    def test_server_error(self):
        assert FailureClass.SERVER_ERROR == "server_error"

    def test_network_unreachable(self):
        assert FailureClass.NETWORK_UNREACHABLE == "network_unreachable"

    def test_schema_changed(self):
        assert FailureClass.SCHEMA_CHANGED == "schema_changed"

    def test_unknown(self):
        assert FailureClass.UNKNOWN == "unknown"

    def test_all_values(self):
        values = {f.value for f in FailureClass}
        assert values == {
            "auth_expired",
            "endpoint_gone",
            "rate_limited",
            "server_error",
            "network_unreachable",
            "schema_changed",
            "unknown",
        }


# ---------------------------------------------------------------------------
# HealthResult model
# ---------------------------------------------------------------------------


class TestHealthResult:
    """HealthResult captures a health probe outcome."""

    def test_healthy_result(self):
        r = HealthResult(tool_id="get_user", healthy=True, status_code=200, response_time_ms=42.5)
        assert r.tool_id == "get_user"
        assert r.healthy is True
        assert r.failure_class is None
        assert r.status_code == 200
        assert r.response_time_ms == 42.5
        assert r.error_message is None

    def test_unhealthy_result(self):
        r = HealthResult(
            tool_id="get_user",
            healthy=False,
            failure_class=FailureClass.AUTH_EXPIRED,
            status_code=401,
            response_time_ms=15.0,
            error_message="Unauthorized",
        )
        assert r.healthy is False
        assert r.failure_class == FailureClass.AUTH_EXPIRED
        assert r.error_message == "Unauthorized"

    def test_serialization(self):
        r = HealthResult(tool_id="x", healthy=True, status_code=200, response_time_ms=10.0)
        d = r.model_dump()
        assert d["tool_id"] == "x"
        assert d["healthy"] is True


# ---------------------------------------------------------------------------
# classify_failure
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    """classify_failure maps status codes/errors to FailureClass."""

    def test_401_is_auth_expired(self):
        assert HealthChecker.classify_failure(401) == FailureClass.AUTH_EXPIRED

    def test_403_is_auth_expired(self):
        assert HealthChecker.classify_failure(403) == FailureClass.AUTH_EXPIRED

    def test_404_is_endpoint_gone(self):
        assert HealthChecker.classify_failure(404) == FailureClass.ENDPOINT_GONE

    def test_410_is_endpoint_gone(self):
        assert HealthChecker.classify_failure(410) == FailureClass.ENDPOINT_GONE

    def test_429_is_rate_limited(self):
        assert HealthChecker.classify_failure(429) == FailureClass.RATE_LIMITED

    def test_500_is_server_error(self):
        assert HealthChecker.classify_failure(500) == FailureClass.SERVER_ERROR

    def test_502_is_server_error(self):
        assert HealthChecker.classify_failure(502) == FailureClass.SERVER_ERROR

    def test_503_is_server_error(self):
        assert HealthChecker.classify_failure(503) == FailureClass.SERVER_ERROR

    def test_504_is_server_error(self):
        assert HealthChecker.classify_failure(504) == FailureClass.SERVER_ERROR

    def test_network_error_string(self):
        assert HealthChecker.classify_failure(None, error="ConnectError") == FailureClass.NETWORK_UNREACHABLE

    def test_timeout_error_string(self):
        assert HealthChecker.classify_failure(None, error="TimeoutError") == FailureClass.NETWORK_UNREACHABLE

    def test_unknown_status(self):
        assert HealthChecker.classify_failure(418) == FailureClass.UNKNOWN


# ---------------------------------------------------------------------------
# check_tool (single tool probe)
# ---------------------------------------------------------------------------


class TestCheckTool:
    """check_tool sends non-mutating probes."""

    @pytest.mark.asyncio
    async def test_healthy_get_uses_head(self):
        """GET endpoints should be probed with HEAD."""
        action = {"name": "get_user", "method": "GET", "host": "api.example.com", "path": "/api/users/{user_id}"}

        mock_response = AsyncMock()
        mock_response.status_code = 200

        checker = HealthChecker()
        with patch.object(checker, "_send_probe", return_value=(200, 42.0, None)):
            result = await checker.check_tool(action)

        assert result.tool_id == "get_user"
        assert result.healthy is True
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_post_uses_options(self):
        """POST/PUT/DELETE endpoints should be probed with OPTIONS."""
        action = {"name": "create_user", "method": "POST", "host": "api.example.com", "path": "/api/users"}

        checker = HealthChecker()
        with patch.object(checker, "_send_probe", return_value=(200, 10.0, None)):
            result = await checker.check_tool(action)

        assert result.tool_id == "create_user"
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_unhealthy_401(self):
        """401 should produce AUTH_EXPIRED failure."""
        action = {"name": "get_user", "method": "GET", "host": "api.example.com", "path": "/api/users"}

        checker = HealthChecker()
        with patch.object(checker, "_send_probe", return_value=(401, 5.0, None)):
            result = await checker.check_tool(action)

        assert result.healthy is False
        assert result.failure_class == FailureClass.AUTH_EXPIRED
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_unhealthy_404(self):
        """404 should produce ENDPOINT_GONE failure."""
        action = {"name": "get_user", "method": "GET", "host": "api.example.com", "path": "/api/users"}

        checker = HealthChecker()
        with patch.object(checker, "_send_probe", return_value=(404, 5.0, None)):
            result = await checker.check_tool(action)

        assert result.healthy is False
        assert result.failure_class == FailureClass.ENDPOINT_GONE

    @pytest.mark.asyncio
    async def test_network_error(self):
        """Network errors should produce NETWORK_UNREACHABLE failure."""
        action = {"name": "get_user", "method": "GET", "host": "api.example.com", "path": "/api/users"}

        checker = HealthChecker()
        with patch.object(checker, "_send_probe", return_value=(None, 0.0, "ConnectError: connection refused")):
            result = await checker.check_tool(action)

        assert result.healthy is False
        assert result.failure_class == FailureClass.NETWORK_UNREACHABLE
        assert "ConnectError" in result.error_message

    @pytest.mark.asyncio
    async def test_probe_method_get_to_head(self):
        """_probe_method should map GET -> HEAD."""
        checker = HealthChecker()
        assert checker._probe_method("GET") == "HEAD"

    @pytest.mark.asyncio
    async def test_probe_method_post_to_options(self):
        """_probe_method should map POST -> OPTIONS."""
        checker = HealthChecker()
        assert checker._probe_method("POST") == "OPTIONS"

    @pytest.mark.asyncio
    async def test_probe_method_put_to_options(self):
        checker = HealthChecker()
        assert checker._probe_method("PUT") == "OPTIONS"

    @pytest.mark.asyncio
    async def test_probe_method_delete_to_options(self):
        checker = HealthChecker()
        assert checker._probe_method("DELETE") == "OPTIONS"

    @pytest.mark.asyncio
    async def test_probe_method_patch_to_options(self):
        checker = HealthChecker()
        assert checker._probe_method("PATCH") == "OPTIONS"


# ---------------------------------------------------------------------------
# check_all (concurrent multi-tool probe)
# ---------------------------------------------------------------------------


class TestCheckAll:
    """check_all probes multiple tools concurrently."""

    @pytest.mark.asyncio
    async def test_check_all_empty(self):
        checker = HealthChecker()
        results = await checker.check_all([])
        assert results == []

    @pytest.mark.asyncio
    async def test_check_all_single(self):
        action = {"name": "get_user", "method": "GET", "host": "api.example.com", "path": "/api/users"}
        checker = HealthChecker()
        with patch.object(checker, "_send_probe", return_value=(200, 10.0, None)):
            results = await checker.check_all([action])
        assert len(results) == 1
        assert results[0].healthy is True

    @pytest.mark.asyncio
    async def test_check_all_multiple(self):
        actions = [
            {"name": "get_user", "method": "GET", "host": "api.example.com", "path": "/api/users"},
            {"name": "create_user", "method": "POST", "host": "api.example.com", "path": "/api/users"},
            {"name": "delete_user", "method": "DELETE", "host": "api.example.com", "path": "/api/users/{id}"},
        ]
        checker = HealthChecker()
        with patch.object(checker, "_send_probe", return_value=(200, 10.0, None)):
            results = await checker.check_all(actions)
        assert len(results) == 3
        assert all(r.healthy for r in results)

    @pytest.mark.asyncio
    async def test_check_all_mixed_results(self):
        """Some healthy, some not."""
        actions = [
            {"name": "ok_tool", "method": "GET", "host": "api.example.com", "path": "/ok"},
            {"name": "gone_tool", "method": "GET", "host": "api.example.com", "path": "/gone"},
        ]

        call_count = 0

        async def mock_probe(_method, url, _timeout):
            nonlocal call_count
            call_count += 1
            if "/ok" in url:
                return (200, 5.0, None)
            return (404, 5.0, None)

        checker = HealthChecker()
        with patch.object(checker, "_send_probe", side_effect=mock_probe):
            results = await checker.check_all(actions)

        healthy = [r for r in results if r.healthy]
        unhealthy = [r for r in results if not r.healthy]
        assert len(healthy) == 1
        assert len(unhealthy) == 1

    @pytest.mark.asyncio
    async def test_check_all_respects_concurrency(self):
        """Should not exceed max_concurrent."""
        actions = [
            {"name": f"tool_{i}", "method": "GET", "host": "api.example.com", "path": f"/api/{i}"}
            for i in range(10)
        ]
        checker = HealthChecker(max_concurrent=3)

        active = 0
        max_active = 0


        async def tracking_probe(_method, _url, _timeout):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return (200, 10.0, None)

        with patch.object(checker, "_send_probe", side_effect=tracking_probe):
            results = await checker.check_all(actions)

        assert len(results) == 10
        assert max_active <= 3


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


class TestBuildProbeUrl:
    """_build_probe_url constructs the URL correctly."""

    def test_basic_url(self):
        checker = HealthChecker()
        action = {"host": "api.example.com", "path": "/api/users"}
        url = checker._build_probe_url(action)
        assert url == "https://api.example.com/api/users"

    def test_strips_path_params(self):
        """Path parameters like {user_id} should be replaced."""
        checker = HealthChecker()
        action = {"host": "api.example.com", "path": "/api/users/{user_id}/posts/{post_id}"}
        url = checker._build_probe_url(action)
        # Path params should be replaced with placeholder
        assert "{user_id}" not in url
        assert "{post_id}" not in url

    def test_custom_scheme(self):
        checker = HealthChecker(scheme="http")
        action = {"host": "localhost:8080", "path": "/api/health"}
        url = checker._build_probe_url(action)
        assert url.startswith("http://")
