"""Tests for the interactive repair flow (5-phase lifecycle)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from toolwright.ui.console import TOOLWRIGHT_THEME
from toolwright.ui.ops import PreflightCheck, PreflightResult


@pytest.fixture
def mock_console() -> Console:
    return Console(file=StringIO(), force_terminal=False, theme=TOOLWRIGHT_THEME)


def _preflight(*checks: tuple[str, bool, str]) -> PreflightResult:
    """Create a PreflightResult from (name, passed, detail) tuples."""
    if not checks:
        checks = (("test", True, "ok"),)
    pf_checks = [PreflightCheck(name=n, passed=p, detail=d) for n, p, d in checks]
    return PreflightResult(checks=pf_checks)


class TestRepairFlowDiagnosis:
    """repair_flow() runs preflight and diagnosis phases."""

    def test_shows_diagnosis_heading(self, mock_console: Console) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight()),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", return_value=None),
            patch("toolwright.ui.flows.repair._has_pending_tools", return_value=False),
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Repair" in output

    def test_shows_all_healthy_when_no_failures(self, mock_console: Console) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight(
                ("tools.json", True, "/path/tools.json"),
                ("lockfile", True, "/path/lockfile"),
            )),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", return_value=None),
            patch("toolwright.ui.flows.repair._has_pending_tools", return_value=False),
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Preflight passed" in output

    def test_classifies_missing_artifacts(self, mock_console: Console) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight(
                ("tools.json", False, "tools.json missing: /p/tools.json"),
                ("lockfile", True, "/path/lockfile"),
            )),
            # Quit on preflight failure
            patch("toolwright.ui.flows.repair.prompt_action", return_value="q"),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "missing" in output.lower()

    def test_classifies_digest_mismatch(self, mock_console: Console) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight(
                ("tools.json", True, "/p/tools.json"),
                ("artifacts digest", False, "lockfile artifacts digest mismatch; re-run toolwright gate sync"),
            )),
            patch("toolwright.ui.flows.repair.prompt_action", return_value="q"),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "toolwright gate sync" in output


class TestRepairFlowSuggestedFixes:
    """repair_flow() suggests specific fix commands on preflight failure."""

    def test_suggests_gate_sync_for_missing_lockfile(self, mock_console: Console) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight(
                ("lockfile", False, "missing; run toolwright gate sync"),
            )),
            patch("toolwright.ui.flows.repair.prompt_action", return_value="q"),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "toolwright gate sync" in output

    def test_suggests_recapture_for_missing_tools(self, mock_console: Console) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight(
                ("tools.json", False, "tools.json missing: /p/tools.json"),
            )),
            patch("toolwright.ui.flows.repair.prompt_action", return_value="q"),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "toolwright mint" in output

    def test_suggests_docker_for_missing_docker(self, mock_console: Console) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight(
                ("docker", False, "docker not available; install Docker or use --runtime local"),
            )),
            patch("toolwright.ui.flows.repair.prompt_action", return_value="q"),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "docker" in output.lower() or "--runtime local" in output


class TestRepairFlowPrompts:
    """repair_flow() prompts for toolpack when not provided."""

    def test_prompts_for_toolpack_when_missing(
        self, tmp_path: Path, mock_console: Console
    ) -> None:
        from toolwright.ui.flows.repair import repair_flow

        tp = tmp_path / "toolpacks" / "api"
        tp.mkdir(parents=True)
        (tp / "toolpack.yaml").write_text("name: api")

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight()),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", return_value=None),
            patch("toolwright.ui.flows.repair._has_pending_tools", return_value=False),
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            repair_flow(root=tmp_path)

    def test_shows_error_when_no_toolpacks(
        self, tmp_path: Path, mock_console: Console
    ) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with patch("toolwright.ui.flows.repair.err_console", mock_console):
            repair_flow(root=tmp_path)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "No toolpacks found" in output


class TestRepairFlowJumpToGate:
    """repair_flow() offers to jump to gate review when pending tools found."""

    def test_offers_gate_review_on_pending(self, mock_console: Console) -> None:
        from toolwright.ui.flows.repair import repair_flow

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight(
                ("lockfile", True, "/path/lockfile"),
            )),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", return_value=None),
            patch("toolwright.ui.flows.repair._has_pending_tools", return_value=True),
            # "Jump to gate review?" -> False
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "pending" in output.lower() or "Pending" in output


class TestRepairFlowRegistration:
    """Repair flow is accessible and registered."""

    def test_repair_flow_importable(self) -> None:
        from toolwright.ui.flows.repair import repair_flow

        assert callable(repair_flow)

    def test_repair_flow_registered_in_interactive_commands(self) -> None:
        from toolwright.ui.flows import INTERACTIVE_COMMANDS

        assert "repair" in INTERACTIVE_COMMANDS

    def test_repair_flow_accepts_interactive_flow_kwargs(self) -> None:
        """repair_flow accepts ctx and missing_param for InteractiveFlow protocol."""
        from toolwright.ui.flows.repair import repair_flow

        mock_con = Console(file=StringIO(), force_terminal=False, theme=TOOLWRIGHT_THEME)

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_con),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight()),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", return_value=None),
            patch("toolwright.ui.flows.repair._has_pending_tools", return_value=False),
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            # Should not raise TypeError for extra kwargs
            repair_flow(
                toolpack_path="/some/toolpack.yaml",
                ctx=None,
                missing_param="toolpack",
            )


class TestRepairFlowEngineIntegration:
    """repair_flow() integrates with RepairEngine for deep diagnosis."""

    def test_engine_diagnosis_always_runs(self, mock_console: Console) -> None:
        """Engine diagnosis runs automatically after preflight (no prompt)."""
        from toolwright.ui.flows.repair import repair_flow

        engine_mock = MagicMock(return_value=None)

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight()),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", engine_mock),
            patch("toolwright.ui.flows.repair._has_pending_tools", return_value=False),
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            repair_flow(toolpack_path="/some/toolpack.yaml", root=Path(".toolwright"))

        engine_mock.assert_called_once_with("/some/toolpack.yaml", mock_console)

    def test_engine_shows_no_issues_message(self, mock_console: Console) -> None:
        """Shows 'No issues found' when engine report has 0 items."""
        from toolwright.models.repair import (
            RedactionSummary,
            RepairDiagnosis,
            RepairPatchPlan,
            RepairReport,
            VerifySnapshot,
        )
        from toolwright.ui.flows.repair import repair_flow

        empty_report = RepairReport(
            toolpack_id="test",
            toolpack_path="/test/toolpack.yaml",
            diagnosis=RepairDiagnosis(
                total_issues=0,
                by_severity={},
                by_source={},
                clusters={},
                context_files_used=[],
                items=[],
            ),
            patch_plan=RepairPatchPlan(
                total_patches=0,
                safe_count=0,
                approval_required_count=0,
                manual_count=0,
                patches=[],
                commands_sh="",
            ),
            verify_before=VerifySnapshot(verify_status="pass", summary={}),
            redaction_summary=RedactionSummary(redacted_field_count=0, redacted_keys=[]),
            exit_code=0,
        )

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight()),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", return_value=empty_report),
            patch("toolwright.ui.flows.repair._has_pending_tools", return_value=False),
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            repair_flow(toolpack_path="/test/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "No issues found" in output

    def test_engine_shows_diagnosis_items(self, mock_console: Console) -> None:
        """_run_engine_diagnosis displays diagnosis items with severity."""
        from toolwright.models.decision import ReasonCode
        from toolwright.models.drift import DriftSeverity
        from toolwright.models.repair import (
            DiagnosisItem,
            DiagnosisSource,
            PatchAction,
            PatchItem,
            PatchKind,
            RedactionSummary,
            RepairDiagnosis,
            RepairPatchPlan,
            RepairReport,
            VerifySnapshot,
        )
        from toolwright.ui.flows.repair import _run_engine_diagnosis

        diag_item = DiagnosisItem(
            id="abc123",
            source=DiagnosisSource.AUDIT_LOG,
            severity=DriftSeverity.CRITICAL,
            reason_code=ReasonCode.DENIED_INTEGRITY_MISMATCH,
            tool_id="create_user",
            title="Denied: integrity mismatch",
            description="Tool 'create_user' denied due to integrity mismatch",
            cluster_key="tool:create_user",
        )

        patch_item = PatchItem(
            id="patch_1",
            diagnosis_id="abc123",
            kind=PatchKind.MANUAL,
            action=PatchAction.INVESTIGATE,
            args={"toolpack_path": "/test/toolpack.yaml"},
            cli_command="# Investigate: artifacts digest mismatch",
            title="Investigate integrity mismatch",
            description="Artifact digests do not match.",
            reason="Integrity mismatch requires manual investigation",
            risk_note="Potential security concern",
        )

        report = RepairReport(
            toolpack_id="test",
            toolpack_path="/test/toolpack.yaml",
            diagnosis=RepairDiagnosis(
                total_issues=1,
                by_severity={"critical": 1},
                by_source={"audit_log": 1},
                clusters={"tool:create_user": ["abc123"]},
                context_files_used=["/test/audit.log.jsonl"],
                items=[diag_item],
            ),
            patch_plan=RepairPatchPlan(
                total_patches=1,
                safe_count=0,
                approval_required_count=0,
                manual_count=1,
                patches=[patch_item],
                commands_sh="# Investigate: artifacts digest mismatch",
            ),
            verify_before=VerifySnapshot(verify_status="fail", summary={}),
            redaction_summary=RedactionSummary(redacted_field_count=0, redacted_keys=[]),
            exit_code=1,
        )

        with (
            patch("toolwright.core.repair.engine.RepairEngine") as MockEngine,
            patch("toolwright.core.toolpack.load_toolpack") as mock_load,
            patch("toolwright.core.toolpack.resolve_toolpack_paths") as mock_resolve,
        ):
            mock_load.return_value = MagicMock()
            mock_resolve.return_value = MagicMock()
            MockEngine.return_value.run.return_value = report

            _run_engine_diagnosis("/test/toolpack.yaml", mock_console)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "CRITICAL" in output
        assert "integrity mismatch" in output.lower()

    def test_engine_shows_patch_kind_labels(self, mock_console: Console) -> None:
        """repair_flow shows correct labels for each PatchKind in Phase 3."""
        from toolwright.models.decision import ReasonCode
        from toolwright.models.drift import DriftSeverity
        from toolwright.models.repair import (
            DiagnosisItem,
            DiagnosisSource,
            PatchAction,
            PatchItem,
            PatchKind,
            RedactionSummary,
            RepairDiagnosis,
            RepairPatchPlan,
            RepairReport,
            VerifySnapshot,
        )
        from toolwright.ui.flows.repair import repair_flow

        items = [
            DiagnosisItem(
                id="d1",
                source=DiagnosisSource.AUDIT_LOG,
                severity=DriftSeverity.ERROR,
                reason_code=ReasonCode.DENIED_NOT_APPROVED,
                tool_id="get_users",
                title="Denied: not approved",
                description="Tool 'get_users' not approved",
                cluster_key="tool:get_users",
            ),
        ]

        patches = [
            PatchItem(
                id="p1",
                diagnosis_id="d1",
                kind=PatchKind.APPROVAL_REQUIRED,
                action=PatchAction.GATE_ALLOW,
                args={},
                cli_command="toolwright gate allow --toolpack /test/tp.yaml",
                title="Approve tool: get_users",
                description="Tool 'get_users' not approved.",
                reason="denied_not_approved",
                risk_note="Grants tool execution permission",
            ),
        ]

        report = RepairReport(
            toolpack_id="test",
            toolpack_path="/test/toolpack.yaml",
            diagnosis=RepairDiagnosis(
                total_issues=1,
                by_severity={"error": 1},
                by_source={"audit_log": 1},
                clusters={"tool:get_users": ["d1"]},
                context_files_used=[],
                items=items,
            ),
            patch_plan=RepairPatchPlan(
                total_patches=1,
                safe_count=0,
                approval_required_count=1,
                manual_count=0,
                patches=patches,
                commands_sh="toolwright gate allow --toolpack /test/tp.yaml",
            ),
            verify_before=VerifySnapshot(verify_status="fail", summary={}),
            redaction_summary=RedactionSummary(redacted_field_count=0, redacted_keys=[]),
            exit_code=1,
        )

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight()),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", return_value=report),
            # Phase 4 & 5 confirms -> False
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            repair_flow(toolpack_path="/test/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Approval required" in output or "approval required" in output.lower()
        assert "toolwright gate allow" in output

    def test_engine_graceful_on_toolpack_load_error(self, mock_console: Console) -> None:
        """_run_engine_diagnosis shows warning when toolpack can't be loaded."""
        from toolwright.ui.flows.repair import _run_engine_diagnosis

        with patch("toolwright.core.toolpack.load_toolpack", side_effect=FileNotFoundError("not found")):
            _run_engine_diagnosis("/nonexistent/toolpack.yaml", mock_console)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Could not load toolpack" in output

    def test_engine_graceful_on_engine_error(self, mock_console: Console) -> None:
        """_run_engine_diagnosis shows warning when engine.run() fails."""
        from toolwright.ui.flows.repair import _run_engine_diagnosis

        with (
            patch("toolwright.core.repair.engine.RepairEngine") as MockEngine,
            patch("toolwright.core.toolpack.load_toolpack") as mock_load,
            patch("toolwright.core.toolpack.resolve_toolpack_paths") as mock_resolve,
        ):
            mock_load.return_value = MagicMock()
            mock_resolve.return_value = MagicMock()
            MockEngine.return_value.run.side_effect = RuntimeError("engine boom")

            _run_engine_diagnosis("/test/toolpack.yaml", mock_console)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Engine diagnosis failed" in output

    def test_engine_shows_context_files_used(self, mock_console: Console) -> None:
        """_run_engine_diagnosis lists context files when issues are found."""
        from toolwright.models.decision import ReasonCode
        from toolwright.models.drift import DriftSeverity
        from toolwright.models.repair import (
            DiagnosisItem,
            DiagnosisSource,
            RedactionSummary,
            RepairDiagnosis,
            RepairPatchPlan,
            RepairReport,
            VerifySnapshot,
        )
        from toolwright.ui.flows.repair import _run_engine_diagnosis

        report = RepairReport(
            toolpack_id="test",
            toolpack_path="/test/toolpack.yaml",
            diagnosis=RepairDiagnosis(
                total_issues=1,
                by_severity={"error": 1},
                by_source={"audit_log": 1},
                clusters={},
                context_files_used=["/test/audit.log.jsonl", "/test/drift.json"],
                items=[
                    DiagnosisItem(
                        id="d1",
                        source=DiagnosisSource.AUDIT_LOG,
                        severity=DriftSeverity.ERROR,
                        reason_code=ReasonCode.DENIED_NOT_APPROVED,
                        tool_id="x",
                        title="Denied",
                        description="desc",
                        cluster_key="tool:x",
                    ),
                ],
            ),
            patch_plan=RepairPatchPlan(
                total_patches=0,
                safe_count=0,
                approval_required_count=0,
                manual_count=0,
                patches=[],
                commands_sh="",
            ),
            verify_before=VerifySnapshot(verify_status="pass", summary={}),
            redaction_summary=RedactionSummary(redacted_field_count=0, redacted_keys=[]),
            exit_code=0,
        )

        with (
            patch("toolwright.core.repair.engine.RepairEngine") as MockEngine,
            patch("toolwright.core.toolpack.load_toolpack") as mock_load,
            patch("toolwright.core.toolpack.resolve_toolpack_paths") as mock_resolve,
        ):
            mock_load.return_value = MagicMock()
            mock_resolve.return_value = MagicMock()
            MockEngine.return_value.run.return_value = report

            _run_engine_diagnosis("/test/toolpack.yaml", mock_console)

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "audit.log.jsonl" in output
        assert "drift.json" in output

    def test_engine_shows_verify_phase(self, mock_console: Console) -> None:
        """repair_flow shows Phase 5 verify heading."""
        from toolwright.models.decision import ReasonCode
        from toolwright.models.drift import DriftSeverity
        from toolwright.models.repair import (
            DiagnosisItem,
            DiagnosisSource,
            PatchAction,
            PatchItem,
            PatchKind,
            RedactionSummary,
            RepairDiagnosis,
            RepairPatchPlan,
            RepairReport,
            VerifySnapshot,
        )
        from toolwright.ui.flows.repair import repair_flow

        report = RepairReport(
            toolpack_id="test",
            toolpack_path="/test/toolpack.yaml",
            diagnosis=RepairDiagnosis(
                total_issues=1,
                by_severity={"error": 1},
                by_source={"audit_log": 1},
                clusters={},
                context_files_used=[],
                items=[
                    DiagnosisItem(
                        id="d1",
                        source=DiagnosisSource.AUDIT_LOG,
                        severity=DriftSeverity.ERROR,
                        reason_code=ReasonCode.DENIED_NOT_APPROVED,
                        tool_id="x",
                        title="Denied",
                        description="desc",
                        cluster_key="tool:x",
                    ),
                ],
            ),
            patch_plan=RepairPatchPlan(
                total_patches=1,
                safe_count=0,
                approval_required_count=1,
                manual_count=0,
                patches=[
                    PatchItem(
                        id="p1",
                        diagnosis_id="d1",
                        kind=PatchKind.APPROVAL_REQUIRED,
                        action=PatchAction.GATE_ALLOW,
                        args={},
                        cli_command="toolwright gate allow",
                        title="Allow tool",
                        description="desc",
                        reason="r",
                    ),
                ],
                commands_sh="toolwright gate allow",
            ),
            verify_before=VerifySnapshot(verify_status="fail", summary={"mode": "contracts"}),
            redaction_summary=RedactionSummary(redacted_field_count=0, redacted_keys=[]),
            exit_code=1,
        )

        with (
            patch("toolwright.ui.flows.repair.err_console", mock_console),
            patch("toolwright.ui.flows.repair.run_repair_preflight", return_value=_preflight()),
            patch("toolwright.ui.flows.repair._run_engine_diagnosis", return_value=report),
            # All confirms -> False
            patch("toolwright.ui.flows.repair.confirm", return_value=False),
        ):
            repair_flow(toolpack_path="/test/toolpack.yaml", root=Path(".toolwright"))

        output = mock_console.file.getvalue()  # type: ignore[attr-defined]
        assert "Re-verify" in output or "toolwright verify" in output
