"""Tests for Smart Mint Probe (_smart_probe and sub-probes).

Replaces test_mint_auth_precheck.py. Covers:
- _probe_base_url: auth detection, WWW-Authenticate parsing
- _probe_graphql: introspection detection, gating
- _probe_openapi: well-known path detection
- _smart_probe: integration, rendering, timeout behavior
"""

from __future__ import annotations

import httpx
import pytest

from toolwright.cli.mint import (
    ProbeResult,
    _probe_base_url,
    _probe_graphql,
    _probe_hosts,
    _probe_openapi,
    _render_probe_results,
    _smart_probe,
)

# ── Batch 1: _probe_base_url ─────────────────────────────────────


def _mock_transport(status: int, headers: dict[str, str] | None = None):
    """Build an httpx.MockTransport returning a fixed response."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers or {})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_probe_base_url_401_detects_auth() -> None:
    transport = _mock_transport(401)
    result = await _probe_base_url("https://api.example.com", transport=transport)
    assert result["auth_required"] is True
    assert result["base_status"] == 401


@pytest.mark.asyncio
async def test_probe_base_url_403_detects_auth() -> None:
    transport = _mock_transport(403)
    result = await _probe_base_url("https://api.example.com", transport=transport)
    assert result["auth_required"] is True
    assert result["base_status"] == 403


@pytest.mark.asyncio
async def test_probe_base_url_200_no_auth() -> None:
    transport = _mock_transport(200)
    result = await _probe_base_url("https://api.example.com", transport=transport)
    assert result["auth_required"] is False
    assert result["base_status"] == 200


@pytest.mark.asyncio
async def test_probe_base_url_parses_www_authenticate() -> None:
    transport = _mock_transport(
        401, headers={"WWW-Authenticate": 'Bearer realm="api", scope="read"'}
    )
    result = await _probe_base_url("https://api.example.com", transport=transport)
    assert result["auth_scheme"] == "Bearer"
    assert result["www_authenticate_raw"] == 'Bearer realm="api", scope="read"'


@pytest.mark.asyncio
async def test_probe_base_url_network_error_silent() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")
    transport = httpx.MockTransport(handler)
    result = await _probe_base_url("https://api.example.com", transport=transport)
    assert result == {}


# ── Batch 2: _probe_graphql ──────────────────────────────────────


def _gql_mock_transport(
    status: int = 200,
    body: str = "",
    content_type: str = "application/json",
):
    """Build a MockTransport for GraphQL probe tests."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            content=body.encode(),
            headers={"content-type": content_type},
        )
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_probe_graphql_detected() -> None:
    body = '{"data":{"__schema":{"queryType":{"name":"Query"}}}}'
    transport = _gql_mock_transport(200, body)
    result = await _probe_graphql(
        "https://api.linear.app/graphql",
        ["api.linear.app"],
        transport=transport,
    )
    assert result["graphql_detected"] is True
    assert result["graphql_url"] is not None


@pytest.mark.asyncio
async def test_probe_graphql_not_detected_404() -> None:
    transport = _gql_mock_transport(404)
    result = await _probe_graphql(
        "https://api.linear.app/graphql",
        ["api.linear.app"],
        transport=transport,
    )
    assert result.get("graphql_detected", False) is False


@pytest.mark.asyncio
async def test_probe_graphql_not_detected_no_schema() -> None:
    body = '{"data":{"hello":"world"}}'
    transport = _gql_mock_transport(200, body)
    result = await _probe_graphql(
        "https://api.linear.app/graphql",
        ["api.linear.app"],
        transport=transport,
    )
    assert result.get("graphql_detected", False) is False


@pytest.mark.asyncio
async def test_probe_graphql_network_error_silent() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")
    transport = httpx.MockTransport(handler)
    result = await _probe_graphql(
        "https://api.linear.app/graphql",
        ["api.linear.app"],
        transport=transport,
    )
    assert result.get("graphql_detected", False) is False


@pytest.mark.asyncio
async def test_probe_graphql_probes_allowed_hosts_for_rest_url() -> None:
    """GraphQL probe should try /graphql on allowed hosts even for REST URLs."""
    probed_urls: list[str] = []
    def handler(_request: httpx.Request) -> httpx.Response:
        probed_urls.append(str(_request.url))
        body = '{"data":{"__schema":{"queryType":{"name":"Query"}}}}'
        return httpx.Response(200, content=body.encode())
    transport = httpx.MockTransport(handler)
    result = await _probe_graphql(
        "https://api.github.com",
        ["api.github.com"],
        transport=transport,
    )
    assert len(probed_urls) >= 1  # Should have probed at least 1 URL
    assert any("/graphql" in url for url in probed_urls)
    assert result["graphql_detected"] is True


@pytest.mark.asyncio
async def test_probe_graphql_detects_on_allowed_host() -> None:
    """GraphQL detected on allowed host when start_url is a dashboard."""
    def handler(_request: httpx.Request) -> httpx.Response:
        body = '{"data":{"__schema":{"queryType":{"name":"Query"}}}}'
        return httpx.Response(200, content=body.encode())
    transport = httpx.MockTransport(handler)
    result = await _probe_graphql(
        "https://dashboard.linear.app",
        ["api.linear.app"],
        transport=transport,
    )
    assert result["graphql_detected"] is True
    assert result["graphql_url"] == "https://api.linear.app/graphql"


@pytest.mark.asyncio
async def test_probe_graphql_always_uses_https() -> None:
    """GraphQL probe uses HTTPS for non-localhost hosts."""
    probed_urls: list[str] = []
    def handler(_request: httpx.Request) -> httpx.Response:
        probed_urls.append(str(_request.url))
        return httpx.Response(404)
    transport = httpx.MockTransport(handler)
    await _probe_graphql(
        "http://some-app.example.com",
        ["api.example.com"],
        transport=transport,
    )
    # Should use https, not http
    for url in probed_urls:
        assert url.startswith("https://"), f"Expected https but got: {url}"


@pytest.mark.asyncio
async def test_probe_graphql_probes_start_url_with_graphql_path() -> None:
    """When start_url contains 'graphql', probe that URL directly."""
    probed_urls: list[str] = []
    def handler(_request: httpx.Request) -> httpx.Response:
        probed_urls.append(str(_request.url))
        body = '{"data":{"__schema":{"queryType":{"name":"Query"}}}}'
        return httpx.Response(200, content=body.encode())
    transport = httpx.MockTransport(handler)
    result = await _probe_graphql(
        "https://store.myshopify.com/admin/api/2024-01/graphql.json",
        ["store.myshopify.com"],
        transport=transport,
    )
    assert result["graphql_detected"] is True
    # start_url itself should be among probed URLs
    assert any("graphql.json" in url for url in probed_urls)


# ── Batch 2b: _probe_hosts ───────────────────────────────────────


def _host_mock_transport(
    status: int = 200,
    headers: dict[str, str] | None = None,
    content_type: str = "application/json",
):
    """Build a MockTransport for host probe tests."""
    h = {"content-type": content_type, **(headers or {})}
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=h)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_probe_hosts_returns_per_host_status() -> None:
    """Host probe returns status and content_type for each allowed host."""
    transport = _host_mock_transport(200, content_type="application/json")
    result = await _probe_hosts(
        "https://dashboard.stripe.com",
        ["api.stripe.com"],
        transport=transport,
    )
    assert "api.stripe.com" in result
    assert result["api.stripe.com"]["status"] == 200
    assert result["api.stripe.com"]["content_type"] == "json"


@pytest.mark.asyncio
async def test_probe_hosts_detects_auth_on_allowed_host() -> None:
    """Host probe detects auth requirement from 401 + WWW-Authenticate."""
    transport = _host_mock_transport(
        401, headers={"WWW-Authenticate": "Bearer"}, content_type="application/json"
    )
    result = await _probe_hosts(
        "https://dashboard.stripe.com",
        ["api.stripe.com"],
        transport=transport,
    )
    assert result["api.stripe.com"]["auth_required"] is True
    assert result["api.stripe.com"]["auth_scheme"] == "Bearer"


@pytest.mark.asyncio
async def test_probe_hosts_detects_html_response() -> None:
    """Host returning HTML is flagged as likely web portal."""
    transport = _host_mock_transport(200, content_type="text/html")
    result = await _probe_hosts(
        "https://dashboard.stripe.com",
        ["admin.shopify.com"],
        transport=transport,
    )
    assert result["admin.shopify.com"]["content_type"] == "html"


@pytest.mark.asyncio
async def test_probe_hosts_timeout_returns_error() -> None:
    """Host probe timeout is captured as error."""
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")
    transport = httpx.MockTransport(handler)
    result = await _probe_hosts(
        "https://dashboard.stripe.com",
        ["api.stripe.com"],
        transport=transport,
    )
    assert result["api.stripe.com"]["error"] == "timeout"


@pytest.mark.asyncio
async def test_probe_hosts_unreachable_returns_error() -> None:
    """Host probe connection error is captured."""
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")
    transport = httpx.MockTransport(handler)
    result = await _probe_hosts(
        "https://dashboard.stripe.com",
        ["api.stripe.com"],
        transport=transport,
    )
    assert result["api.stripe.com"]["error"] == "unreachable"


@pytest.mark.asyncio
async def test_probe_hosts_skips_same_host_as_start_url() -> None:
    """Host probe skips hosts that match start_url's netloc."""
    call_count = 0
    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200)
    transport = httpx.MockTransport(handler)
    result = await _probe_hosts(
        "https://api.stripe.com/some/page",
        ["api.stripe.com"],
        transport=transport,
    )
    assert call_count == 0  # Same host — no separate probe needed
    assert result == {}


# ── Batch 3: _probe_openapi ──────────────────────────────────────


def _openapi_mock_transport(
    found_path: str | None = None,
):
    """Build a MockTransport for OpenAPI probe tests.

    If found_path is set, return 200 for that path; 404 for all others.
    """
    def handler(_request: httpx.Request) -> httpx.Response:
        if found_path and _request.url.path == found_path:
            return httpx.Response(200)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_probe_openapi_found() -> None:
    transport = _openapi_mock_transport("/openapi.json")
    result = await _probe_openapi(
        ["api.example.com"],
        transport=transport,
    )
    assert result["openapi_found"] is True
    assert "openapi.json" in result["openapi_url"]


@pytest.mark.asyncio
async def test_probe_openapi_not_found() -> None:
    transport = _openapi_mock_transport(None)  # All 404s
    result = await _probe_openapi(
        ["api.example.com"],
        transport=transport,
    )
    assert result.get("openapi_found", False) is False


# ── Batch 4: Structured render output ────────────────────────────


def test_render_structured_all_clear(capsys) -> None:
    """All-clear probe shows reachable status with structured format."""
    result = ProbeResult(
        base_status=200,
        host_probes={"api.example.com": {"status": 200, "content_type": "json",
                                          "auth_required": False, "auth_scheme": None,
                                          "error": None}},
    )
    _render_probe_results(result, "https://api.example.com", ["api.example.com"])
    captured = capsys.readouterr()
    assert "Probing" in captured.out
    assert "\u2713" in captured.out  # check mark
    assert "Reachable" in captured.out or "200" in captured.out


def test_render_structured_auth_required(capsys) -> None:
    """Auth required shows warning, scheme, and exact export command."""
    result = ProbeResult(
        base_status=401,
        auth_required=True,
        auth_scheme="Bearer",
    )
    _render_probe_results(result, "https://api.example.com", ["api.example.com"])
    captured = capsys.readouterr()
    assert "\u26A0" in captured.out  # warning icon
    assert "Auth required" in captured.out
    assert "Bearer" in captured.out
    assert "TOOLWRIGHT_AUTH_API_EXAMPLE_COM" in captured.out
    assert "export" in captured.out


def test_render_structured_auth_403_no_scheme(capsys) -> None:
    """403 without WWW-Authenticate still shows auth warning."""
    result = ProbeResult(
        base_status=403,
        auth_required=True,
        auth_scheme=None,
    )
    _render_probe_results(result, "https://api.example.com", ["api.example.com"])
    captured = capsys.readouterr()
    assert "\u26A0" in captured.out
    assert "Auth required" in captured.out
    assert "TOOLWRIGHT_AUTH_API_EXAMPLE_COM" in captured.out


def test_render_structured_openapi_found(capsys) -> None:
    """OpenAPI found shows spec URL and exact import command."""
    result = ProbeResult(
        openapi_found=True,
        openapi_url="https://api.example.com/openapi.json",
    )
    _render_probe_results(result, "https://example.com", ["api.example.com"])
    captured = capsys.readouterr()
    assert "\u2713" in captured.out  # check mark
    assert "OpenAPI" in captured.out
    assert "openapi.json" in captured.out
    assert "capture import" in captured.out
    assert "-a api.example.com" in captured.out


def test_render_structured_graphql_and_openapi(capsys) -> None:
    """Both GraphQL and OpenAPI detected — both shown with import suggestion."""
    result = ProbeResult(
        graphql_detected=True,
        graphql_url="https://api.example.com/graphql",
        openapi_found=True,
        openapi_url="https://api.example.com/openapi.json",
    )
    _render_probe_results(result, "https://example.com", ["api.example.com"])
    captured = capsys.readouterr()
    assert "GraphQL" in captured.out
    assert "OpenAPI" in captured.out
    assert "capture import" in captured.out


def test_render_structured_host_html(capsys) -> None:
    """Host returning HTML shows web portal warning."""
    result = ProbeResult(
        host_probes={"admin.shopify.com": {"status": 200, "content_type": "html",
                                            "auth_required": False, "auth_scheme": None,
                                            "error": None}},
    )
    _render_probe_results(result, "https://dashboard.shopify.com", ["admin.shopify.com"])
    captured = capsys.readouterr()
    assert "\u26A0" in captured.out  # warning
    assert "HTML" in captured.out or "html" in captured.out
    assert "web portal" in captured.out.lower() or "portal" in captured.out.lower()


def test_render_structured_host_timeout(capsys) -> None:
    """Host timeout shows cross icon and timeout message."""
    result = ProbeResult(
        host_probes={"api.stripe.com": {"status": None, "content_type": None,
                                         "auth_required": False, "auth_scheme": None,
                                         "error": "timeout"}},
    )
    _render_probe_results(result, "https://dashboard.stripe.com", ["api.stripe.com"])
    captured = capsys.readouterr()
    assert "\u2717" in captured.out  # cross mark
    assert "timed out" in captured.out.lower()


def test_render_structured_host_unreachable(capsys) -> None:
    """Host unreachable shows cross icon."""
    result = ProbeResult(
        host_probes={"api.stripe.com": {"status": None, "content_type": None,
                                         "auth_required": False, "auth_scheme": None,
                                         "error": "unreachable"}},
    )
    _render_probe_results(result, "https://dashboard.stripe.com", ["api.stripe.com"])
    captured = capsys.readouterr()
    assert "\u2717" in captured.out  # cross mark
    assert "unreachable" in captured.out.lower()


def test_render_host_probe_auth_shows_export(capsys) -> None:
    """Host probe with auth_required shows per-host export command."""
    result = ProbeResult(
        host_probes={"api.stripe.com": {"status": 401, "content_type": "json",
                                         "auth_required": True, "auth_scheme": "Bearer",
                                         "error": None}},
    )
    _render_probe_results(result, "https://dashboard.stripe.com", ["api.stripe.com"])
    captured = capsys.readouterr()
    assert "TOOLWRIGHT_AUTH_API_STRIPE_COM" in captured.out
    assert "export" in captured.out


def test_no_probe_flag_skips_probing() -> None:
    """When no_probe=True, _smart_probe should not be called."""
    from unittest.mock import patch

    with patch("toolwright.cli.mint._smart_probe") as mock_probe:
        from toolwright.cli.mint import run_mint

        # run_mint will fail early because there's no playwright etc, but
        # we only care that _smart_probe was NOT called before it errors.
        try:
            run_mint(
                start_url="https://example.com",
                allowed_hosts=["api.example.com"],
                name=None,
                scope_name="full",
                headless=True,
                script_path=None,
                duration_seconds=10,
                output_root="/tmp/test",
                deterministic=False,
                print_mcp_config=False,
                verbose=False,
                no_probe=True,
            )
        except (SystemExit, Exception):
            pass  # Expected — we only check the mock
        mock_probe.assert_not_called()


def test_probe_runs_by_default_regardless_of_auth_profile() -> None:
    """Probe should run even when auth_profile is set (old gating skipped it)."""
    from unittest.mock import patch

    with patch("toolwright.cli.mint._smart_probe") as mock_probe:
        from toolwright.cli.mint import run_mint

        try:
            run_mint(
                start_url="https://example.com",
                allowed_hosts=["api.example.com"],
                name=None,
                scope_name="full",
                headless=True,
                script_path=None,
                duration_seconds=10,
                output_root="/tmp/test",
                deterministic=False,
                print_mcp_config=False,
                verbose=False,
                auth_profile="nonexistent",
            )
        except (SystemExit, Exception):
            pass  # Expected — auth profile doesn't exist
        mock_probe.assert_called_once()


def test_smart_probe_timeout_completes() -> None:
    """Smart probe completes even with slow/erroring responses (timeouts work)."""
    import time

    def slow_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    transport = httpx.MockTransport(slow_handler)
    start = time.monotonic()
    # _smart_probe should complete quickly because mock transport raises immediately
    _smart_probe(
        ["api.example.com"],
        "https://api.example.com",
        transport=transport,
    )
    elapsed = time.monotonic() - start
    # Should complete well under 10 seconds (probes are concurrent, timeouts are 5s)
    assert elapsed < 10
