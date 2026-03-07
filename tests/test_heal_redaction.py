"""Tests for sensitive field redaction in heal examples."""

from __future__ import annotations


class TestRedactExamples:
    def test_redacts_password_field(self):
        from toolwright.core.heal.redaction import redact_examples

        result = redact_examples({"user.password": "hunter2"})
        assert result["user.password"] == "[REDACTED]"

    def test_redacts_token_field(self):
        from toolwright.core.heal.redaction import redact_examples

        sensitive = {
            "auth.token": "abc",
            "api.secret": "xyz",
            "config.api_key": "k123",
            "user.auth_header": "Bearer tok",
            "profile.ssn": "123-45-6789",
            "payment.credit_card": "4111111111111111",
            "payment.cvv": "123",
        }
        result = redact_examples(sensitive)
        for path in sensitive:
            assert result[path] == "[REDACTED]", f"{path} should be redacted"

    def test_case_insensitive(self):
        from toolwright.core.heal.redaction import redact_examples

        result = redact_examples({
            "user.API_KEY": "k1",
            "data.Password": "pw",
            "config.SECRET": "s1",
        })
        for path in result:
            assert result[path] == "[REDACTED]", f"{path} should be redacted"

    def test_non_sensitive_preserved(self):
        from toolwright.core.heal.redaction import redact_examples

        result = redact_examples({
            "user.name": "Alice",
            "data.count": "42",
            "items[].id": "item_1",
        })
        assert result["user.name"] == "Alice"
        assert result["data.count"] == "42"
        assert result["items[].id"] == "item_1"

    def test_nested_path_matching(self):
        """Redaction checks the leaf key segment, not the full path."""
        from toolwright.core.heal.redaction import redact_examples

        result = redact_examples({"settings.api_key": "k1"})
        assert result["settings.api_key"] == "[REDACTED]"

    def test_array_path_leaf(self):
        """Leaf extraction handles [] suffix."""
        from toolwright.core.heal.redaction import redact_examples

        result = redact_examples({"users[].api_key": "k1"})
        assert result["users[].api_key"] == "[REDACTED]"

    def test_empty_dict(self):
        from toolwright.core.heal.redaction import redact_examples

        assert redact_examples({}) == {}
