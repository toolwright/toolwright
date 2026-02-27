"""Auth requirement detection — analyze captures to identify auth needs.

This module examines HTTP exchanges to detect:
1. Endpoints that require authentication (401/403 responses)
2. Login redirects (302 to known login paths)
3. Auth-related headers present in successful requests
4. Cookie-based session patterns
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from toolwright.models.capture import CaptureSession

# Common login/auth URL path patterns
LOGIN_PATH_PATTERNS = {
    "/login", "/signin", "/sign-in", "/auth", "/authenticate",
    "/oauth", "/sso", "/saml", "/cas", "/oidc",
    "/accounts/login", "/api/auth", "/api/login",
}

# Headers that indicate auth was used
AUTH_HEADERS = {
    "authorization", "x-api-key", "x-auth-token", "x-access-token",
    "x-csrf-token", "x-xsrf-token",
}

# Response headers that indicate session management
SESSION_HEADERS = {
    "set-cookie", "x-auth-token", "x-access-token",
}


class AuthRequirement:
    """Describes detected authentication requirements for an API."""

    def __init__(
        self,
        *,
        requires_auth: bool = False,
        auth_type: str = "unknown",
        evidence: list[str] | None = None,
        login_url: str | None = None,
        protected_endpoints: list[str] | None = None,
        suggestion: str = "",
    ) -> None:
        self.requires_auth = requires_auth
        self.auth_type = auth_type  # "cookie", "bearer", "api_key", "redirect", "unknown"
        self.evidence = evidence or []
        self.login_url = login_url
        self.protected_endpoints = protected_endpoints or []
        self.suggestion = suggestion

    def to_dict(self) -> dict[str, Any]:
        return {
            "requires_auth": self.requires_auth,
            "auth_type": self.auth_type,
            "evidence": self.evidence,
            "login_url": self.login_url,
            "protected_endpoints": self.protected_endpoints,
            "suggestion": self.suggestion,
        }


def detect_auth_requirements(session: CaptureSession) -> AuthRequirement:
    """Analyze a capture session to detect authentication requirements.

    Returns an AuthRequirement describing what auth the API needs.
    """
    denied_endpoints: list[str] = []
    login_redirects: list[str] = []
    auth_headers_seen: set[str] = set()
    cookie_auth = False
    login_url: str | None = None

    for exchange in session.exchanges:
        endpoint_ref = f"{exchange.method} {exchange.host}{exchange.path}"

        # Check for 401/403 responses (auth required)
        if exchange.response_status in (401, 403):
            denied_endpoints.append(endpoint_ref)

        # Check for login redirects
        if exchange.response_status in (301, 302, 303, 307, 308):
            location = _get_header(exchange.response_headers, "location")
            if location and _is_login_path(location):
                login_redirects.append(endpoint_ref)
                login_url = location

        # Check for auth headers in requests
        for header_name in exchange.request_headers:
            if header_name.lower() in AUTH_HEADERS:
                auth_headers_seen.add(header_name.lower())

        # Check for session cookies
        if _get_header(exchange.response_headers, "set-cookie"):
            cookie_auth = True

    # Build requirement
    evidence: list[str] = []
    auth_type = "unknown"
    requires_auth = False

    if denied_endpoints:
        requires_auth = True
        evidence.append(f"{len(denied_endpoints)} endpoint(s) returned 401/403")

    if login_redirects:
        requires_auth = True
        evidence.append(f"{len(login_redirects)} endpoint(s) redirected to login")

    if "authorization" in auth_headers_seen:
        auth_type = "bearer"
        evidence.append("Authorization header detected in requests")
    elif "x-api-key" in auth_headers_seen:
        auth_type = "api_key"
        evidence.append("API key header detected in requests")
    elif cookie_auth and (denied_endpoints or login_redirects):
        auth_type = "cookie"
        evidence.append("Cookie-based session management detected")
    elif requires_auth:
        auth_type = "redirect"

    # Build actionable suggestion
    suggestion = ""
    if requires_auth and not auth_headers_seen:
        suggestion = (
            "This API appears to require authentication. "
            "Run: toolwright auth login --profile <name> --url <login-url>\n"
            "Then: toolwright mint <url> --auth-profile <name> -a <host>"
        )
    elif requires_auth:
        suggestion = (
            "Auth headers detected. If capture was incomplete, "
            "use --auth-profile for authenticated capture."
        )

    return AuthRequirement(
        requires_auth=requires_auth,
        auth_type=auth_type,
        evidence=evidence,
        login_url=login_url,
        protected_endpoints=denied_endpoints[:10],  # cap at 10
        suggestion=suggestion,
    )


def check_session_auth_coverage(
    session: CaptureSession,
) -> dict[str, Any]:
    """Check what fraction of endpoints in a session have auth coverage.

    Returns stats about auth state across the capture.
    """
    total = len(session.exchanges)
    if total == 0:
        return {"total": 0, "authenticated": 0, "denied": 0, "coverage": 1.0}

    authenticated = 0
    denied = 0
    for ex in session.exchanges:
        if ex.response_status in (401, 403):
            denied += 1
        elif any(h.lower() in AUTH_HEADERS for h in ex.request_headers):
            authenticated += 1
        elif ex.response_status and 200 <= ex.response_status < 400:
            authenticated += 1  # Successful without explicit auth header = public

    coverage = (total - denied) / total if total > 0 else 0.0

    return {
        "total": total,
        "authenticated": authenticated,
        "denied": denied,
        "coverage": round(coverage, 3),
    }


def _get_header(headers: dict[str, str], name: str) -> str | None:
    """Case-insensitive header lookup."""
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def _is_login_path(url: str) -> bool:
    """Check if a URL looks like a login/auth redirect target."""
    try:
        parsed = urlparse(url)
        path = parsed.path.lower().rstrip("/")
    except Exception:
        return False

    return any(path == pattern or path.endswith(pattern) for pattern in LOGIN_PATH_PATTERNS)
