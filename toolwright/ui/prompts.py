"""Reusable prompt primitives for the Cask TUI.

Every function accepts an optional *console* (for output) and *input_stream*
(for deterministic test input) so that tests never need to monkeypatch stdin.

Selection prompts (select_one, select_many) dispatch to either:
- "fancy" mode: arrow-key navigation via prompt-toolkit (when available + TTY)
- "plain" mode: numbered readline input (always works, test-friendly)

The dispatch is controlled by resolve_ui_mode() from toolwright.ui.policy.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from rich.console import Console

from toolwright.ui.console import err_console
from toolwright.ui.policy import resolve_ui_mode

# ---------------------------------------------------------------------------
# select_one: dispatcher + plain + fancy
# ---------------------------------------------------------------------------


def select_one(
    choices: list[str],
    *,
    labels: list[str] | None = None,
    prompt: str = "Select",
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> str:
    """Display a menu and return the selected choice value.

    Routes to arrow-key (fancy) or numbered-input (plain) based on
    terminal capabilities and CASK_UI env var.

    Raises ``KeyboardInterrupt`` on EOF / cancel.
    """
    mode = resolve_ui_mode(input_stream=input_stream)
    if mode == "fancy":
        return _select_one_fancy(
            choices, labels=labels, prompt=prompt, console=console
        )
    return _select_one_plain(
        choices,
        labels=labels,
        prompt=prompt,
        console=console,
        input_stream=input_stream,
    )


def _select_one_plain(
    choices: list[str],
    *,
    labels: list[str] | None = None,
    prompt: str = "Select",
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> str:
    """Numbered menu selection (plain mode)."""
    con = console or err_console
    stream = input_stream or sys.stdin
    display = labels if labels else choices

    con.print()
    for i, label in enumerate(display, 1):
        con.print(f"  [bold]{i}[/bold]) {label}")
    con.print()

    while True:
        con.print(f"{prompt} [muted](1-{len(choices)})[/muted]: ", end="")
        line = stream.readline()
        if not line:
            raise KeyboardInterrupt
        raw = line.strip()
        if not raw:
            continue
        try:
            idx = int(raw)
        except ValueError:
            con.print(f"[warning]Enter a number between 1 and {len(choices)}[/warning]")
            continue
        if 1 <= idx <= len(choices):
            return choices[idx - 1]
        con.print(f"[warning]Enter a number between 1 and {len(choices)}[/warning]")


def _select_one_fancy(
    choices: list[str],
    *,
    labels: list[str] | None = None,
    prompt: str = "Select",
    console: Console | None = None,  # noqa: ARG001
) -> str:
    """Arrow-key single-select using prompt-toolkit.

    Renders inline to stderr. Returns the selected choice value.
    Raises ``KeyboardInterrupt`` on Ctrl-C.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import FormattedTextControl, Layout, Window
    from prompt_toolkit.output import create_output

    display = labels if labels else choices
    selected_index = 0

    # --- key bindings ---
    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _move_up(_event: object) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(display)

    @kb.add("down")
    @kb.add("j")
    def _move_down(_event: object) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(display)

    @kb.add("enter")
    def _accept(_event: object) -> None:
        app = _event.app
        app.exit(result=selected_index)

    @kb.add("c-c")
    def _cancel(_event: object) -> None:
        app = _event.app
        app.exit(result=None)

    # --- layout ---
    def _get_text() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        fragments.append(("bold", f" {prompt}"))
        fragments.append(("", "  (\u2191/\u2193 move, Enter select)\n"))
        for i, label in enumerate(display):
            if i == selected_index:
                fragments.append(("bold fg:cyan", f"  \u276f {label}\n"))
            else:
                fragments.append(("", f"    {label}\n"))
        return fragments

    control = FormattedTextControl(_get_text)
    window = Window(content=control, always_hide_cursor=True)
    layout = Layout(window)

    # --- print header via Rich to stderr, then run app ---
    output = create_output(stdout=sys.stderr)

    app: Application[int | None] = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        output=output,
    )

    result = app.run()

    if result is None:
        raise KeyboardInterrupt

    return choices[result]


# ---------------------------------------------------------------------------
# select_many: dispatcher + plain + fancy
# ---------------------------------------------------------------------------


def select_many(
    choices: list[str],
    *,
    labels: list[str] | None = None,
    prompt: str = "Select (comma-separated numbers, 'all', or 'none')",
    default_all: bool = False,
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> list[str]:
    """Display a checklist and return selected choice values.

    Routes to arrow-key (fancy) or numbered-input (plain) based on
    terminal capabilities and CASK_UI env var.

    Raises ``KeyboardInterrupt`` on EOF / cancel.
    """
    mode = resolve_ui_mode(input_stream=input_stream)
    if mode == "fancy":
        return _select_many_fancy(
            choices,
            labels=labels,
            prompt=prompt,
            default_all=default_all,
            console=console,
        )
    return _select_many_plain(
        choices,
        labels=labels,
        prompt=prompt,
        default_all=default_all,
        console=console,
        input_stream=input_stream,
    )


def _select_many_plain(
    choices: list[str],
    *,
    labels: list[str] | None = None,
    prompt: str = "Select (comma-separated numbers, 'all', or 'none')",
    default_all: bool = False,
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> list[str]:
    """Multi-select with comma separation, 'all', and 'none' (plain mode)."""
    con = console or err_console
    stream = input_stream or sys.stdin
    display = labels if labels else choices

    con.print()
    for i, label in enumerate(display, 1):
        con.print(f"  [bold]{i}[/bold]) {label}")
    con.print()

    hint = " [muted](default: all)[/muted]" if default_all else ""
    while True:
        con.print(f"{prompt}{hint}: ", end="")
        line = stream.readline()
        if not line:
            raise KeyboardInterrupt
        raw = line.strip().lower()

        if not raw and default_all:
            return list(choices)
        if raw == "all":
            return list(choices)
        if raw == "none":
            return []

        selected: list[str] = []
        valid = True
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                idx = int(part)
            except ValueError:
                con.print(f"[warning]Invalid input: {part!r}[/warning]")
                valid = False
                break
            if 1 <= idx <= len(choices):
                if choices[idx - 1] not in selected:
                    selected.append(choices[idx - 1])
            else:
                con.print(
                    f"[warning]{idx} is out of range (1-{len(choices)})[/warning]"
                )
                valid = False
                break
        if valid and selected:
            return selected
        if valid:
            con.print("[warning]No items selected[/warning]")


def _select_many_fancy(
    choices: list[str],
    *,
    labels: list[str] | None = None,
    prompt: str = "Select",
    default_all: bool = False,  # noqa: ARG001
    console: Console | None = None,  # noqa: ARG001
) -> list[str]:
    """Arrow-key multi-select using prompt-toolkit.

    Renders inline to stderr. Space toggles, 'a' toggles all, Enter confirms.
    Returns selected choice values in original order.
    Raises ``KeyboardInterrupt`` on Ctrl-C.

    Note: ``default_all`` is accepted for API parity with ``_select_many_plain``
    but has no effect in fancy mode — the user explicitly toggles items.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import FormattedTextControl, Layout, Window
    from prompt_toolkit.output import create_output

    display = labels if labels else choices
    cursor = 0
    checked: set[int] = set()

    # --- key bindings ---
    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _move_up(_event: object) -> None:
        nonlocal cursor
        cursor = (cursor - 1) % len(display)

    @kb.add("down")
    @kb.add("j")
    def _move_down(_event: object) -> None:
        nonlocal cursor
        cursor = (cursor + 1) % len(display)

    @kb.add("space")
    def _toggle(_event: object) -> None:
        if cursor in checked:
            checked.discard(cursor)
        else:
            checked.add(cursor)

    @kb.add("a")
    def _toggle_all(_event: object) -> None:
        if len(checked) == len(choices):
            checked.clear()
        else:
            checked.update(range(len(choices)))

    @kb.add("enter")
    def _accept(_event: object) -> None:
        app = _event.app
        # Return indices in original order
        app.exit(result=sorted(checked))

    @kb.add("c-c")
    def _cancel(_event: object) -> None:
        app = _event.app
        app.exit(result=None)

    # --- layout ---
    def _get_text() -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        fragments.append(("bold", f" {prompt}"))
        fragments.append(("", "  (\u2191/\u2193 move, Space toggle, a=all, Enter confirm)\n"))
        for i, label in enumerate(display):
            mark = "\u2713" if i in checked else " "
            if i == cursor:
                fragments.append(("bold fg:cyan", f"  \u276f [{mark}] {label}\n"))
            else:
                fragments.append(("", f"    [{mark}] {label}\n"))
        return fragments

    control = FormattedTextControl(_get_text)
    window = Window(content=control, always_hide_cursor=True)
    layout = Layout(window)

    output = create_output(stdout=sys.stderr)

    app: Application[list[int] | None] = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        output=output,
    )

    result = app.run()

    if result is None:
        raise KeyboardInterrupt

    # Return choices at the selected indices, in original order
    return [choices[i] for i in sorted(result)]


# ---------------------------------------------------------------------------
# Other prompts (no dispatch needed — always plain)
# ---------------------------------------------------------------------------


def confirm(
    message: str,
    *,
    default: bool = False,
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> bool:
    """Rich-based yes/no confirmation."""
    con = console or err_console
    stream = input_stream or sys.stdin

    hint = "[Y/n]" if default else "[y/N]"
    con.print(f"{message} {hint} ", end="")
    line = stream.readline()
    if not line:
        raise KeyboardInterrupt
    raw = line.strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def confirm_typed(
    message: str,
    *,
    required_text: str = "APPROVE",
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> bool:
    """Require the user to type an exact string to confirm a risky action."""
    con = console or err_console
    stream = input_stream or sys.stdin

    con.print(f"{message} [warning](type {required_text} to confirm)[/warning]: ", end="")
    line = stream.readline()
    if not line:
        raise KeyboardInterrupt
    return line.strip() == required_text


def input_text(
    prompt: str,
    *,
    default: str = "",
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> str:
    """Prompt for text input with an optional default."""
    con = console or err_console
    stream = input_stream or sys.stdin

    suffix = f" [muted]({default})[/muted]" if default else ""
    con.print(f"{prompt}{suffix}: ", end="")
    line = stream.readline()
    if not line:
        raise KeyboardInterrupt
    raw = line.strip()
    return raw if raw else default


def input_path(
    prompt: str,
    *,
    must_exist: bool = True,
    file_okay: bool = True,
    dir_okay: bool = True,
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> Path:
    """Prompt for a file/directory path with validation."""
    con = console or err_console
    stream = input_stream or sys.stdin

    while True:
        con.print(f"{prompt}: ", end="")
        line = stream.readline()
        if not line:
            raise KeyboardInterrupt
        raw = line.strip()
        if not raw:
            con.print("[warning]Path cannot be empty[/warning]")
            continue

        p = Path(raw).expanduser().resolve()

        if must_exist and not p.exists():
            con.print(f"[warning]Path does not exist: {p}[/warning]")
            continue
        if p.exists():
            if p.is_file() and not file_okay:
                con.print("[warning]Expected a directory, got a file[/warning]")
                continue
            if p.is_dir() and not dir_okay:
                con.print("[warning]Expected a file, got a directory[/warning]")
                continue

        return p


# ---------------------------------------------------------------------------
# Single-letter action prompt
# ---------------------------------------------------------------------------


def _has_prompt_toolkit() -> bool:
    """Check if prompt-toolkit is available."""
    try:
        import prompt_toolkit  # noqa: F401
        return True
    except ImportError:
        return False


def _format_action_hint(actions: dict[str, str]) -> str:
    """Format action choices as keyboard hints.

    Given ``{"a": "approve", "b": "block", "s": "skip"}``, returns:
    ``[a]pprove  [b]lock  [s]kip``
    """
    parts: list[str] = []
    for key, label in actions.items():
        if label.lower().startswith(key.lower()):
            # Highlight the first letter: [a]pprove
            parts.append(f"[bold][{key}][/bold]{label[len(key):]}")
        else:
            # Key doesn't match label start: [y]why
            parts.append(f"[bold][{key}][/bold]{label}")
    return "  ".join(parts)


def prompt_action(
    actions: dict[str, str],
    *,
    prompt: str = "",
    console: Console | None = None,
    input_stream: TextIO | None = None,
) -> str:
    """Single-letter action selection.

    Parameters
    ----------
    actions:
        Mapping of single-character keys to labels.
        Example: ``{"a": "approve", "b": "block", "s": "skip"}``
    prompt:
        Optional leading text before the action hints.
    console:
        Rich Console for output (defaults to stderr console).
    input_stream:
        TextIO for deterministic testing. When provided, reads a full
        line and takes the first character.

    Returns
    -------
    The key string that was selected (e.g., ``"a"``).

    Uses prompt-toolkit for single-keypress input when available and
    running in a TTY. Falls back to readline otherwise.
    """
    con = console or err_console
    stream = input_stream or sys.stdin

    hint = _format_action_hint(actions)
    if prompt:
        con.print(f"\n  {prompt}")
    con.print(f"  {hint}: ", end="")

    valid_keys = {k.lower() for k in actions}

    # Try prompt-toolkit for instant single-keypress in TTY
    if input_stream is None and _has_prompt_toolkit() and sys.stdin.isatty():
        return _prompt_action_toolkit(valid_keys, con)

    # Readline fallback
    return _prompt_action_readline(valid_keys, con, stream)


def _prompt_action_toolkit(valid_keys: set[str], con: Console) -> str:
    """Single-keypress action prompt via prompt-toolkit."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    result: str | None = None
    bindings = KeyBindings()

    for key in valid_keys:
        @bindings.add(key)
        def _handler(event, k=key):  # noqa: B023
            nonlocal result
            result = k
            event.app.exit(result=k)

    @bindings.add(Keys.ControlC)
    def _cancel(event):
        event.app.exit(result=None)

    @bindings.add("?")
    def _help(event):
        # Treat ? same as pressing the key if it's in valid_keys
        if "?" in valid_keys:
            nonlocal result
            result = "?"
            event.app.exit(result="?")

    session: PromptSession[str] = PromptSession(key_bindings=bindings)
    try:
        chosen = session.prompt("")
    except (EOFError, KeyboardInterrupt):
        con.print()
        raise KeyboardInterrupt from None

    if chosen is None:
        con.print()
        raise KeyboardInterrupt

    con.print()  # newline after keypress
    return chosen


def _prompt_action_readline(
    valid_keys: set[str],
    con: Console,
    stream: TextIO,
) -> str:
    """Readline fallback for action prompt."""
    while True:
        line = stream.readline()
        if not line:
            raise KeyboardInterrupt
        raw = line.strip().lower()
        if raw and raw[0] in valid_keys:
            return raw[0]
        con.print(
            f"  [warning]Press one of: {', '.join(sorted(valid_keys))}[/warning]: ",
            end="",
        )
