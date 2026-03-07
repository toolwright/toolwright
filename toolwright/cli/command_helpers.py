"""Shared helpers for top-level CLI command registration."""

from __future__ import annotations

from pathlib import Path

import click

from toolwright.utils.state import confirmation_store_path, resolve_root


def cli_root(ctx: click.Context) -> Path:
    """Return the active toolwright root from context."""
    if ctx.obj:
        return Path(ctx.obj.get("root", resolve_root()))
    return resolve_root()


def cli_root_str(ctx: click.Context) -> str:
    """Return the active toolwright root as a string."""
    return str(cli_root(ctx))


def default_root_path(ctx: click.Context, *parts: str) -> Path:
    """Resolve a path beneath the active toolwright root."""
    return cli_root(ctx).joinpath(*parts)


def resolve_confirmation_store(ctx: click.Context, store_path: str | None) -> str:
    """Resolve the confirmation store path from context or explicit override."""
    return store_path or str(confirmation_store_path(cli_root(ctx)))
