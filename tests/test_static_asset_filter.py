"""Tests for static asset filtering in endpoint aggregation."""

from __future__ import annotations

from toolwright.core.normalize.aggregator import EndpointAggregator
from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod


def _make_exchange(method: str, path: str, host: str = "api.example.com") -> HttpExchange:
    """Create a minimal exchange for testing."""
    return HttpExchange(
        id=f"ex_{path.replace('/', '_')}",
        method=HTTPMethod(method),
        url=f"https://{host}{path}",
        host=host,
        path=path,
        request_headers={},
        response_status=200,
        response_headers={},
    )


def _make_session(exchanges: list[HttpExchange]) -> CaptureSession:
    """Create a capture session from exchanges."""
    return CaptureSession(
        id="test_session",
        start_url="https://api.example.com",
        allowed_hosts=["api.example.com"],
        exchanges=exchanges,
    )


class TestStaticAssetFiltering:
    """Tests that static assets are excluded from endpoint aggregation."""

    def test_js_files_excluded(self) -> None:
        """JS files should be excluded from endpoints."""
        exchanges = [
            _make_exchange("GET", "/api/v1/products"),
            _make_exchange("GET", "/_next/static/chunks/main-abc123.js"),
            _make_exchange("GET", "/static/js/vendor.js"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        paths = [ep.path for ep in endpoints]
        assert any("/products" in p for p in paths)
        assert not any(".js" in p for p in paths)

    def test_css_files_excluded(self) -> None:
        """CSS files should be excluded."""
        exchanges = [
            _make_exchange("GET", "/api/v1/users"),
            _make_exchange("GET", "/static/styles/main.css"),
            _make_exchange("GET", "/assets/theme.min.css"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        paths = [ep.path for ep in endpoints]
        assert any("/users" in p for p in paths)
        assert not any(".css" in p for p in paths)

    def test_image_files_excluded(self) -> None:
        """Image files should be excluded."""
        exchanges = [
            _make_exchange("GET", "/api/v1/data"),
            _make_exchange("GET", "/images/logo.png"),
            _make_exchange("GET", "/media/product.jpg"),
            _make_exchange("GET", "/icons/cart.svg"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        paths = [ep.path for ep in endpoints]
        assert any("/data" in p for p in paths)
        assert not any(".png" in p for p in paths)
        assert not any(".jpg" in p for p in paths)
        assert not any(".svg" in p for p in paths)

    def test_font_files_excluded(self) -> None:
        """Font files should be excluded."""
        exchanges = [
            _make_exchange("GET", "/api/v1/data"),
            _make_exchange("GET", "/fonts/roboto.woff2"),
            _make_exchange("GET", "/fonts/inter.ttf"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        paths = [ep.path for ep in endpoints]
        assert not any(".woff2" in p for p in paths)
        assert not any(".ttf" in p for p in paths)

    def test_sourcemap_files_excluded(self) -> None:
        """Source map files should be excluded."""
        exchanges = [
            _make_exchange("GET", "/api/v1/data"),
            _make_exchange("GET", "/static/js/main.js.map"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        paths = [ep.path for ep in endpoints]
        assert not any(".map" in p for p in paths)

    def test_json_api_not_excluded(self) -> None:
        """JSON API endpoints should NOT be excluded."""
        exchanges = [
            _make_exchange("GET", "/api/v1/products.json"),
            _make_exchange("GET", "/api/config.json"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        # .json endpoints are API responses, not static assets
        assert len(endpoints) >= 1

    def test_mixed_static_and_api(self) -> None:
        """Mixed static + API traffic should only keep API endpoints."""
        exchanges = [
            _make_exchange("GET", "/api/v1/products"),
            _make_exchange("POST", "/api/v1/cart"),
            _make_exchange("GET", "/_next/static/chunks/app.js"),
            _make_exchange("GET", "/static/css/theme.css"),
            _make_exchange("GET", "/images/hero.png"),
            _make_exchange("GET", "/favicon.ico"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        paths = [ep.path for ep in endpoints]
        assert len(endpoints) == 2
        assert any("/products" in p for p in paths)
        assert any("/cart" in p for p in paths)

    def test_walmart_dfwrs_static_js_filtered(self) -> None:
        """Walmart-style CDN paths serving JS bundles should be filtered."""
        exchanges = [
            _make_exchange("GET", "/dfwrs/abc123/uuid-here/v2/1/_next/static/chunks/ads_core.js"),
            _make_exchange("GET", "/dfwrs/abc123/uuid-here/v2/1/_next/static/chunks/widget.js"),
            _make_exchange("GET", "/orchestra/home/graphql/Location/abc123"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        paths = [ep.path for ep in endpoints]
        assert not any(".js" in p for p in paths)
        # GraphQL endpoint should survive
        assert len(endpoints) >= 1

    def test_ebay_tag_manager_js_filtered(self) -> None:
        """eBay-style tag manager JS files should be filtered."""
        exchanges = [
            _make_exchange("GET", "/tag-manager/v1/tag/utag.js"),
            _make_exchange("GET", "/tag-manager/v1/tag/utag.3.js"),
            _make_exchange("GET", "/tag-manager/v1/tag/utag.10.js"),
            _make_exchange("GET", "/tag-manager/v1/tag/madrona_loadscripts.js"),
            _make_exchange("POST", "/customer/v1/customer_service"),
        ]
        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(_make_session(exchanges))
        paths = [ep.path for ep in endpoints]
        assert not any(".js" in p for p in paths)
        # Customer service API should survive
        assert any("customer" in p for p in paths)
