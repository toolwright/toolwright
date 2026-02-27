"""Tests for toolwright.ui.policy — should_interact() detection engine."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear lru_cache between tests so env/TTY mocking works correctly."""
    from toolwright.ui.policy import _stderr_is_terminal, _stdin_is_tty

    _stdin_is_tty.cache_clear()
    _stderr_is_terminal.cache_clear()
    yield
    _stdin_is_tty.cache_clear()
    _stderr_is_terminal.cache_clear()


def _interactive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up an environment where should_interact would return True."""
    # Clear all CI variables
    for var in (
        "CI",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "JENKINS_URL",
        "TF_BUILD",
        "BUILDKITE",
        "CIRCLECI",
        "TRAVIS",
        "TOOLWRIGHT_NON_INTERACTIVE",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("TERM", raising=False)


class TestForceParameter:
    """force= overrides all detection."""

    def test_force_true_returns_true(self) -> None:
        from toolwright.ui.policy import should_interact

        assert should_interact(force=True) is True

    def test_force_false_returns_false(self) -> None:
        from toolwright.ui.policy import should_interact

        assert should_interact(force=False) is False

    def test_force_true_ignores_machine_output(self) -> None:
        from toolwright.ui.policy import should_interact

        assert should_interact(force=True, machine_output=True) is True


class TestMachineOutput:
    """machine_output=True disables interactivity."""

    def test_returns_false_for_machine_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.ui.policy import should_interact

        _interactive_env(monkeypatch)
        assert should_interact(machine_output=True) is False


class TestCIDetection:
    """Each CI env var individually disables interactivity."""

    @pytest.mark.parametrize(
        "var",
        [
            "CI",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "JENKINS_URL",
            "TF_BUILD",
            "BUILDKITE",
            "CIRCLECI",
            "TRAVIS",
            "TOOLWRIGHT_NON_INTERACTIVE",
        ],
    )
    def test_returns_false_in_ci(self, var: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.ui.policy import should_interact

        _interactive_env(monkeypatch)
        monkeypatch.setenv(var, "1")
        assert should_interact() is False


class TestTerminal:
    """TERM=dumb disables interactivity."""

    def test_returns_false_for_dumb_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.ui.policy import should_interact

        _interactive_env(monkeypatch)
        monkeypatch.setenv("TERM", "dumb")
        assert should_interact() is False


class TestStdinTTY:
    """stdin not being a TTY disables interactivity (prevents Prompt.ask hang)."""

    def test_returns_false_when_stdin_not_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.ui.policy import should_interact

        _interactive_env(monkeypatch)
        with patch("toolwright.ui.policy.sys") as mock_sys:
            mock_sys.stdin.isatty.return_value = False
            assert should_interact() is False

    def test_returns_true_when_stdin_is_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.ui.policy import should_interact

        _interactive_env(monkeypatch)
        with (
            patch("toolwright.ui.policy.sys") as mock_sys,
            patch("toolwright.ui.policy._stderr_is_terminal", return_value=True),
        ):
            mock_sys.stdin.isatty.return_value = True
            assert should_interact() is True


class TestStderrTerminal:
    """stderr not being a terminal disables interactivity."""

    def test_returns_false_when_stderr_not_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.ui.policy import should_interact

        _interactive_env(monkeypatch)
        with (
            patch("toolwright.ui.policy._stdin_is_tty", return_value=True),
            patch("toolwright.ui.policy._stderr_is_terminal", return_value=False),
        ):
            assert should_interact() is False


class TestAllChecksPassing:
    """When all checks pass, should_interact returns True."""

    def test_returns_true_when_all_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from toolwright.ui.policy import should_interact

        _interactive_env(monkeypatch)
        with (
            patch("toolwright.ui.policy._stdin_is_tty", return_value=True),
            patch("toolwright.ui.policy._stderr_is_terminal", return_value=True),
        ):
            assert should_interact() is True
