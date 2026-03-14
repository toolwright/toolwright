"""Phase 1.3 hardening tests: expanded SSRF metadata endpoint hard-block list.

The cloud metadata service is reachable at multiple IP addresses across
different cloud providers and instance types:

- ``169.254.169.254`` -- classic AWS / GCP / Azure metadata (IMDSv1/v2)
- ``169.254.170.2``   -- AWS ECS task metadata endpoint
- ``fd00:ec2::254``   -- AWS IPv6 metadata endpoint

All three must be **unconditionally blocked** -- they must not be overridable
by any allowlist or private-CIDR exception.

These tests also exercise the broader network safety surface to ensure that
hardening changes do not regress existing behavior.
"""

from __future__ import annotations

import ipaddress
from unittest.mock import patch

import pytest

from toolwright.core.network_safety import (
    RuntimeBlockError,
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


def _mock_resolved_ips(*addrs: str):
    """Return a mock replacement for ``resolved_ips`` that returns *addrs*."""
    ips = [_ip(a) for a in addrs]

    def _fake(_host: str):
        return ips

    return _fake


# ---------------------------------------------------------------------------
# Metadata hard-block tests
# ---------------------------------------------------------------------------


class TestMetadataEndpointsHardBlocked:
    """All cloud metadata endpoints must be hard-blocked regardless of allowlists."""

    # -- Classic AWS / GCP / Azure metadata ----------------------------------

    def test_blocks_classic_metadata_169_254_169_254(self) -> None:
        """169.254.169.254 is hard-blocked (existing behavior)."""
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("169.254.169.254"),
        ), pytest.raises(RuntimeBlockError, match="metadata"):
            validate_network_target("metadata.internal", [])

    def test_classic_metadata_not_overridable_by_allowlist(self) -> None:
        """Even with the full link-local range allowed, 169.254.169.254 stays blocked."""
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("169.254.169.254"),
        ), pytest.raises(RuntimeBlockError, match="metadata"):
            validate_network_target(
                "metadata.internal", [_net("169.254.0.0/16")]
            )

    # -- AWS ECS metadata ----------------------------------------------------

    def test_blocks_ecs_metadata_169_254_170_2(self) -> None:
        """169.254.170.2 (ECS task metadata) must be hard-blocked."""
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("169.254.170.2"),
        ), pytest.raises(RuntimeBlockError, match="metadata"):
            validate_network_target("ecs-metadata.internal", [])

    def test_ecs_metadata_not_overridable_by_allowlist(self) -> None:
        """Even with the full link-local range allowed, 169.254.170.2 stays blocked."""
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("169.254.170.2"),
        ), pytest.raises(RuntimeBlockError, match="metadata"):
            validate_network_target(
                "ecs-metadata.internal", [_net("169.254.0.0/16")]
            )

    # -- AWS IPv6 metadata ---------------------------------------------------

    def test_blocks_ipv6_metadata_fd00_ec2(self) -> None:
        """fd00:ec2::254 (AWS IPv6 metadata) must be hard-blocked."""
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("fd00:ec2::254"),
        ), pytest.raises(RuntimeBlockError, match="metadata"):
            validate_network_target("ipv6-metadata.internal", [])

    def test_ipv6_metadata_not_overridable_by_allowlist(self) -> None:
        """Even with the fd00::/8 ULA range allowed, fd00:ec2::254 stays blocked."""
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("fd00:ec2::254"),
        ), pytest.raises(RuntimeBlockError, match="metadata"):
            validate_network_target(
                "ipv6-metadata.internal", [_net("fd00::/8")]
            )

    # -- IP literal direct invocation ----------------------------------------

    def test_ip_literal_classic_metadata_blocked(self) -> None:
        """Passing 169.254.169.254 as an IP literal must still be blocked."""
        with pytest.raises(RuntimeBlockError, match="metadata"):
            validate_network_target("169.254.169.254", [_net("169.254.0.0/16")])

    def test_ip_literal_ecs_metadata_blocked(self) -> None:
        """Passing 169.254.170.2 as an IP literal must still be blocked."""
        with pytest.raises(RuntimeBlockError, match="metadata"):
            validate_network_target("169.254.170.2", [_net("169.254.0.0/16")])


# ---------------------------------------------------------------------------
# Private CIDR behavior (non-metadata)
# ---------------------------------------------------------------------------


class TestPrivateCIDRBehavior:
    """Private network addresses blocked by default, allowed when explicitly permitted."""

    def test_private_10_blocked_by_default(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("10.0.0.1"),
        ), pytest.raises(RuntimeBlockError):
            validate_network_target("internal.corp", [])

    def test_private_172_16_blocked_by_default(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("172.16.5.10"),
        ), pytest.raises(RuntimeBlockError):
            validate_network_target("internal.corp", [])

    def test_private_192_168_blocked_by_default(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("192.168.1.1"),
        ), pytest.raises(RuntimeBlockError):
            validate_network_target("router.local", [])

    def test_private_10_allowed_when_permitted(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("10.0.0.1"),
        ):
            validate_network_target("internal.corp", [_net("10.0.0.0/8")])

    def test_private_192_168_allowed_when_permitted(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("192.168.1.1"),
        ):
            validate_network_target("router.local", [_net("192.168.0.0/16")])


# ---------------------------------------------------------------------------
# Loopback behavior
# ---------------------------------------------------------------------------


class TestLoopbackBehavior:
    """Loopback addresses blocked by default."""

    def test_ipv4_loopback_blocked(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("127.0.0.1"),
        ), pytest.raises(RuntimeBlockError):
            validate_network_target("localhost", [])

    def test_ipv6_loopback_blocked(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("::1"),
        ), pytest.raises(RuntimeBlockError):
            validate_network_target("localhost", [])


# ---------------------------------------------------------------------------
# Link-local (non-metadata)
# ---------------------------------------------------------------------------


class TestLinkLocalBehavior:
    """Non-metadata link-local addresses are blocked (always, by is_ip_allowed)."""

    def test_non_metadata_link_local_blocked(self) -> None:
        """A link-local address that is NOT a metadata endpoint is still blocked."""
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("169.254.1.2"),
        ), pytest.raises(RuntimeBlockError):
            validate_network_target("link-local.test", [_net("169.254.0.0/16")])


# ---------------------------------------------------------------------------
# Public IPs
# ---------------------------------------------------------------------------


class TestPublicIPAllowed:
    """Public IP addresses must be allowed through."""

    def test_public_ipv4_allowed(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("8.8.8.8"),
        ):
            validate_network_target("dns.google", [])

    def test_public_ipv6_allowed(self) -> None:
        with patch(
            "toolwright.core.network_safety.resolved_ips",
            _mock_resolved_ips("2606:4700::1111"),
        ):
            validate_network_target("cloudflare.com", [])


# ---------------------------------------------------------------------------
# URL scheme validation
# ---------------------------------------------------------------------------


class TestURLSchemeValidation:
    """http and https allowed; everything else blocked."""

    def test_http_allowed(self) -> None:
        validate_url_scheme("http://example.com/path")

    def test_https_allowed(self) -> None:
        validate_url_scheme("https://example.com/path")

    def test_ftp_blocked(self) -> None:
        with pytest.raises(RuntimeBlockError):
            validate_url_scheme("ftp://example.com/file")

    def test_file_blocked(self) -> None:
        with pytest.raises(RuntimeBlockError):
            validate_url_scheme("file:///etc/passwd")

    def test_gopher_blocked(self) -> None:
        with pytest.raises(RuntimeBlockError):
            validate_url_scheme("gopher://example.com/")

    def test_empty_scheme_blocked(self) -> None:
        with pytest.raises(RuntimeBlockError):
            validate_url_scheme("example.com/path")
