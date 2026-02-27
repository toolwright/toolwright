"""Normalized Playwright dependency/runtime error handling for CLI commands."""

from __future__ import annotations

import sys
import traceback

import click

PLAYWRIGHT_MISSING_ERROR = 'Error: Playwright not installed. Install with: pip install "toolwright[playwright]"'
PLAYWRIGHT_BROWSERS_MISSING_ERROR = (
    "Error: Playwright browsers not installed. Run: playwright install chromium"
)


def classify_playwright_error(exc: BaseException) -> str:
    """Classify a Playwright-related failure.

    Returns one of: missing_package, missing_browsers, other.
    """
    if isinstance(exc, ImportError):
        return "missing_package"

    message = str(exc).lower()
    if "executable doesn't exist" in message:
        return "missing_browsers"
    if "playwright install chromium" in message:
        return "missing_browsers"
    if "playwright install" in message and "browser" in message:
        return "missing_browsers"
    return "other"


def emit_playwright_missing_package() -> None:
    """Emit exact one-line package missing guidance."""
    click.echo(PLAYWRIGHT_MISSING_ERROR, err=True)


def emit_playwright_missing_browsers() -> None:
    """Emit exact one-line browser missing guidance."""
    click.echo(PLAYWRIGHT_BROWSERS_MISSING_ERROR, err=True)


def emit_playwright_error(exc: BaseException, *, verbose: bool, operation: str) -> None:
    """Emit normalized Playwright error output for CLI flows."""
    kind = classify_playwright_error(exc)
    if kind == "missing_package":
        emit_playwright_missing_package()
        return
    if kind == "missing_browsers":
        emit_playwright_missing_browsers()
        return

    click.echo(f"Error during {operation}: {exc}", err=True)
    if verbose:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
