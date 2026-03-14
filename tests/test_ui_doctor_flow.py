"""Tests for the interactive doctor flow and the doctor.py refactored wrapper."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from toolwright.ui.runner import DoctorCheck, DoctorResult


@pytest.fixture
def mock_console() -> Console:
    """Console that writes to a StringIO buffer (not stderr)."""
    return Console(file=StringIO(), force_terminal=False)


class TestDoctorFlowPrompts:
    """doctor_flow() prompts for toolpack when not provided."""

    def test_prompts_for_toolpack_when_missing(
        self, tmp_path: Path, mock_console: Console
    ) -> None:
        """When toolpack_path is None and candidates exist, select_one is called."""
        from toolwright.ui.flows.doctor import doctor_flow

        # Create a mock toolpack
        tp = tmp_path / "toolpacks" / "my-api"
        tp.mkdir(parents=True)
        (tp / "toolpack.yaml").write_text("name: my-api")

        result = DoctorResult(
            checks=[DoctorCheck("test", True, "ok")],
            runtime_mode="local",
        )

        with (
            patch("toolwright.ui.flows.doctor.err_console", mock_console),
            patch("toolwright.ui.flows.doctor.run_doctor_checks", return_value=result),
            patch(
                "toolwright.ui.flows.doctor.confirm", return_value=True
            ),
        ):
            # Pass root=tmp_path so find_toolpacks finds our mock
            doctor_flow(root=tmp_path)

    def test_shows_error_when_no_toolpacks(
        self, tmp_path: Path, mock_console: Console
    ) -> None:
        """When no toolpacks found, shows error and returns."""
        from toolwright.ui.flows.doctor import doctor_flow

        with patch("toolwright.ui.flows.doctor.err_console", mock_console):
            doctor_flow(root=tmp_path)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "No toolpack found" in output

    def test_skips_when_user_declines_confirm(
        self, tmp_path: Path, mock_console: Console
    ) -> None:
        """When user says no to confirm, flow returns without running checks."""
        from toolwright.ui.flows.doctor import doctor_flow

        tp = tmp_path / "toolpacks" / "api"
        tp.mkdir(parents=True)
        (tp / "toolpack.yaml").write_text("name: api")

        with (
            patch("toolwright.ui.flows.doctor.err_console", mock_console),
            patch("toolwright.ui.flows.doctor.confirm", return_value=False),
            patch("toolwright.ui.flows.doctor.run_doctor_checks") as mock_run,
        ):
            doctor_flow(root=tmp_path)
            mock_run.assert_not_called()


class TestDoctorFlowDisplay:
    """doctor_flow() shows Rich checklist and correct messages."""

    def test_shows_success_when_all_pass(
        self, mock_console: Console
    ) -> None:
        from toolwright.ui.flows.doctor import doctor_flow

        result = DoctorResult(
            checks=[
                DoctorCheck("tools.json", True, "/path/tools.json"),
                DoctorCheck("lockfile", True, "/path/lockfile"),
            ],
            runtime_mode="local",
        )

        with (
            patch("toolwright.ui.flows.doctor.err_console", mock_console),
            patch("toolwright.ui.flows.doctor.run_doctor_checks", return_value=result),
            patch("toolwright.ui.flows.doctor.confirm", return_value=True),
        ):
            doctor_flow(toolpack_path="/some/path")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "All checks passed" in output

    def test_shows_failure_message(self, mock_console: Console) -> None:
        from toolwright.ui.flows.doctor import doctor_flow

        result = DoctorResult(
            checks=[
                DoctorCheck("tools.json", False, "missing: /path/tools.json"),
                DoctorCheck("lockfile", True, "/path/lockfile"),
            ],
            runtime_mode="local",
        )

        with (
            patch("toolwright.ui.flows.doctor.err_console", mock_console),
            patch("toolwright.ui.flows.doctor.run_doctor_checks", return_value=result),
            patch("toolwright.ui.flows.doctor.confirm", return_value=True),
        ):
            doctor_flow(toolpack_path="/some/path")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Some checks failed" in output


class TestDoctorFlowPlan:
    """doctor_flow() shows plan before executing."""

    def test_shows_plan_with_correct_command(self, mock_console: Console) -> None:
        from toolwright.ui.flows.doctor import doctor_flow

        result = DoctorResult(
            checks=[DoctorCheck("test", True, "ok")],
            runtime_mode="local",
        )

        with (
            patch("toolwright.ui.flows.doctor.err_console", mock_console),
            patch("toolwright.ui.flows.doctor.run_doctor_checks", return_value=result),
            patch("toolwright.ui.flows.doctor.confirm", return_value=True),
        ):
            doctor_flow(toolpack_path="/my/toolpack.yaml")

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Will run" in output
        assert "toolwright doctor --toolpack /my/toolpack.yaml" in output


class TestDoctorCLIRefactored:
    """The refactored run_doctor() in cli/doctor.py delegates to runner."""

    def test_passes_on_success(self) -> None:
        """run_doctor() does not sys.exit when all checks pass."""
        from toolwright.cli.doctor import run_doctor

        result = DoctorResult(
            checks=[DoctorCheck("test", True, "ok")],
            runtime_mode="local",
        )

        with patch("toolwright.cli.doctor.run_doctor_checks", return_value=result):
            # Should not raise
            run_doctor(toolpack_path="/path", runtime="auto", verbose=False)

    def test_exits_on_failure(self) -> None:
        """run_doctor() calls sys.exit(1) when checks fail."""
        from toolwright.cli.doctor import run_doctor

        result = DoctorResult(
            checks=[DoctorCheck("tools.json", False, "missing")],
            runtime_mode="local",
        )

        with (
            patch("toolwright.cli.doctor.run_doctor_checks", return_value=result),
            pytest.raises(SystemExit, match="1"),
        ):
            run_doctor(toolpack_path="/path", runtime="auto", verbose=False)

    def test_exits_on_load_error(self) -> None:
        """run_doctor() exits on FileNotFoundError from runner."""
        from toolwright.cli.doctor import run_doctor

        with (
            patch(
                "toolwright.cli.doctor.run_doctor_checks",
                side_effect=FileNotFoundError("no such toolpack"),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            run_doctor(toolpack_path="/bad", runtime="auto", verbose=False)


class TestFlowRegistration:
    """Doctor flow is registered in INTERACTIVE_COMMANDS."""

    def test_doctor_registered(self) -> None:
        from toolwright.ui.flows import INTERACTIVE_COMMANDS

        assert "doctor" in INTERACTIVE_COMMANDS

    def test_config_registered(self) -> None:
        from toolwright.ui.flows import INTERACTIVE_COMMANDS

        assert "config" in INTERACTIVE_COMMANDS
