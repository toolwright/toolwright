"""Toolpack auto-resolution chain.

Resolution order:
    1. --toolpack flag (explicit, always wins)
    2. TOOLWRIGHT_TOOLPACK env var
    3. .toolwright/config.yaml -> default_toolpack (directory name)
    4. Auto-detect single toolpack in .toolwright/toolpacks/
    5. Error with actionable message
"""

from __future__ import annotations

import os
from pathlib import Path

import click
import yaml

from toolwright.utils.state import DEFAULT_ROOT


def resolve_toolpack_path(
    explicit: str | None = None,
    root: Path | None = None,
) -> Path:
    """Resolve toolpack path via: flag -> env var -> config -> auto-detect -> error."""
    # 1. Explicit flag
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p

        # Try as a bare name under .toolwright/toolpacks/{name}/toolpack.yaml
        resolved_root = root if root is not None else DEFAULT_ROOT
        name_path = resolved_root / "toolpacks" / explicit / "toolpack.yaml"
        if name_path.exists():
            return name_path

        raise FileNotFoundError(f"Toolpack not found: {p}")

    # 2. Env var
    env_val = os.environ.get("TOOLWRIGHT_TOOLPACK")
    if env_val:
        p = Path(env_val)
        if not p.exists():
            raise FileNotFoundError(
                f"TOOLWRIGHT_TOOLPACK points to missing file: {p}"
            )
        return p

    # 3. Config file — value is ALWAYS a directory name under toolpacks/
    resolved_root = root if root is not None else DEFAULT_ROOT
    config_path = resolved_root / "config.yaml"
    if config_path.exists():
        cfg = yaml.safe_load(config_path.read_text()) or {}
        default = cfg.get("default_toolpack")
        if default:
            p = resolved_root / "toolpacks" / default / "toolpack.yaml"
            if p.exists():
                return Path(p)

    # 4. Auto-detect single toolpack
    toolpacks_dir = resolved_root / "toolpacks"
    if toolpacks_dir.is_dir():
        matches = sorted(toolpacks_dir.glob("*/toolpack.yaml"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            lines = "\n".join(f"  --toolpack {m}" for m in matches)
            raise click.UsageError(
                f"Multiple toolpacks found. Specify one:\n"
                f"{lines}\n\n"
                f"Or set a default: toolwright use <name>"
            )

    # 5. Nothing found
    raise click.UsageError(
        "No toolpack found. Create one with:\n"
        "  toolwright create <recipe>          # e.g. github, stripe\n"
        "  toolwright create --spec <spec>     # from OpenAPI spec"
    )


def _host_to_slug(host: str) -> str:
    """Convert a hostname to a short human-friendly slug.

    api.stripe.com  ->  stripe
    dummyjson.com   ->  dummyjson
    localhost       ->  localhost
    """
    host = host.split(":")[0]
    parts = host.split(".")
    strip = {"api", "www", "rest", "v1", "v2", "com", "org", "net", "io", "dev", "co"}
    meaningful = [p for p in parts if p.lower() not in strip]
    return meaningful[0] if meaningful else parts[0]


def generate_toolpack_slug(
    *,
    name: str | None = None,
    allowed_hosts: list[str] | None = None,
    root: Path | None = None,
) -> str:
    """Generate a human-friendly toolpack directory name.

    Priority: user-provided name > host slug > 'toolpack'.
    Handles collisions: stripe, stripe-2, stripe-3, ...
    """
    import uuid

    # Determine base slug
    if name:
        slug = name
    elif allowed_hosts:
        slug = _host_to_slug(allowed_hosts[0])
    else:
        slug = "toolpack"

    # If no root, no collision check needed
    if root is None:
        return slug

    # Handle collisions
    toolpacks_dir = root / "toolpacks"
    if not toolpacks_dir.is_dir() or not (toolpacks_dir / slug).exists():
        return slug

    for i in range(2, 100):
        candidate = f"{slug}-{i}"
        if not (toolpacks_dir / candidate).exists():
            return candidate

    return f"{slug}-{uuid.uuid4().hex[:8]}"
