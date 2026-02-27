"""CDN/analytics path blocklist for capture filtering.

Blocks infrastructure paths that never carry real app data.
The list is intentionally tight — only CDN/analytics/tracking
prefixes that are universally non-app-data.
"""

from __future__ import annotations

BLOCKED_PATH_PREFIXES: tuple[str, ...] = (
    "/cdn-cgi/",
    "/beacon",
    "/collect",
    "/pixel",
    "/_analytics",
    "/gtm.js",
)


def is_blocked_path(path: str) -> bool:
    """Check if a path matches any blocked prefix.

    Returns True if the path starts with a known CDN/analytics prefix.
    """
    if not path or path == "/":
        return False
    return any(path.startswith(prefix) for prefix in BLOCKED_PATH_PREFIXES)
