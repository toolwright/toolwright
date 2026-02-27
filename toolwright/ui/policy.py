"""TUI interaction policy: when to show interactive prompts.

should_interact() rules (checked in order):
1. Explicit force parameter → honour it.
2. Machine-output mode → False.
3. Known CI env vars → False.
4. TERM=dumb → False.
5. stdin is not a TTY → False (prevents Prompt.ask hang on piped stdin).
6. stderr is not a TTY (Rich detection) → False.
7. All pass → True.

resolve_ui_mode() rules:
1. input_stream is not None → "plain" (test injection).
2. CASK_UI=plain → "plain".
3. CASK_UI=fancy or auto/unset → terminal reality check:
   - prompt-toolkit not importable → "plain"
   - stdin not TTY → "plain"
   - stderr not terminal → "plain" (prompt-toolkit renders to stderr)
   - TERM=dumb → "plain"
   - CI env vars → "plain"
   - All pass → "fancy"
"""

from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from typing import Literal, TextIO

from rich.console import Console

_CI_ENV_VARS = frozenset({
    "CI",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "JENKINS_URL",
    "TF_BUILD",
    "BUILDKITE",
    "CIRCLECI",
    "TRAVIS",
    "CASK_NON_INTERACTIVE",
})


def should_interact(
    *,
    force: bool | None = None,
    machine_output: bool = False,
) -> bool:
    """Return True if the current session should use interactive prompts."""
    if force is not None:
        return force

    if machine_output:
        return False

    for var in _CI_ENV_VARS:
        if os.environ.get(var):
            return False

    if os.environ.get("TERM") == "dumb":
        return False

    if not _stdin_is_tty():
        return False

    return _stderr_is_terminal()


@lru_cache(maxsize=1)
def _stdin_is_tty() -> bool:
    """Check whether stdin is a real TTY."""
    return sys.stdin.isatty()


@lru_cache(maxsize=1)
def _stderr_is_terminal() -> bool:
    """Use Rich Console to detect stderr terminal capability."""
    c = Console(stderr=True)
    return c.is_terminal


@lru_cache(maxsize=1)
def _stdout_is_tty() -> bool:
    """Check whether stdout is a real TTY."""
    return sys.stdout.isatty()


@lru_cache(maxsize=1)
def _has_prompt_toolkit() -> bool:
    """Return True when prompt_toolkit is importable."""
    try:
        spec = importlib.util.find_spec("prompt_toolkit")
    except (ImportError, ValueError):
        return False
    return spec is not None


def _terminal_supports_fancy() -> bool:
    """Return True when the terminal can support fancy (arrow-key) prompts.

    Checks: prompt-toolkit available, stdin TTY, stderr is terminal,
    TERM not dumb, not in CI.

    Note: we check stderr (not stdout) because prompt-toolkit renders
    entirely to stderr via ``create_output(stdout=sys.stderr)``.
    stdout may be piped without affecting interactive prompts.
    """
    if not _has_prompt_toolkit():
        return False
    if not _stdin_is_tty():
        return False
    if not _stderr_is_terminal():
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return all(not os.environ.get(var) for var in _CI_ENV_VARS)


def resolve_ui_mode(
    *,
    input_stream: TextIO | None = None,
) -> Literal["plain", "fancy"]:
    """Determine whether to use fancy (arrow-key) or plain (numbered) prompts.

    Resolution:
    1. input_stream provided (test injection) → "plain"
    2. CASK_UI=plain → "plain"
    3. CASK_UI=fancy → "fancy" only if terminal supports it, else "plain"
    4. CASK_UI=auto or unset → auto-detect via terminal reality checks
    """
    if input_stream is not None:
        return "plain"

    ui_env = os.environ.get("CASK_UI", "auto").lower().strip()

    if ui_env == "plain":
        return "plain"

    # Both "fancy" and "auto" go through terminal reality checks
    if _terminal_supports_fancy():
        return "fancy"

    return "plain"
