"""Tests for the prompt_action() single-letter action prompt."""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from toolwright.ui.prompts import _format_action_hint, prompt_action


class TestFormatActionHint:
    """Tests for _format_action_hint helper."""

    def test_basic_hint(self) -> None:
        result = _format_action_hint({"a": "approve", "b": "block"})
        assert "[a]" in result
        assert "[b]" in result
        assert "pprove" in result
        assert "lock" in result

    def test_key_not_matching_label(self) -> None:
        result = _format_action_hint({"y": "why"})
        assert "[y]" in result
        assert "why" in result


class TestPromptAction:
    """Tests for prompt_action() with readline fallback (input_stream)."""

    def test_valid_key_returned(self) -> None:
        stream = io.StringIO("a\n")
        result = prompt_action(
            {"a": "approve", "b": "block", "s": "skip"},
            input_stream=stream,
            console=Console(file=io.StringIO(), force_terminal=False),
        )
        assert result == "a"

    def test_second_valid_key(self) -> None:
        stream = io.StringIO("b\n")
        result = prompt_action(
            {"a": "approve", "b": "block", "s": "skip"},
            input_stream=stream,
            console=Console(file=io.StringIO(), force_terminal=False),
        )
        assert result == "b"

    def test_case_insensitive(self) -> None:
        stream = io.StringIO("A\n")
        result = prompt_action(
            {"a": "approve", "b": "block"},
            input_stream=stream,
            console=Console(file=io.StringIO(), force_terminal=False),
        )
        assert result == "a"

    def test_invalid_then_valid(self) -> None:
        stream = io.StringIO("x\na\n")
        result = prompt_action(
            {"a": "approve", "b": "block"},
            input_stream=stream,
            console=Console(file=io.StringIO(), force_terminal=False),
        )
        assert result == "a"

    def test_eof_raises_keyboard_interrupt(self) -> None:
        stream = io.StringIO("")
        with pytest.raises(KeyboardInterrupt):
            prompt_action(
                {"a": "approve", "b": "block"},
                input_stream=stream,
                console=Console(file=io.StringIO(), force_terminal=False),
            )

    def test_question_mark_key(self) -> None:
        stream = io.StringIO("?\n")
        result = prompt_action(
            {"a": "approve", "?": "help"},
            input_stream=stream,
            console=Console(file=io.StringIO(), force_terminal=False),
        )
        assert result == "?"

    def test_with_prompt_text(self) -> None:
        out = io.StringIO()
        stream = io.StringIO("a\n")
        prompt_action(
            {"a": "approve"},
            prompt="Choose action",
            input_stream=stream,
            console=Console(file=out, force_terminal=False),
        )
        output = out.getvalue()
        assert "Choose action" in output

    def test_takes_first_char_of_input(self) -> None:
        stream = io.StringIO("approve\n")
        result = prompt_action(
            {"a": "approve", "b": "block"},
            input_stream=stream,
            console=Console(file=io.StringIO(), force_terminal=False),
        )
        assert result == "a"

    def test_all_gate_review_actions(self) -> None:
        """Verify all gate review action keys work."""
        actions = {
            "a": "approve",
            "b": "block",
            "s": "skip",
            "d": "diff",
            "y": "why",
            "p": "policy",
            "?": "help",
        }
        for key in actions:
            stream = io.StringIO(f"{key}\n")
            result = prompt_action(
                actions,
                input_stream=stream,
                console=Console(file=io.StringIO(), force_terminal=False),
            )
            assert result == key, f"Expected {key!r}, got {result!r}"
