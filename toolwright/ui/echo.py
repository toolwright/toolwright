"""Command echo utilities for the Cask TUI.

Both functions output to stderr — never stdout.
"""

from __future__ import annotations

import shlex

from rich.console import Console

from toolwright.ui.console import err_console


def echo_plan(
    commands: list[list[str]],
    *,
    console: Console | None = None,
) -> None:
    """Display commands that WILL be run (before execution). Goes to stderr."""
    con = console or err_console
    if not commands:
        return
    con.print()
    con.print("[heading]Will run:[/heading]")
    for cmd in commands:
        con.print(f"  [command]{shlex.join(cmd)}[/command]")
    con.print()


def echo_summary(
    commands: list[list[str]],
    *,
    console: Console | None = None,
) -> None:
    """Display commands that WERE run (after execution). Goes to stderr."""
    con = console or err_console
    if not commands:
        return
    con.print()
    con.print("[heading]Ran:[/heading]")
    for cmd in commands:
        con.print(f"  [command]{shlex.join(cmd)}[/command]")
    con.print()
