"""FlowContext and shared exceptions for the Toolwright TUI narrative engine.

FlowContext is threaded through all interactive flows, carrying selected
state (toolpack, lockfile, etc.) and output preferences.  It is frozen
— flows that need to update it create a new instance via ``replace()``.

ToolwrightCancelled is raised by the progress system on Ctrl-C.  Top-level
Click commands catch it and exit with code 130.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class FlowContext:
    """Shared state passed through all TUI flows.

    This is the single source of truth for "where we are" in the
    narrative: which toolpack, which lockfile, what just happened,
    and what output mode we're in.
    """

    root: Path
    toolpack_path: Path | None = None
    toolpack_id: str | None = None
    toolpack_fingerprint: str | None = None
    lockfile_path: Path | None = None
    capture_id: str | None = None
    baseline_path: Path | None = None
    last_command: str | None = None
    last_result: Any | None = None
    output_mode: Literal["rich", "plain", "json"] = "rich"
    intent: str | None = None
    interactive: bool = True

    def replace(self, **changes: Any) -> FlowContext:
        """Return a new FlowContext with the given fields replaced."""
        return _dc_replace(self, **changes)


class ToolwrightCancelled(Exception):
    """Raised on Ctrl-C during progress.

    Caught by the top-level Click command handler which prints
    "Aborted." to stderr and exits with code 130.
    """
