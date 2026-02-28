"""Shared network safety functions for SSRF prevention.

Both the HTTP proxy gateway (``cli/enforce.py``) and the MCP stdio server
(``mcp/server.py``) delegate to these functions so that IP validation, host
normalization, and scheme checks behave identically regardless of the runtime
surface.

Design principles:
- **Fail-closed**: if DNS returns multiple A/AAAA records and *any* resolved
  IP is disallowed, the entire target is blocked.
- **IP-literal fast path**: raw IP addresses skip DNS resolution entirely,
  avoiding DNS-rebinding edge cases.
- **Consistent normalization**: both sides of every allowlist comparison are
  lowercased, port-stripped, bracket-stripped, and trailing-dot-stripped.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from toolwright.models.decision import ReasonCode

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class RuntimeBlockError(Exception):
    """Execution blocked by runtime network safety checks."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


# ---------------------------------------------------------------------------
# Host normalization
# ---------------------------------------------------------------------------


def normalize_host_for_allowlist(value: str) -> str:
    """Normalize a host string for allowlist comparison.

    * Lowercases
    * Strips trailing dot (DNS FQDN form)
    * Strips IPv6 brackets (``[::1]`` → ``::1``)
    * Strips port (``host:443`` → ``host``, ``[::1]:443`` → ``::1``)
    """
    raw = value.strip().lower().rstrip(".")
    if not raw:
        return ""

    # Bracketed IPv6: [::1]:8443 or [::1]
    if raw.startswith("["):
        closing = raw.find("]")
        if closing > 0:
            return raw[1:closing]
        return raw

    # host:port — only when there is exactly one colon (avoid splitting IPv6).
    if raw.count(":") == 1:
        host, port = raw.rsplit(":", 1)
        if port.isdigit():
            return host

    return raw


def host_matches_allowlist(host: str, allowed_hosts: set[str]) -> bool:
    """Check whether *host* matches any entry in *allowed_hosts*.

    Both the candidate and each pattern are normalized before comparison.
    Wildcard patterns like ``*.example.com`` match one level of subdomain.
    """
    normalized_host = normalize_host_for_allowlist(host)
    for raw_pattern in allowed_hosts:
        pattern = normalize_host_for_allowlist(raw_pattern)
        if not pattern:
            continue
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if not suffix:
                continue
            if (
                normalized_host.endswith(f".{suffix}")
                and normalized_host.count(".") == suffix.count(".") + 1
            ):
                return True
            continue
        if normalized_host == pattern:
            return True
    return False


# ---------------------------------------------------------------------------
# Metadata endpoints (unconditionally blocked)
# ---------------------------------------------------------------------------

_METADATA_ENDPOINTS: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS IMDSv1/v2, GCP, Azure
        "169.254.170.2",  # AWS ECS task metadata
        "fd00:ec2::254",  # AWS IPv6 metadata
    }
)

# ---------------------------------------------------------------------------
# IP validation
# ---------------------------------------------------------------------------


def resolved_ips(
    host: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve *host* to a list of IP addresses.

    If *host* is already an IP literal (v4 or v6) it is returned directly
    without touching DNS.
    """
    normalized = normalize_host_for_allowlist(host)

    # Fast path: IP literal → skip DNS entirely.
    try:
        return [ipaddress.ip_address(normalized)]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(normalized, None)
    except OSError as exc:
        raise RuntimeBlockError(
            ReasonCode.DENIED_HOST_RESOLUTION_FAILED,
            f"Failed to resolve host '{host}': {exc}",
        ) from exc

    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        addr = info[4][0]
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue

    if not ips:
        raise RuntimeBlockError(
            ReasonCode.DENIED_HOST_RESOLUTION_FAILED,
            f"No valid IPs resolved for host '{host}'",
        )
    return ips


def is_ip_allowed(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allow_private_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """Fail-closed IP policy.

    * **Always block**: unspecified, multicast, link-local.
    * **Block loopback** unless an entry in *allow_private_networks* covers it.
    * **Block private** unless an entry in *allow_private_networks* covers it.
    * **Allow public**.
    """
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        return False

    if ip.is_loopback:
        return any(ip in network for network in allow_private_networks)

    if ip.is_private:
        return any(ip in network for network in allow_private_networks)

    return True


def validate_network_target(
    host: str,
    allow_private_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> None:
    """Resolve *host* and validate **all** resulting IPs.

    Fail-closed: if *any* resolved IP is disallowed the entire target is
    blocked.  Cloud metadata endpoints (``169.254.169.254``, ``169.254.170.2``,
    ``fd00:ec2::254``) are hard-blocked regardless of the allowlist.
    """
    ips = resolved_ips(host)
    for ip in ips:
        # Hard-block cloud metadata endpoints -- not overridable by allowlist.
        if str(ip) in _METADATA_ENDPOINTS:
            raise RuntimeBlockError(
                ReasonCode.DENIED_HOST_RESOLUTION_FAILED,
                f"Resolved host '{host}' to cloud metadata endpoint {ip}",
            )
        if not is_ip_allowed(ip, allow_private_networks):
            raise RuntimeBlockError(
                ReasonCode.DENIED_HOST_RESOLUTION_FAILED,
                f"Resolved host '{host}' to blocked address {ip}",
            )


def validate_url_scheme(url: str) -> None:
    """Only allow ``http`` and ``https`` URL schemes."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise RuntimeBlockError(
            ReasonCode.DENIED_SCHEME_NOT_ALLOWED,
            f"Unsupported URL scheme '{scheme or '<empty>'}' for runtime request",
        )
