"""Shared Rich Console, theme, and SymbolSet for the Cask TUI.

All interactive output goes to stderr via ``err_console``.
Flows never write to stdout.

SymbolSet
---------
Chosen once at import time based on terminal capability.  Rich mode
uses Unicode glyphs when the terminal supports them; plain mode is
always ASCII-safe (no box drawing, no Unicode symbols).

Respects ``NO_COLOR`` and ``CLICOLOR=0`` environment variables.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache

from rich.console import Console
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

TOOLWRIGHT_THEME = Theme(
    {
        # Base
        "info": "cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        # Risk tiers
        "risk.low": "green",
        "risk.medium": "yellow",
        "risk.high": "red",
        "risk.critical": "bold red",
        # Headings and chrome
        "heading": "bold cyan",
        "muted": "dim",
        "command": "bold white on dark_blue",
        # Step tracker
        "step.done": "bold green",
        "step.active": "bold cyan",
        "step.pending": "dim",
        # Governance
        "seal": "bold green",
        "next": "bold cyan",
        # Drift categories
        "drift.breaking": "bold red",
        "drift.auth": "red",
        "drift.policy": "yellow",
        "drift.schema": "cyan",
        "drift.risk": "yellow",
        "drift.info": "dim",
        # Tool actions
        "tool.read": "green",
        "tool.write": "yellow",
        "tool.delete": "red",
        # Audit
        "audit.who": "bold",
        "audit.when": "dim",
    }
)

# All TUI chrome goes to stderr.
err_console = Console(stderr=True, theme=TOOLWRIGHT_THEME)


# ---------------------------------------------------------------------------
# SymbolSet — Unicode / ASCII glyph abstraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolSet:
    """Terminal-safe glyphs chosen once per session.

    Rich mode uses Unicode when the terminal supports it; plain mode
    uses ASCII-only characters suitable for pipes, CI, and dumb terminals.
    """

    ok: str
    fail: str
    pending: str
    warning: str
    arrow: str
    branch: str
    corner: str
    active: str
    dot: str


_UNICODE_SYMBOLS = SymbolSet(
    ok="\u2713",       # ✓
    fail="\u2717",     # ✗
    pending="\u25cb",  # ○
    warning="!",
    arrow="\u2192",    # →
    branch="\u251c\u2500",  # ├─
    corner="\u2514\u2500",  # └─
    active=">>",
    dot="\u25c6",      # ◆
)

_ASCII_SYMBOLS = SymbolSet(
    ok="[OK]",
    fail="[FAIL]",
    pending="[--]",
    warning="[WARN]",
    arrow="->",
    branch="|-",
    corner="\\-",
    active=">>",
    dot="*",
)


@lru_cache(maxsize=1)
def _detect_unicode_support() -> bool:
    """Heuristic: can the terminal render basic Unicode glyphs?"""
    # Respect explicit color/capability overrides.
    if os.environ.get("NO_COLOR") or os.environ.get("CLICOLOR") == "0":
        return False
    if os.environ.get("TERM") == "dumb":
        return False

    # Check stderr encoding (all our output goes there).
    encoding = getattr(sys.stderr, "encoding", None) or ""
    if encoding.lower().replace("-", "") in ("utf8", "utf16", "utf32"):
        return True

    # Fallback: if Rich thinks stderr is a real terminal, trust it.
    return err_console.is_terminal


def get_symbols() -> SymbolSet:
    """Return the session-appropriate symbol set.

    Called by views to get glyphs for status icons, tree drawing, etc.
    The result is cached for the lifetime of the process.
    """
    return _UNICODE_SYMBOLS if _detect_unicode_support() else _ASCII_SYMBOLS
