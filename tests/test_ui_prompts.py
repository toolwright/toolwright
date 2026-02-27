"""Tests for toolwright.ui.prompts — prompt primitives with injectable input_stream."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from toolwright.ui.prompts import (
    confirm,
    confirm_typed,
    input_path,
    input_text,
    select_many,
    select_one,
)

# Use a Console that writes to a StringIO so we don't spam test output.
_test_console = Console(file=StringIO(), force_terminal=False)


class TestSelectOne:
    """Numbered menu selection."""

    def test_returns_first_choice(self) -> None:
        result = select_one(
            ["alpha", "beta", "gamma"],
            input_stream=StringIO("1\n"),
            console=_test_console,
        )
        assert result == "alpha"

    def test_returns_last_choice(self) -> None:
        result = select_one(
            ["alpha", "beta", "gamma"],
            input_stream=StringIO("3\n"),
            console=_test_console,
        )
        assert result == "gamma"

    def test_rejects_invalid_then_accepts_valid(self) -> None:
        # First "abc" is invalid, then "2" is valid
        result = select_one(
            ["alpha", "beta"],
            input_stream=StringIO("abc\n2\n"),
            console=_test_console,
        )
        assert result == "beta"

    def test_rejects_out_of_range_then_accepts_valid(self) -> None:
        result = select_one(
            ["alpha", "beta"],
            input_stream=StringIO("5\n1\n"),
            console=_test_console,
        )
        assert result == "alpha"

    def test_raises_on_eof(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            select_one(
                ["alpha", "beta"],
                input_stream=StringIO(""),
                console=_test_console,
            )

    def test_uses_custom_labels(self) -> None:
        # Labels are for display only; returned value is from choices
        result = select_one(
            ["a", "b"],
            labels=["Apple", "Banana"],
            input_stream=StringIO("2\n"),
            console=_test_console,
        )
        assert result == "b"


class TestSelectMany:
    """Multi-select with comma separation, 'all', and 'none'."""

    def test_all_shortcut(self) -> None:
        result = select_many(
            ["a", "b", "c"],
            input_stream=StringIO("all\n"),
            console=_test_console,
        )
        assert result == ["a", "b", "c"]

    def test_none_shortcut(self) -> None:
        result = select_many(
            ["a", "b", "c"],
            input_stream=StringIO("none\n"),
            console=_test_console,
        )
        assert result == []

    def test_comma_separated(self) -> None:
        result = select_many(
            ["a", "b", "c"],
            input_stream=StringIO("1,3\n"),
            console=_test_console,
        )
        assert result == ["a", "c"]

    def test_default_all_on_empty(self) -> None:
        result = select_many(
            ["a", "b"],
            default_all=True,
            input_stream=StringIO("\n"),
            console=_test_console,
        )
        assert result == ["a", "b"]

    def test_deduplicates(self) -> None:
        result = select_many(
            ["a", "b"],
            input_stream=StringIO("1,1\n"),
            console=_test_console,
        )
        assert result == ["a"]

    def test_rejects_out_of_range(self) -> None:
        # "5" is out of range, then "1" is valid
        result = select_many(
            ["a", "b"],
            input_stream=StringIO("5\n1\n"),
            console=_test_console,
        )
        assert result == ["a"]


class TestConfirm:
    """Yes/no confirmation."""

    def test_default_no_on_empty_input(self) -> None:
        assert confirm("Continue?", input_stream=StringIO("\n"), console=_test_console) is False

    def test_default_yes_on_empty_input(self) -> None:
        assert (
            confirm(
                "Continue?",
                default=True,
                input_stream=StringIO("\n"),
                console=_test_console,
            )
            is True
        )

    def test_y_returns_true(self) -> None:
        assert confirm("Continue?", input_stream=StringIO("y\n"), console=_test_console) is True

    def test_yes_returns_true(self) -> None:
        assert confirm("Continue?", input_stream=StringIO("yes\n"), console=_test_console) is True

    def test_n_returns_false(self) -> None:
        assert confirm("Continue?", input_stream=StringIO("n\n"), console=_test_console) is False

    def test_raises_on_eof(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            confirm("Continue?", input_stream=StringIO(""), console=_test_console)


class TestConfirmTyped:
    """Typed confirmation for risky actions."""

    def test_exact_match_returns_true(self) -> None:
        assert (
            confirm_typed(
                "Are you sure?",
                input_stream=StringIO("APPROVE\n"),
                console=_test_console,
            )
            is True
        )

    def test_wrong_text_returns_false(self) -> None:
        assert (
            confirm_typed(
                "Are you sure?",
                input_stream=StringIO("approve\n"),
                console=_test_console,
            )
            is False
        )

    def test_custom_required_text(self) -> None:
        assert (
            confirm_typed(
                "Are you sure?",
                required_text="DELETE",
                input_stream=StringIO("DELETE\n"),
                console=_test_console,
            )
            is True
        )

    def test_empty_returns_false(self) -> None:
        assert (
            confirm_typed(
                "Are you sure?",
                input_stream=StringIO("\n"),
                console=_test_console,
            )
            is False
        )

    def test_raises_on_eof(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            confirm_typed("Confirm?", input_stream=StringIO(""), console=_test_console)


class TestInputText:
    """Text input with optional default."""

    def test_returns_typed_text(self) -> None:
        assert (
            input_text("Name", input_stream=StringIO("Alice\n"), console=_test_console) == "Alice"
        )

    def test_returns_default_on_empty(self) -> None:
        assert (
            input_text(
                "Name",
                default="Bob",
                input_stream=StringIO("\n"),
                console=_test_console,
            )
            == "Bob"
        )

    def test_returns_empty_when_no_default(self) -> None:
        assert input_text("Name", input_stream=StringIO("\n"), console=_test_console) == ""

    def test_raises_on_eof(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            input_text("Name", input_stream=StringIO(""), console=_test_console)


class TestInputPath:
    """Path input with validation."""

    def test_returns_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = input_path(
            "File",
            input_stream=StringIO(f"{f}\n"),
            console=_test_console,
        )
        assert result == f.resolve()

    def test_rejects_nonexistent_then_accepts_existing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.txt"
        existing = tmp_path / "ok.txt"
        existing.write_text("hello")
        result = input_path(
            "File",
            input_stream=StringIO(f"{missing}\n{existing}\n"),
            console=_test_console,
        )
        assert result == existing.resolve()

    def test_rejects_file_when_dir_only(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        d = tmp_path / "mydir"
        d.mkdir()
        result = input_path(
            "Directory",
            file_okay=False,
            input_stream=StringIO(f"{f}\n{d}\n"),
            console=_test_console,
        )
        assert result == d.resolve()

    def test_rejects_dir_when_file_only(self, tmp_path: Path) -> None:
        d = tmp_path / "mydir"
        d.mkdir()
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = input_path(
            "File",
            dir_okay=False,
            input_stream=StringIO(f"{d}\n{f}\n"),
            console=_test_console,
        )
        assert result == f.resolve()

    def test_allows_nonexistent_when_must_exist_false(self, tmp_path: Path) -> None:
        target = tmp_path / "new_file.txt"
        result = input_path(
            "File",
            must_exist=False,
            input_stream=StringIO(f"{target}\n"),
            console=_test_console,
        )
        assert result == target.resolve()

    def test_raises_on_eof(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            input_path("File", input_stream=StringIO(""), console=_test_console)
