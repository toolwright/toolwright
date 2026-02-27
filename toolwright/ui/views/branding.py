"""Compact branding header for portal commands.

Shown only on "portal" commands: status, ship, demo, dashboard.
Never shown inside subcommands like gate allow or drift.

Maximum 2 lines.  ASCII-safe in plain mode via SymbolSet.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

from rich.console import Console
from rich.text import Text

from toolwright.ui.console import err_console, get_symbols


def _get_version() -> str:
    """Return the installed toolwright version, or 'dev' if not installed."""
    try:
        return _pkg_version("toolwright")
    except Exception:
        return "dev"


def render_rich_header(
    *,
    root: str | None = None,
    toolpack_id: str | None = None,
    console: Console | None = None,
) -> None:
    """Print the branded header to stderr.

    Example (Unicode mode):
        ◆ toolwright v0.2.0  ·  governed agent tools
        root: .toolwright  toolpack: stripe-api

    Example (ASCII mode):
        * toolwright v0.2.0  -  governed agent tools
        root: .toolwright  toolpack: stripe-api
    """
    con = console or err_console
    sym = get_symbols()
    ver = _get_version()

    sep = "\u00b7" if sym.dot != "*" else "-"  # · or -
    header = Text.from_markup(
        f"  [heading]{sym.dot} toolwright[/heading] v{ver}  {sep}  [muted]governed agent tools[/muted]"
    )
    con.print(header)

    if root or toolpack_id:
        parts: list[str] = []
        if root:
            parts.append(f"root: {root}")
        if toolpack_id:
            parts.append(f"toolpack: {toolpack_id}")
        con.print(f"  [muted]{'  '.join(parts)}[/muted]")

    con.print()  # blank line after header


def render_plain_header(
    *,
    root: str | None = None,
    toolpack_id: str | None = None,
) -> str:
    """Return the branded header as plain text (no ANSI codes)."""
    ver = _get_version()
    lines = [f"  * toolwright v{ver}  -  governed agent tools"]
    if root or toolpack_id:
        parts: list[str] = []
        if root:
            parts.append(f"root: {root}")
        if toolpack_id:
            parts.append(f"toolpack: {toolpack_id}")
        lines.append(f"  {'  '.join(parts)}")
    return "\n".join(lines)
