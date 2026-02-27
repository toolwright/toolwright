"""Tests for prefixed ID normalization in path normalizer."""

from __future__ import annotations

from toolwright.core.normalize.path_normalizer import PathNormalizer, VarianceNormalizer


class TestPrefixedIDNormalization:
    """PathNormalizer should detect common prefixed ID patterns."""

    def setup_method(self) -> None:
        self.normalizer = PathNormalizer()

    def test_underscore_prefixed_id(self) -> None:
        """usr_123, prod_001, etc."""
        assert self.normalizer.normalize("/api/users/usr_123") == "/api/users/{id}"

    def test_hyphen_prefixed_id(self) -> None:
        """ord-abc123, etc."""
        assert self.normalizer.normalize("/api/orders/ord-abc123") == "/api/orders/{id}"

    def test_stripe_style_customer(self) -> None:
        """cus_test123abc (Stripe customer ID)."""
        assert self.normalizer.normalize("/api/customers/cus_test123abc") == "/api/customers/{id}"

    def test_stripe_style_payment_intent(self) -> None:
        """pi_abc123def456 (Stripe payment intent)."""
        assert self.normalizer.normalize("/api/payments/pi_abc123def456") == "/api/payments/{id}"

    def test_slack_style_user_id(self) -> None:
        """U12345678 (Slack-style uppercase prefix + digits)."""
        assert self.normalizer.normalize("/api/users/U12345678") == "/api/users/{id}"

    def test_short_prefix_with_hex(self) -> None:
        """item_7f3a."""
        assert self.normalizer.normalize("/api/items/item_7f3a") == "/api/items/{id}"

    def test_does_not_normalize_snake_case_route_keys_without_digits(self) -> None:
        """Snake_case route keys without digits are often stable path segments, not IDs."""
        assert (
            self.normalizer.normalize("/api/p/csr/content_types/product_page_blurbs/entries")
            == "/api/p/csr/content_types/product_page_blurbs/entries"
        )

    def test_does_not_match_plain_words(self) -> None:
        """Regular path segments should NOT be normalized."""
        assert self.normalizer.normalize("/api/users") == "/api/users"
        assert self.normalizer.normalize("/api/products") == "/api/products"
        assert self.normalizer.normalize("/api/search") == "/api/search"

    def test_does_not_match_version_segments(self) -> None:
        """v1, v2, etc. should NOT become {id}."""
        assert self.normalizer.normalize("/api/v2/users") == "/api/v2/users"

    def test_preserves_existing_placeholders(self) -> None:
        """Already-parameterized paths should pass through."""
        assert self.normalizer.normalize("/api/users/{id}") == "/api/users/{id}"

    def test_mixed_path(self) -> None:
        """Multiple segments with one being a prefixed ID."""
        result = self.normalizer.normalize("/api/users/usr_123/orders")
        assert result == "/api/users/{id}/orders"

    def test_multiple_prefixed_ids(self) -> None:
        """Multiple prefixed IDs in one path."""
        result = self.normalizer.normalize("/api/users/usr_123/orders/ord_456")
        assert result == "/api/users/{id}/orders/{id}"


class TestVarianceNormalizerPrefixedIDs:
    """VarianceNormalizer should also handle prefixed IDs."""

    def test_variance_normalizes_prefixed_ids(self) -> None:
        """Even without variance, prefixed IDs should be caught by base normalizer."""
        vn = VarianceNormalizer()
        vn.learn_from_paths(["/api/users/usr_123"], "GET")
        result = vn.normalize_path("/api/users/usr_123", "GET")
        assert result == "/api/users/{id}"

    def test_variance_deduplicates_prefixed_ids(self) -> None:
        """Two prefixed IDs under same method should produce one template."""
        vn = VarianceNormalizer()
        vn.learn_from_paths(["/api/users/usr_123", "/api/users/usr_456"], "GET")
        r1 = vn.normalize_path("/api/users/usr_123", "GET")
        r2 = vn.normalize_path("/api/users/usr_456", "GET")
        assert r1 == r2
        assert r1 == "/api/users/{id}"


class TestVarianceNormalizerSlugGeneralization:
    """VarianceNormalizer should generalize slug-like segments when structure matches."""

    def test_generalizes_listing_slug_across_observations(self) -> None:
        """Different product slugs should collapse into one {slug} template."""
        vn = VarianceNormalizer()
        p1 = "/_next/data/BUILD123/en/buy/air-jordan-4-retro-rare-air-white-lettering.json"
        p2 = "/_next/data/BUILD123/en/buy/nike-dunk-low-panda.json"

        vn.learn_from_paths([p1, p2], "GET")

        r1 = vn.normalize_path(p1, "GET")
        r2 = vn.normalize_path(p2, "GET")

        assert r1 == r2
        assert r1 == "/_next/data/BUILD123/en/buy/{slug}.json"

    def test_does_not_merge_unrelated_resource_roots(self) -> None:
        """Different static resource roots should remain distinct templates."""
        vn = VarianceNormalizer()
        p1 = "/api/users/list"
        p2 = "/api/orders/list"

        vn.learn_from_paths([p1, p2], "GET")

        assert vn.normalize_path(p1, "GET") == "/api/users/list"
        assert vn.normalize_path(p2, "GET") == "/api/orders/list"

    def test_does_not_merge_stable_underscored_route_keys(self) -> None:
        """Stable route key segments should not be generalized as slugs."""
        vn = VarianceNormalizer()
        p1 = "/api/p/csr/1/iron_footer_next/entries"
        p2 = "/api/p/csr/1/product_page_blurbs/entries"

        vn.learn_from_paths([p1, p2], "GET")

        assert vn.normalize_path(p1, "GET") == "/api/p/csr/{id}/iron_footer_next/entries"
        assert vn.normalize_path(p2, "GET") == "/api/p/csr/{id}/product_page_blurbs/entries"

    def test_single_observation_slug_json_is_generalized(self) -> None:
        """A single long slug.json listing route should still normalize to {slug}."""
        vn = VarianceNormalizer()
        p1 = "/_next/data/BUILD123/en/buy/air-jordan-4-retro-rare-air-white-lettering.json"

        vn.learn_from_paths([p1], "GET")

        assert vn.normalize_path(p1, "GET") == "/_next/data/BUILD123/en/buy/{slug}.json"

    def test_single_observation_named_json_route_stays_fixed(self) -> None:
        """Stable JSON route keys should not be generalized without slug characteristics."""
        vn = VarianceNormalizer()
        p1 = "/_next/data/BUILD123/en/search.json"

        vn.learn_from_paths([p1], "GET")

        assert vn.normalize_path(p1, "GET") == "/_next/data/BUILD123/en/search.json"


class TestToolNamingWithPrefixedIDs:
    """Tool names should be clean when paths have prefixed IDs."""

    def test_get_detail_name(self) -> None:
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("GET", "/api/users/{id}")
        assert name == "get_user"

    def test_delete_detail_name(self) -> None:
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("DELETE", "/api/users/{id}")
        assert name == "delete_user"

    def test_put_detail_name(self) -> None:
        from toolwright.utils.naming import generate_tool_name

        name = generate_tool_name("PUT", "/api/users/{id}")
        assert name == "update_user"


class TestEndToEndPrefixedIDs:
    """Full pipeline should handle prefixed IDs correctly."""

    def test_aggregator_deduplicates_prefixed_ids(self) -> None:
        """usr_123 and usr_456 under GET should become one endpoint."""
        from toolwright.core.normalize import EndpointAggregator
        from toolwright.models.capture import CaptureSession, HttpExchange, HTTPMethod

        session = CaptureSession(
            id="test",
            name="test",
            allowed_hosts=["api.example.com"],
            exchanges=[
                HttpExchange(
                    id="e1",
                    url="https://api.example.com/api/users/usr_123",
                    method=HTTPMethod.GET,
                    host="api.example.com",
                    path="/api/users/usr_123",
                    response_status=200,
                    response_headers={"Content-Type": "application/json"},
                    response_body='{"id": "usr_123", "name": "Jane"}',
                    response_body_json={"id": "usr_123", "name": "Jane"},
                ),
                HttpExchange(
                    id="e2",
                    url="https://api.example.com/api/users/usr_456",
                    method=HTTPMethod.GET,
                    host="api.example.com",
                    path="/api/users/usr_456",
                    response_status=200,
                    response_headers={"Content-Type": "application/json"},
                    response_body='{"id": "usr_456", "name": "Bob"}',
                    response_body_json={"id": "usr_456", "name": "Bob"},
                ),
            ],
        )

        agg = EndpointAggregator(first_party_hosts=["api.example.com"])
        endpoints = agg.aggregate(session)

        # Should be 1 endpoint (GET /api/users/{id}), not 2
        get_endpoints = [e for e in endpoints if e.method == "GET"]
        assert len(get_endpoints) == 1
        assert get_endpoints[0].path == "/api/users/{id}"
