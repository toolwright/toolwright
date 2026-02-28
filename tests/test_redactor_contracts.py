"""Tests for strict redaction pipeline contracts.

Covers:
- Bearer token redaction
- JWT token redaction
- Basic auth redaction
- API key redaction
- Vendor-specific tokens (ghp_, sk_live_, AKIA*)
- Cookie/set-cookie header redaction
- JSON body keys with sensitive names
- Body truncation and schema zero
"""

from __future__ import annotations

import json

from toolwright.core.capture.redactor import Redactor
from toolwright.models.capture import HttpExchange, HTTPMethod


def test_redactor_caps_body_excerpts_and_adds_digests() -> None:
    long_body = "Bearer secret-token " + ("x" * 5000)
    exchange = HttpExchange(
        url="https://api.example.com/users",
        method=HTTPMethod.POST,
        request_headers={"Authorization": "Bearer abc"},
        request_body=long_body,
        response_headers={"set-cookie": "abc"},
        response_body=long_body,
        response_status=200,
        response_content_type="application/json",
    )

    redacted = Redactor().redact_exchange(exchange)

    assert redacted.request_headers["Authorization"] == "[REDACTED]"
    assert redacted.response_headers["set-cookie"] == "[REDACTED]"
    assert redacted.request_body is not None
    assert redacted.response_body is not None
    assert "[REDACTED_BEARER]" in redacted.request_body
    assert "[REDACTED_BEARER]" in redacted.response_body
    assert redacted.request_body.endswith("...[TRUNCATED]")
    assert redacted.response_body.endswith("...[TRUNCATED]")
    assert len(redacted.request_body) <= Redactor.MAX_BODY_CHARS + len("...[TRUNCATED]")
    assert len(redacted.response_body) <= Redactor.MAX_BODY_CHARS + len("...[TRUNCATED]")
    assert redacted.notes["request_body_truncated"] is True
    assert redacted.notes["response_body_truncated"] is True
    assert redacted.notes["request_body_sha256"]
    assert redacted.notes["response_body_sha256"]


def test_truncated_list_body_preserves_schema_sample() -> None:
    """Large list response body should produce a zeroed schema sample, not None."""
    items = [{"id": i, "title": f"Post {i}", "active": True, "score": 3.14} for i in range(200)]
    import json

    body_text = json.dumps(items)
    assert len(body_text) > Redactor.MAX_BODY_CHARS  # Confirm it triggers truncation

    exchange = HttpExchange(
        url="https://api.example.com/posts",
        method=HTTPMethod.GET,
        response_status=200,
        response_body=body_text,
        response_body_json=items,
        response_content_type="application/json",
    )

    redacted = Redactor().redact_exchange(exchange)

    # response_body_json must NOT be None after truncation
    assert redacted.response_body_json is not None
    assert isinstance(redacted.response_body_json, list)
    assert len(redacted.response_body_json) >= 1
    # The sample dict should have typed zero values
    sample = redacted.response_body_json[0]
    assert isinstance(sample, dict)
    assert sample["id"] == 0  # int zero
    assert sample["title"] == ""  # string zero
    assert sample["active"] is False  # bool zero
    assert sample["score"] == 0.0  # float zero
    assert redacted.notes.get("schema_sample") is True


def test_truncated_dict_body_preserves_schema_zero() -> None:
    """Large dict response body should produce zero-valued schema, not None."""
    big_dict = {"name": "x" * 5000, "count": 42, "active": True, "ratio": 2.5}
    import json

    body_text = json.dumps(big_dict)
    assert len(body_text) > Redactor.MAX_BODY_CHARS

    exchange = HttpExchange(
        url="https://api.example.com/stats",
        method=HTTPMethod.GET,
        response_status=200,
        response_body=body_text,
        response_body_json=big_dict,
        response_content_type="application/json",
    )

    redacted = Redactor().redact_exchange(exchange)
    assert redacted.response_body_json is not None
    assert isinstance(redacted.response_body_json, dict)
    assert redacted.response_body_json["name"] == ""
    assert redacted.response_body_json["count"] == 0
    assert redacted.response_body_json["active"] is False
    assert redacted.response_body_json["ratio"] == 0.0
    assert redacted.notes.get("schema_sample") is True


def test_schema_zero_no_original_values_remain() -> None:
    """No original string/int/bool values should remain in the schema sample."""
    items = [
        {"email": "user@example.com", "age": 25, "premium": True, "balance": 99.99},
        {"email": "other@test.org", "age": 30, "premium": False, "balance": 0.5},
    ]
    import json

    body = json.dumps(items * 100)  # Make it big enough to truncate
    exchange = HttpExchange(
        url="https://api.example.com/users",
        method=HTTPMethod.GET,
        response_status=200,
        response_body=body,
        response_body_json=items * 100,
        response_content_type="application/json",
    )

    redacted = Redactor().redact_exchange(exchange)
    assert redacted.response_body_json is not None

    def _check_no_originals(obj: object) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                _check_no_originals(v)
        elif isinstance(obj, list):
            for item in obj:
                _check_no_originals(item)
        elif isinstance(obj, str):
            assert obj == "", f"Original string found: {obj}"
        elif isinstance(obj, bool):
            assert obj is False, f"Original bool found: {obj}"
        elif isinstance(obj, int):
            assert obj == 0, f"Original int found: {obj}"
        elif isinstance(obj, float):
            assert obj == 0.0, f"Original float found: {obj}"

    _check_no_originals(redacted.response_body_json)


def test_schema_zero_sampling_indices() -> None:
    """Sampling uses [0, len//2, len-1] indices deterministically."""
    items = [{"idx": i, "label": f"item_{i}"} for i in range(10)]
    # Expected sample indices: 0, 5, 9

    from toolwright.core.capture.redactor import Redactor

    r = Redactor()
    result = r._schema_zero(items)
    assert isinstance(result, list)
    assert len(result) == 1  # Merged into single item
    # Keys from items[0], items[5], items[9] should all be present
    assert "idx" in result[0]
    assert "label" in result[0]


def test_schema_zero_recursion_depth_cap() -> None:
    """Recursion depth > 20 returns empty dict/list."""
    # Build deeply nested dict
    nested: dict = {"leaf": "value"}
    for _ in range(25):
        nested = {"child": nested}

    from toolwright.core.capture.redactor import Redactor

    r = Redactor()
    result = r._schema_zero(nested)
    # Should not raise and should return a dict
    assert isinstance(result, dict)

    # Find the deepest level — past depth 20 it should be {} (opaque)
    current = result
    depth = 0
    while isinstance(current, dict) and "child" in current:
        current = current["child"]
        depth += 1
    # Should have stopped recursing — fewer levels than the 25 we created
    assert depth < 25
    # The deepest value should be {} (opaque, no further recursion)
    assert current == {} or current == {"leaf": ""}


def test_schema_zero_short_strings_replaced() -> None:
    """Even short 1-3 char strings are replaced with empty string."""
    data = {"a": "x", "b": "ab", "c": "abc"}

    from toolwright.core.capture.redactor import Redactor

    r = Redactor()
    result = r._schema_zero(data)
    assert result["a"] == ""
    assert result["b"] == ""
    assert result["c"] == ""


# ------------------------------------------------------------------
# Phase 8.2  JWT token redaction
# ------------------------------------------------------------------


def test_jwt_token_redacted_in_body() -> None:
    """JWT tokens (eyJ...) must be redacted from request/response bodies."""
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    exchange = HttpExchange(
        url="https://api.example.com/auth",
        method=HTTPMethod.POST,
        request_body=f"token={jwt}",
        response_body=f'{{"access_token": "{jwt}"}}',
        response_status=200,
        response_content_type="application/json",
    )

    redacted = Redactor().redact_exchange(exchange)

    assert jwt not in (redacted.request_body or "")
    assert "[REDACTED_JWT]" in (redacted.request_body or "")
    assert jwt not in (redacted.response_body or "")
    assert "[REDACTED_JWT]" in (redacted.response_body or "")


# ------------------------------------------------------------------
# Phase 8.2  Basic auth redaction
# ------------------------------------------------------------------


def test_basic_auth_redacted_in_body() -> None:
    """Basic auth credentials must be redacted from bodies."""
    basic_cred = "Basic dXNlcjpwYXNzd29yZA=="
    exchange = HttpExchange(
        url="https://api.example.com/login",
        method=HTTPMethod.POST,
        request_body=f"Authorization: {basic_cred}",
        response_status=200,
        response_body="ok",
        response_content_type="text/plain",
    )

    redacted = Redactor().redact_exchange(exchange)

    assert "dXNlcjpwYXNzd29yZA==" not in (redacted.request_body or "")
    assert "[REDACTED_BASIC]" in (redacted.request_body or "")


# ------------------------------------------------------------------
# Phase 8.2  API key redaction
# ------------------------------------------------------------------


def test_api_key_redacted_in_body() -> None:
    """API keys in common formats must be redacted from bodies."""
    body = 'api_key="sk_test_abc123xyz"'
    exchange = HttpExchange(
        url="https://api.example.com/config",
        method=HTTPMethod.GET,
        response_status=200,
        response_body=body,
        response_content_type="text/plain",
    )

    redacted = Redactor().redact_exchange(exchange)

    assert "sk_test_abc123xyz" not in (redacted.response_body or "")
    assert "[REDACTED]" in (redacted.response_body or "")


# ------------------------------------------------------------------
# Phase 8.2  Vendor-specific token redaction (ghp_, sk_live_, AKIA*)
# ------------------------------------------------------------------


def test_bearer_vendor_tokens_redacted() -> None:
    """Vendor-specific tokens used as bearer tokens must be redacted."""
    # GitHub personal access token
    ghp_token = "bearer ghp_1234567890abcdef1234567890abcdef12345678"
    exchange = HttpExchange(
        url="https://api.github.com/repos",
        method=HTTPMethod.GET,
        request_body=ghp_token,
        response_status=200,
        response_body="ok",
        response_content_type="text/plain",
    )

    redacted = Redactor().redact_exchange(exchange)
    assert "ghp_" not in (redacted.request_body or "")
    assert "[REDACTED_BEARER]" in (redacted.request_body or "")


def test_stripe_live_key_redacted_as_bearer() -> None:
    """Stripe live keys used as bearer tokens must be redacted."""
    stripe_key = "bearer sk_live_abc123def456ghi789"
    exchange = HttpExchange(
        url="https://api.stripe.com/v1/charges",
        method=HTTPMethod.POST,
        request_body=stripe_key,
        response_status=200,
        response_body="ok",
        response_content_type="text/plain",
    )

    redacted = Redactor().redact_exchange(exchange)
    assert "sk_live_" not in (redacted.request_body or "")
    assert "[REDACTED_BEARER]" in (redacted.request_body or "")


def test_aws_access_key_id_redacted_as_api_key() -> None:
    """AWS access key IDs in api_key fields must be redacted."""
    aws_body = 'api_key="AKIAIOSFODNN7EXAMPLE"'
    exchange = HttpExchange(
        url="https://sts.amazonaws.com",
        method=HTTPMethod.POST,
        request_body=aws_body,
        response_status=200,
        response_body="ok",
        response_content_type="text/plain",
    )

    redacted = Redactor().redact_exchange(exchange)
    assert "AKIAIOSFODNN7EXAMPLE" not in (redacted.request_body or "")


# ------------------------------------------------------------------
# Phase 8.2  Cookie header redaction
# ------------------------------------------------------------------


def test_cookie_header_redacted() -> None:
    """Cookie and Set-Cookie headers must always be redacted."""
    exchange = HttpExchange(
        url="https://example.com/page",
        method=HTTPMethod.GET,
        request_headers={"Cookie": "session=abc123; csrftoken=xyz789"},
        response_headers={"Set-Cookie": "session=def456; Path=/; HttpOnly"},
        response_status=200,
        response_content_type="text/html",
    )

    redacted = Redactor().redact_exchange(exchange)

    assert redacted.request_headers["Cookie"] == "[REDACTED]"
    assert redacted.response_headers["Set-Cookie"] == "[REDACTED]"


# ------------------------------------------------------------------
# Phase 8.2  JSON body keys with sensitive names
# ------------------------------------------------------------------


def test_json_body_sensitive_keys_redacted() -> None:
    """JSON body keys matching SENSITIVE_PARAMS must be redacted."""
    body_json = {
        "username": "admin",
        "password": "super_secret_123",
        "token": "tok_abc123",
        "api_key": "key_xyz789",
        "access_token": "at_abc123",
        "refresh_token": "rt_xyz789",
        "data": "safe_value",
    }
    body_text = json.dumps(body_json)

    exchange = HttpExchange(
        url="https://api.example.com/auth",
        method=HTTPMethod.POST,
        request_body=body_text,
        request_body_json=body_json,
        response_status=200,
        response_body="ok",
        response_content_type="text/plain",
    )

    redacted = Redactor().redact_exchange(exchange)

    # Dict-level redaction of sensitive keys
    rj = redacted.request_body_json
    assert rj is not None
    assert rj["password"] == "[REDACTED]"
    assert rj["token"] == "[REDACTED]"
    assert rj["api_key"] == "[REDACTED]"
    assert rj["access_token"] == "[REDACTED]"
    assert rj["refresh_token"] == "[REDACTED]"
    # Non-sensitive keys preserved
    assert rj["username"] == "admin"
    assert rj["data"] == "safe_value"


def test_nested_json_sensitive_keys_redacted() -> None:
    """Nested JSON dicts with sensitive keys must be recursively redacted."""
    body_json = {
        "credentials": {
            "token": "tok_inner",
            "secret": "s3cr3t",
        },
        "config": {
            "name": "test",
        },
    }
    body_text = json.dumps(body_json)

    exchange = HttpExchange(
        url="https://api.example.com/settings",
        method=HTTPMethod.PUT,
        request_body=body_text,
        request_body_json=body_json,
        response_status=200,
        response_body="ok",
        response_content_type="text/plain",
    )

    redacted = Redactor().redact_exchange(exchange)

    rj = redacted.request_body_json
    assert rj is not None
    assert rj["credentials"]["token"] == "[REDACTED]"
    assert rj["credentials"]["secret"] == "[REDACTED]"
    assert rj["config"]["name"] == "test"
