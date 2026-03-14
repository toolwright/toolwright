"""Auth utilities -- shared host-to-env-var normalization."""

from __future__ import annotations

import re


def host_to_env_var(host: str) -> str:
    """Convert a hostname to the per-host env var name.

    api.stripe.com  ->  TOOLWRIGHT_AUTH_API_STRIPE_COM
    localhost:8080  ->  TOOLWRIGHT_AUTH_LOCALHOST_8080
    """
    normalized = re.sub(r"[^A-Za-z0-9]", "_", host).upper()
    return f"TOOLWRIGHT_AUTH_{normalized}"
