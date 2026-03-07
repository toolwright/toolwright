"""Header parsing utilities for --extra-header CLI flag."""

from __future__ import annotations

import click


def parse_extra_headers(raw: tuple[str, ...]) -> dict[str, str]:
    """Parse raw 'Name: value' strings into a header dict.

    Duplicates: last value wins (same as curl).
    """
    headers: dict[str, str] = {}
    for entry in raw:
        if ":" not in entry:
            raise click.BadParameter(
                f"Invalid header format: {entry!r} (expected 'Name: value')",
                param_hint="--extra-header",
            )
        name, _, value = entry.partition(":")
        name = name.strip()
        value = value.strip()
        if not name:
            raise click.BadParameter(
                f"Empty header name in: {entry!r}",
                param_hint="--extra-header",
            )
        headers[name] = value
    return headers
