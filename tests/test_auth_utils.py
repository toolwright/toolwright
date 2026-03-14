"""Tests for toolwright.utils.auth — shared host-to-env-var normalization."""

from __future__ import annotations

from toolwright.utils.auth import host_to_env_var


class TestHostToEnvVar:
    """Test host_to_env_var() produces correct env var names."""

    def test_dotted_hostname(self) -> None:
        assert host_to_env_var("api.stripe.com") == "TOOLWRIGHT_AUTH_API_STRIPE_COM"

    def test_hostname_with_port(self) -> None:
        assert host_to_env_var("localhost:8080") == "TOOLWRIGHT_AUTH_LOCALHOST_8080"

    def test_simple_hostname(self) -> None:
        assert host_to_env_var("localhost") == "TOOLWRIGHT_AUTH_LOCALHOST"

    def test_github_hostname(self) -> None:
        assert host_to_env_var("api.github.com") == "TOOLWRIGHT_AUTH_API_GITHUB_COM"

    def test_hyphenated_hostname(self) -> None:
        assert host_to_env_var("my-api.example.com") == "TOOLWRIGHT_AUTH_MY_API_EXAMPLE_COM"

    def test_lowercase_input_uppercased(self) -> None:
        result = host_to_env_var("api.stripe.com")
        assert result == result.upper()

    def test_mixed_case_input(self) -> None:
        assert host_to_env_var("Api.Stripe.COM") == "TOOLWRIGHT_AUTH_API_STRIPE_COM"
