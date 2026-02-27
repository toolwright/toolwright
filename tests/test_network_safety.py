"""Tests for the shared network safety module.

Ensures that SSRF prevention, IP validation, host normalization, and URL
scheme checks behave identically regardless of which runtime surface
(HTTP gateway or MCP server) uses them.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from toolwright.core.network_safety import (
    RuntimeBlockError,
    host_matches_allowlist,
    is_ip_allowed,
    normalize_host_for_allowlist,
    resolved_ips,
    validate_network_target,
    validate_url_scheme,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _net(cidr: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    return ipaddress.ip_network(cidr, strict=False)


def _ip(addr: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    return ipaddress.ip_address(addr)


# ---------------------------------------------------------------------------
# is_ip_allowed
# ---------------------------------------------------------------------------


class TestIsIpAllowed:
    """IP classification — fail-closed by default."""

    def test_blocks_loopback_by_default(self) -> None:
        assert is_ip_allowed(_ip("127.0.0.1"), []) is False
        assert is_ip_allowed(_ip("::1"), []) is False

    def test_permits_loopback_when_cidr_allowlisted(self) -> None:
        assert is_ip_allowed(_ip("127.0.0.1"), [_net("127.0.0.0/8")]) is True
        assert is_ip_allowed(_ip("::1"), [_net("::1/128")]) is True

    def test_always_blocks_link_local(self) -> None:
        # link-local must be blocked even when private networks are allowed
        assert is_ip_allowed(_ip("169.254.1.2"), [_net("169.254.0.0/16")]) is False

    def test_always_blocks_multicast(self) -> None:
        assert is_ip_allowed(_ip("224.0.0.1"), [_net("224.0.0.0/4")]) is False

    def test_always_blocks_unspecified(self) -> None:
        assert is_ip_allowed(_ip("0.0.0.0"), [_net("0.0.0.0/0")]) is False
        assert is_ip_allowed(_ip("::"), [_net("::/0")]) is False

    def test_blocks_private_by_default(self) -> None:
        assert is_ip_allowed(_ip("10.0.0.1"), []) is False
        assert is_ip_allowed(_ip("192.168.1.1"), []) is False
        assert is_ip_allowed(_ip("172.16.0.1"), []) is False

    def test_permits_private_when_cidr_allowlisted(self) -> None:
        assert is_ip_allowed(_ip("10.0.0.1"), [_net("10.0.0.0/8")]) is True
        assert is_ip_allowed(_ip("192.168.1.1"), [_net("192.168.0.0/16")]) is True

    def test_permits_public_ip(self) -> None:
        assert is_ip_allowed(_ip("8.8.8.8"), []) is True
        assert is_ip_allowed(_ip("1.1.1.1"), []) is True
        assert is_ip_allowed(_ip("2606:4700::1111"), []) is True


# ---------------------------------------------------------------------------
# resolved_ips
# ---------------------------------------------------------------------------


class TestResolvedIps:
    """DNS resolution with IP-literal fast path."""

    def test_ipv4_literal_skips_dns(self) -> None:
        result = resolved_ips("8.8.8.8")
        assert result == [_ip("8.8.8.8")]

    def test_ipv6_literal_skips_dns(self) -> None:
        result = resolved_ips("::1")
        assert result == [_ip("::1")]

    def test_hostname_resolves_via_dns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_getaddrinfo(_host: str, _port, **_kwargs):
            return [
                (socket.AF_INET, 0, 0, "", ("93.184.216.34", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        result = resolved_ips("example.com")
        assert _ip("93.184.216.34") in result

    def test_dns_failure_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_getaddrinfo(_host: str, _port, **_kwargs):
            raise socket.gaierror("Name resolution failed")

        monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
        with pytest.raises(RuntimeBlockError) as exc_info:
            resolved_ips("nonexistent.invalid")
        assert "denied_host_resolution_failed" in str(exc_info.value.reason_code)

    def test_empty_resolution_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def empty_getaddrinfo(_host: str, _port, **_kwargs):
            return []

        monkeypatch.setattr(socket, "getaddrinfo", empty_getaddrinfo)
        with pytest.raises(RuntimeBlockError):
            resolved_ips("empty.invalid")


# ---------------------------------------------------------------------------
# validate_network_target
# ---------------------------------------------------------------------------


class TestValidateNetworkTarget:
    """Fail-closed network target validation."""

    def test_blocks_if_any_ip_disallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mixed public + private IPs → block (fail-closed)."""

        def fake_getaddrinfo(_host: str, _port, **_kwargs):
            return [
                (socket.AF_INET, 0, 0, "", ("8.8.8.8", 0)),
                (socket.AF_INET, 0, 0, "", ("10.0.0.1", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(RuntimeBlockError):
            validate_network_target("example.com", [])

    def test_blocks_metadata_ip_always(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cloud metadata endpoint is always blocked, even with private CIDRs allowed."""

        def fake_getaddrinfo(_host: str, _port, **_kwargs):
            return [
                (socket.AF_INET, 0, 0, "", ("169.254.169.254", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(RuntimeBlockError) as exc_info:
            validate_network_target("metadata.internal", [_net("169.254.0.0/16")])
        assert "metadata" in exc_info.value.message.lower()

    def test_allows_all_public_ips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_getaddrinfo(_host: str, _port, **_kwargs):
            return [
                (socket.AF_INET, 0, 0, "", ("93.184.216.34", 0)),
                (socket.AF_INET, 0, 0, "", ("93.184.216.35", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        # Should not raise
        validate_network_target("example.com", [])

    def test_ip_literal_validated_directly(self) -> None:
        """IP literal should be validated without DNS, blocked if private."""
        with pytest.raises(RuntimeBlockError):
            validate_network_target("10.0.0.1", [])

    def test_ip_literal_public_allowed(self) -> None:
        """Public IP literal should pass."""
        validate_network_target("8.8.8.8", [])


# ---------------------------------------------------------------------------
# normalize_host_for_allowlist
# ---------------------------------------------------------------------------


class TestNormalizeHostForAllowlist:
    """Host normalization for consistent allowlist matching."""

    def test_strips_port(self) -> None:
        assert normalize_host_for_allowlist("api.example.com:443") == "api.example.com"

    def test_strips_ipv6_brackets_and_port(self) -> None:
        assert normalize_host_for_allowlist("[::1]:8443") == "::1"

    def test_strips_ipv6_brackets_without_port(self) -> None:
        assert normalize_host_for_allowlist("[2001:db8::1]") == "2001:db8::1"

    def test_strips_trailing_dot(self) -> None:
        assert normalize_host_for_allowlist("api.example.com.") == "api.example.com"

    def test_lowercases(self) -> None:
        assert normalize_host_for_allowlist("API.Example.COM") == "api.example.com"

    def test_passthrough(self) -> None:
        assert normalize_host_for_allowlist("api.example.com") == "api.example.com"

    def test_empty_string(self) -> None:
        assert normalize_host_for_allowlist("") == ""
        assert normalize_host_for_allowlist("  ") == ""


# ---------------------------------------------------------------------------
# host_matches_allowlist
# ---------------------------------------------------------------------------


class TestHostMatchesAllowlist:
    """Allowlist matching with normalization."""

    def test_exact_match(self) -> None:
        assert host_matches_allowlist("api.example.com", {"api.example.com"}) is True

    def test_exact_match_case_insensitive(self) -> None:
        assert host_matches_allowlist("API.Example.COM", {"api.example.com"}) is True

    def test_wildcard_matches_subdomain(self) -> None:
        assert host_matches_allowlist("sub.example.com", {"*.example.com"}) is True

    def test_wildcard_does_not_match_bare_domain(self) -> None:
        assert host_matches_allowlist("example.com", {"*.example.com"}) is False

    def test_wildcard_does_not_match_deep_subdomain(self) -> None:
        assert host_matches_allowlist("a.b.example.com", {"*.example.com"}) is False

    def test_port_in_candidate_stripped(self) -> None:
        assert host_matches_allowlist("api.example.com:443", {"api.example.com"}) is True

    def test_ipv6_bracket_normalization(self) -> None:
        assert host_matches_allowlist("[::1]:8443", {"::1"}) is True

    def test_trailing_dot_normalization(self) -> None:
        assert host_matches_allowlist("api.example.com.", {"api.example.com"}) is True

    def test_no_match(self) -> None:
        assert host_matches_allowlist("evil.com", {"api.example.com"}) is False

    def test_empty_allowlist(self) -> None:
        assert host_matches_allowlist("api.example.com", set()) is False


# ---------------------------------------------------------------------------
# validate_url_scheme
# ---------------------------------------------------------------------------


class TestValidateUrlScheme:
    """URL scheme validation."""

    def test_allows_https(self) -> None:
        validate_url_scheme("https://api.example.com/v1/users")

    def test_allows_http(self) -> None:
        validate_url_scheme("http://api.example.com/v1/users")

    def test_blocks_file_scheme(self) -> None:
        with pytest.raises(RuntimeBlockError):
            validate_url_scheme("file:///etc/passwd")

    def test_blocks_ftp_scheme(self) -> None:
        with pytest.raises(RuntimeBlockError):
            validate_url_scheme("ftp://example.com/file")

    def test_blocks_empty_scheme(self) -> None:
        with pytest.raises(RuntimeBlockError):
            validate_url_scheme("example.com/path")
