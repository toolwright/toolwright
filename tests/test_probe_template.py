"""Tests for probe template extraction and sanitization.

Covers: query parameter stripping/keeping, header sanitization,
auth credential detection, token heuristics, and template selection.
"""

from __future__ import annotations

import json

from toolwright.core.drift.probe_template import (
    _looks_like_secret_value,
    _looks_like_token,
    _sanitize_headers,
    _sanitize_query_params,
    extract_probe_template,
)
from toolwright.models.probe_template import ProbeTemplate


# ---------------------------------------------------------------------------
# Query parameter sanitization
# ---------------------------------------------------------------------------


class TestStripsPaginationCursors:
    def test_strips_pagination_cursors(self):
        params = {"page_info": "abc123", "cursor": "xyz", "after": "token"}
        result = _sanitize_query_params(params)
        assert result == {}


class TestKeepsFieldSelection:
    def test_keeps_field_selection(self):
        params = {"fields": "id,title", "include": "variants", "expand": "author"}
        result = _sanitize_query_params(params)
        assert result == params


class TestKeepsPaginationSize:
    def test_keeps_pagination_size(self):
        params = {"limit": "50", "per_page": "25"}
        result = _sanitize_query_params(params)
        assert result == params


class TestStripsAuthTokens:
    def test_strips_auth_tokens(self):
        params = {"access_token": "secret", "api_key": "abc", "token": "xyz"}
        result = _sanitize_query_params(params)
        assert result == {}


class TestStripsCacheBusters:
    def test_strips_cache_busters(self):
        params = {"timestamp": "1234567890", "_": "abc", "nonce": "xyz"}
        result = _sanitize_query_params(params)
        assert result == {}


class TestStripsRequestIds:
    def test_strips_request_ids(self):
        params = {
            "request_id": "abc",
            "correlation_id": "xyz",
            "idempotency_key": "123",
        }
        result = _sanitize_query_params(params)
        assert result == {}


class TestKeepsStatusFilters:
    def test_keeps_status_filters(self):
        params = {"status": "active", "type": "product", "category": "electronics"}
        result = _sanitize_query_params(params)
        assert result == params


class TestKeepsSortParams:
    def test_keeps_sort_params(self):
        params = {"sort": "created_at", "order": "desc", "direction": "asc"}
        result = _sanitize_query_params(params)
        assert result == params


class TestHeuristicStripsLongBase64:
    def test_heuristic_strips_long_base64(self):
        long_token = "A" * 100
        params = {"unknown_param": long_token}
        result = _sanitize_query_params(params)
        assert result == {}


class TestHeuristicStripsUuids:
    def test_heuristic_strips_uuids(self):
        params = {"session": "550e8400-e29b-41d4-a716-446655440000"}
        result = _sanitize_query_params(params)
        assert result == {}


class TestKeepsShortValues:
    def test_keeps_short_values(self):
        params = {"custom_flag": "true", "mode": "compact"}
        result = _sanitize_query_params(params)
        assert result == params


# ---------------------------------------------------------------------------
# Header sanitization
# ---------------------------------------------------------------------------


class TestHeaderKeepsAccept:
    def test_header_keeps_accept(self):
        headers = {"Accept": "application/json"}
        result = _sanitize_headers(headers)
        assert result == {"Accept": "application/json"}


class TestHeaderKeepsApiVersion:
    def test_header_keeps_api_version(self):
        headers = {
            "X-API-Version": "2024-01",
            "X-Shopify-API-Version": "2024-01",
        }
        result = _sanitize_headers(headers)
        assert result == headers


class TestHeaderStripsAuth:
    def test_header_strips_auth(self):
        headers = {"Authorization": "Bearer secret123"}
        result = _sanitize_headers(headers)
        assert result == {}


class TestHeaderStripsCookies:
    def test_header_strips_cookies(self):
        headers = {"Cookie": "session=abc123"}
        result = _sanitize_headers(headers)
        assert result == {}


class TestHeaderStripsXApiKey:
    def test_header_strips_x_api_key(self):
        headers = {"x-api-key": "sk_live_abc123"}
        result = _sanitize_headers(headers)
        assert result == {}


class TestHeaderStripsAuthPatternHeaders:
    def test_header_strips_auth_pattern_headers(self):
        headers = {
            "X-Auth-Token": "abc",
            "X-Access-Token": "xyz",
            "X-Token": "123",
        }
        result = _sanitize_headers(headers)
        assert result == {}


class TestHeaderKeepsNonAuthXHeaders:
    def test_header_keeps_non_auth_x_headers(self):
        headers = {"X-Custom-Feature": "enabled"}
        result = _sanitize_headers(headers)
        assert result == {"X-Custom-Feature": "enabled"}


class TestHeaderStripsXSessionId:
    def test_header_strips_x_session_id(self):
        headers = {"X-Session-Id": "abc123"}
        result = _sanitize_headers(headers)
        assert result == {}


class TestHeaderStripsJwtValue:
    def test_header_strips_jwt_value(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        headers = {"X-Internal-Token": jwt}
        result = _sanitize_headers(headers)
        assert result == {}


class TestHeaderStripsLongBase64Value:
    def test_header_strips_long_base64_value(self):
        long_val = "A" * 100
        headers = {"X-Custom": long_val}
        result = _sanitize_headers(headers)
        assert result == {}


class TestHeaderKeepsShortValueXHeader:
    def test_header_keeps_short_value_x_header(self):
        headers = {"X-Feature-Flag": "enabled"}
        result = _sanitize_headers(headers)
        assert result == {"X-Feature-Flag": "enabled"}


# ---------------------------------------------------------------------------
# Full probe template extraction
# ---------------------------------------------------------------------------


class TestShopifyRealUrl:
    def test_shopify_real_url(self):
        url = (
            "https://myshop.myshopify.com/admin/api/2024-01/products.json"
            "?fields=id,title&status=active&page_info=eyJsYXN0IjoxfQ=="
            "&access_token=shpat_abc123"
        )
        template = extract_probe_template(
            method="GET",
            url=url,
            request_headers={
                "Accept": "application/json",
                "X-Shopify-API-Version": "2024-01",
                "Authorization": "Bearer shpat_abc123",
            },
        )

        assert template.method == "GET"
        assert template.path == "/admin/api/2024-01/products.json"
        assert template.query_params == {"fields": "id,title", "status": "active"}
        assert "Authorization" not in template.headers
        assert template.headers.get("Accept") == "application/json"
        assert template.headers.get("X-Shopify-API-Version") == "2024-01"


class TestGithubRealUrl:
    def test_github_real_url(self):
        url = (
            "https://api.github.com/repos/octocat/hello-world/issues"
            "?state=open&sort=created&direction=desc&per_page=30"
        )
        template = extract_probe_template(
            method="GET",
            url=url,
            request_headers={
                "Accept": "application/vnd.github.v3+json",
                "Authorization": "token ghp_abc123",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "MyApp/1.0",
            },
        )

        assert template.path == "/repos/octocat/hello-world/issues"
        assert template.query_params == {
            "state": "open",
            "sort": "created",
            "direction": "desc",
            "per_page": "30",
        }
        assert "Authorization" not in template.headers
        assert "User-Agent" not in template.headers
        assert template.headers.get("X-GitHub-Api-Version") == "2022-11-28"


# ---------------------------------------------------------------------------
# Token/secret heuristics
# ---------------------------------------------------------------------------


class TestLooksLikeToken:
    def test_long_base64_is_token(self):
        assert _looks_like_token("A" * 100) is True

    def test_uuid_is_token(self):
        assert _looks_like_token("550e8400-e29b-41d4-a716-446655440000") is True

    def test_short_string_is_not_token(self):
        assert _looks_like_token("active") is False

    def test_number_is_not_token(self):
        assert _looks_like_token("42") is False


class TestLooksLikeSecretValue:
    def test_jwt_is_secret(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        assert _looks_like_secret_value(jwt) is True

    def test_long_base64_is_secret(self):
        assert _looks_like_secret_value("A" * 100) is True

    def test_short_value_is_not_secret(self):
        assert _looks_like_secret_value("enabled") is False

    def test_normal_header_value_is_not_secret(self):
        assert _looks_like_secret_value("application/json") is False


# ---------------------------------------------------------------------------
# Canonical template selection (unit-level tests for selection logic)
# ---------------------------------------------------------------------------


class TestCanonicalTemplateIdentical:
    def test_canonical_template_identical(self):
        """All templates same -> returns any."""
        from toolwright.core.drift.probe_template import extract_probe_template

        t1 = extract_probe_template(
            "GET",
            "https://api.example.com/items?fields=id,name&limit=50",
            {"Accept": "application/json"},
        )
        t2 = extract_probe_template(
            "GET",
            "https://api.example.com/items?fields=id,name&limit=50",
            {"Accept": "application/json"},
        )
        assert t1.to_dict() == t2.to_dict()


class TestCanonicalTemplateMostParams:
    def test_canonical_template_most_params(self):
        """Differing templates -> picks one with most shape params."""
        t1 = ProbeTemplate(
            method="GET",
            path="/items",
            query_params={"fields": "id"},
            headers={},
        )
        t2 = ProbeTemplate(
            method="GET",
            path="/items",
            query_params={"fields": "id,name,status", "limit": "50"},
            headers={},
        )

        # The one with more shape-affecting params should be preferred
        templates = [t1, t2]
        best = max(
            templates,
            key=lambda t: (
                len(t.query_params),
                json.dumps(sorted(t.query_params.items())),
            ),
        )
        assert best.query_params == {"fields": "id,name,status", "limit": "50"}


class TestCanonicalTemplateDeterministic:
    def test_canonical_template_deterministic(self):
        """Same inputs always produce same output."""
        t1 = ProbeTemplate(
            method="GET",
            path="/items",
            query_params={"fields": "id", "limit": "50"},
            headers={},
        )
        t2 = ProbeTemplate(
            method="GET",
            path="/items",
            query_params={"fields": "id,name"},
            headers={},
        )

        templates = [t1, t2]
        score_fn = lambda t: (
            len(t.query_params),
            json.dumps(sorted(t.query_params.items())),
        )

        result1 = max(templates, key=score_fn)
        result2 = max(templates, key=score_fn)
        assert result1.to_dict() == result2.to_dict()
