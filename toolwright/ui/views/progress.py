"""Cancel-safe progress display for long-running Toolwright operations.

One implementation, three modes:
- **Spinner**: indeterminate (e.g., "Capturing browser traffic...")
- **Step**: n-of-m (e.g., "Compiling [2/5] Normalizing endpoints...")
- **Feed**: reserved for future live-discovery display

Cancel safety
-------------
On Ctrl-C the progress display is cleaned up and a ``ToolwrightCancelled``
exception is raised.  The top-level Click command catches it, prints
"Aborted." to stderr, and exits with code 130.

Callers should use transactional writes (write to temp dir, then
atomically rename on success) so that cancellation never leaves
partial state.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from toolwright.ui.console import err_console
from toolwright.ui.context import ToolwrightCancelled


class ToolwrightProgress:
    """Wrapper around Rich Progress with cancel-safe semantics.

    Use via the ``toolwright_progress`` context manager.
    """

    def __init__(
        self,
        description: str,
        steps: list[str] | None,
        console: Console,
    ) -> None:
        self._description = description
        self._steps = steps
        self._console = console
        self._current_step = 0
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def _build_progress(self) -> Progress:
        """Build the appropriate Rich Progress bar."""
        if self._steps:
            # Step mode: [spinner] description [bar] M/N elapsed
            return Progress(
                SpinnerColumn(),
                TextColumn("[bold]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=self._console,
                transient=True,
            )
        # Spinner mode: [spinner] description elapsed
        return Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            TimeElapsedColumn(),
            console=self._console,
            transient=True,
        )

    def start(self) -> None:
        """Start the progress display."""
        self._progress = self._build_progress()
        total = len(self._steps) if self._steps else None
        self._progress.start()
        desc = self._step_description()
        self._task_id = self._progress.add_task(desc, total=total)

    def stop(self) -> None:
        """Stop the progress display cleanly."""
        if self._progress:
            self._progress.stop()
            self._progress = None

    def advance(self, label: str | None = None) -> None:
        """Advance to the next step.

        In step mode, increments the progress bar.
        In spinner mode, updates the description text.
        """
        if not self._progress or self._task_id is None:
            return

        if self._steps:
            self._current_step += 1
            desc = label or self._step_description()
            self._progress.update(self._task_id, advance=1, description=desc)
        elif label:
            self._progress.update(self._task_id, description=label)

    def update_description(self, text: str) -> None:
        """Update the status text without advancing."""
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, description=text)

    def _step_description(self) -> str:
        """Build description string for current step."""
        if self._steps and self._current_step < len(self._steps):
            return f"{self._description} — {self._steps[self._current_step]}"
        return self._description


@contextmanager
def toolwright_progress(
    description: str,
    steps: list[str] | None = None,
    *,
    console: Console | None = None,
) -> Generator[ToolwrightProgress, None, None]:
    """Cancel-safe progress context manager.

    Usage::

        with toolwright_progress("Compiling", ["Parse", "Normalize", "Generate"]) as p:
            do_parse()
            p.advance("Normalize")
            do_normalize()
            p.advance("Generate")
            do_generate()

    On Ctrl-C: cleans up the progress display and raises ``ToolwrightCancelled``.
    """
    con = console or err_console
    prog = ToolwrightProgress(description, steps, con)
    prog.start()
    try:
        yield prog
    except KeyboardInterrupt:
        prog.stop()
        con.print("[warning]Aborted.[/warning]")
        raise ToolwrightCancelled() from None
    else:
        prog.stop()
