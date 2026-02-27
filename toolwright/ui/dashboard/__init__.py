"""Optional Textual dashboard for Cask.

Requires ``toolwright[tui]`` (textual).  If Textual is not installed,
``toolwright dashboard`` prints an install hint and falls back to
``toolwright status`` output.
"""

from __future__ import annotations


def has_textual() -> bool:
    """Check if Textual is importable."""
    try:
        import textual  # noqa: F401

        return True
    except ImportError:
        return False


def run_dashboard(toolpack_path: str, root: str = ".toolwright") -> None:
    """Launch the Textual dashboard, or fall back gracefully.

    If Textual is not installed, prints an install hint and shows
    ``toolwright status`` output instead.
    """
    if not has_textual():
        _fallback(toolpack_path, root)
        return

    from toolwright.ui.dashboard.app import CaskDashboardApp

    app = CaskDashboardApp(toolpack_path=toolpack_path, root=root)
    app.run()


def _fallback(toolpack_path: str, root: str) -> None:  # noqa: ARG001
    """Show install hint and fall back to toolwright status."""
    import sys

    from toolwright.ui.console import err_console

    con = err_console
    con.print()
    con.print("[warning]Textual is not installed.[/warning]")
    con.print(f'  Install with: [command]{sys.executable} -m pip install "toolwright[tui]"[/command]')
    con.print()
    con.print("[heading]Falling back to toolwright status:[/heading]")
    con.print()

    try:
        from toolwright.ui.ops import get_status
        from toolwright.ui.views.status import render_plain, render_rich

        model = get_status(toolpack_path)
        if con.is_terminal:
            con.print(render_rich(model))
        else:
            con.print(render_plain(model))
    except Exception as exc:
        con.print(f"[error]Could not load status: {exc}[/error]")
        con.print(f"  Run: [command]toolwright status --toolpack {toolpack_path}[/command]")
