"""Tests for RepairEngine — diagnosis, patch generation, severity, exit codes, redaction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from toolwright.models.decision import ReasonCode
from toolwright.models.drift import DriftSeverity, DriftType
from toolwright.models.repair import (
    DiagnosisSource,
    PatchAction,
    PatchKind,
)
from toolwright.models.verify import VerifyStatus

# ---------------------------------------------------------------------------
# Fixtures: synthetic context files
# ---------------------------------------------------------------------------

def _write_audit_log(path: Path, entries: list[dict[str, Any]]) -> Path:
    """Write synthetic audit.log.jsonl."""
    out = path / "audit.log.jsonl"
    with out.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    return out


def _deny_entry(
    reason_code: str,
    tool_id: str = "get_users",
    **extra: Any,
) -> dict[str, Any]:
    """Build a synthetic DENY audit entry."""
    return {
        "timestamp": "2026-02-20T00:00:00Z",
        "run_id": "test_run",
        "tool_id": tool_id,
        "scope_id": "test_scope",
        "decision": "deny",
        "reason_code": reason_code,
        "evidence_refs": [],
        "lockfile_digest": "abc123",
        "policy_digest": "def456",
        "extra": extra,
    }


def _allow_entry(tool_id: str = "get_users") -> dict[str, Any]:
    """Build a synthetic ALLOW audit entry."""
    return {
        "timestamp": "2026-02-20T00:00:00Z",
        "run_id": "test_run",
        "tool_id": tool_id,
        "scope_id": "test_scope",
        "decision": "allow",
        "reason_code": "allowed_policy",
        "evidence_refs": [],
        "lockfile_digest": "abc123",
        "policy_digest": "def456",
    }


def _write_drift_report(path: Path, drifts: list[dict[str, Any]]) -> Path:
    """Write synthetic drift.json."""
    report = {
        "id": "dr_test",
        "schema_version": "1.0",
        "generated_at": "2026-02-20T00:00:00Z",
        "total_drifts": len(drifts),
        "drifts": drifts,
    }
    out = path / "drift.json"
    out.write_text(json.dumps(report), encoding="utf-8")
    return out


def _write_verify_report(path: Path, sections: dict[str, Any]) -> Path:
    """Write synthetic verify report."""
    report = {
        "id": "vr_test",
        "schema_version": "1.0",
        "toolpack_id": "tp_test",
        **sections,
    }
    out = path / "verify_report.json"
    out.write_text(json.dumps(report), encoding="utf-8")
    return out


def _write_minimal_toolpack(path: Path) -> Path:
    """Write a minimal toolpack.yaml and supporting artifacts."""
    import yaml

    tp_dir = path / "toolpacks" / "tp_test"
    tp_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = tp_dir / "artifact"
    artifact_dir.mkdir(exist_ok=True)
    lockfile_dir = tp_dir / "lockfile"
    lockfile_dir.mkdir(exist_ok=True)

    # tools.json
    tools = {"actions": [{"name": "get_users", "method": "GET", "path": "/users"}]}
    (artifact_dir / "tools.json").write_text(json.dumps(tools))

    # toolsets.yaml
    (artifact_dir / "toolsets.yaml").write_text(
        yaml.safe_dump({"toolsets": [{"name": "default", "tools": ["get_users"]}]})
    )

    # policy.yaml
    (artifact_dir / "policy.yaml").write_text(
        yaml.safe_dump({"version": "1.0", "rules": []})
    )

    # baseline.json
    (artifact_dir / "baseline.json").write_text(json.dumps({"endpoints": []}))

    # contracts
    (artifact_dir / "contracts.yaml").write_text(
        yaml.safe_dump({"contracts": []})
    )

    # pending lockfile
    (lockfile_dir / "toolwright.lock.pending.yaml").write_text(
        yaml.safe_dump({"version": "1.0.0", "tools": {}})
    )

    # toolpack.yaml
    toolpack = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "toolpack_id": "tp_test",
        "created_at": "2026-02-20T00:00:00Z",
        "capture_id": "cap_test",
        "artifact_id": "art_test",
        "scope": "test",
        "allowed_hosts": ["api.example.com"],
        "origin": {"start_url": "https://api.example.com", "name": "Test"},
        "paths": {
            "tools": "artifact/tools.json",
            "toolsets": "artifact/toolsets.yaml",
            "policy": "artifact/policy.yaml",
            "baseline": "artifact/baseline.json",
            "contracts": "artifact/contracts.yaml",
            "lockfiles": {
                "pending": "lockfile/toolwright.lock.pending.yaml",
            },
        },
    }
    tp_file = tp_dir / "toolpack.yaml"
    tp_file.write_text(yaml.safe_dump(toolpack, sort_keys=False))
    return tp_file


def _make_engine(toolpack_path: Path):
    """Create a RepairEngine from a toolpack path."""
    from toolwright.core.repair.engine import RepairEngine
    from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

    toolpack = load_toolpack(toolpack_path)
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_path)
    return RepairEngine(
        toolpack=toolpack,
        toolpack_path=toolpack_path.resolve(),
        resolved=resolved,
    )


# ===========================================================================
# 1. Diagnosis parsing (10 tests)
# ===========================================================================


class TestDiagnosisParsing:
    """Tests for context file parsing and diagnosis generation."""

    def test_audit_log_deny_entries_diagnosed(self, tmp_path: Path) -> None:
        """DENY entries in audit.log.jsonl produce DiagnosisItems."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved", tool_id="get_users"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        assert report.diagnosis.total_issues >= 1
        item = report.diagnosis.items[0]
        assert item.source == DiagnosisSource.AUDIT_LOG
        assert item.reason_code == ReasonCode.DENIED_NOT_APPROVED

    def test_audit_log_allow_entries_ignored(self, tmp_path: Path) -> None:
        """ALLOW entries are skipped — only DENY produces diagnoses."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _allow_entry(tool_id="get_users"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        assert report.diagnosis.total_issues == 0

    def test_drift_breaking_diagnosed(self, tmp_path: Path) -> None:
        """Breaking drifts produce diagnoses."""
        tp = _write_minimal_toolpack(tmp_path)
        drift = _write_drift_report(tmp_path, [
            {
                "id": "d1",
                "type": "breaking",
                "severity": "critical",
                "endpoint_id": "get_users",
                "path": "/users",
                "method": "GET",
                "title": "Endpoint removed",
                "description": "/users no longer responds",
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[drift], auto_discover=False)

        assert report.diagnosis.total_issues >= 1
        item = report.diagnosis.items[0]
        assert item.source == DiagnosisSource.DRIFT_REPORT
        assert item.drift_type == DriftType.BREAKING

    def test_drift_additive_ignored(self, tmp_path: Path) -> None:
        """Additive drifts are not diagnosed (informational only)."""
        tp = _write_minimal_toolpack(tmp_path)
        drift = _write_drift_report(tmp_path, [
            {
                "id": "d1",
                "type": "additive",
                "severity": "info",
                "title": "New endpoint",
                "description": "New read-only endpoint",
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[drift], auto_discover=False)

        assert report.diagnosis.total_issues == 0

    def test_verify_fail_diagnosed(self, tmp_path: Path) -> None:
        """Failed verify sections produce diagnoses."""
        tp = _write_minimal_toolpack(tmp_path)
        vr = _write_verify_report(tmp_path, {
            "contracts": {"status": "fail", "assertion_results": []},
        })
        engine = _make_engine(tp)
        report = engine.run(context_paths=[vr], auto_discover=False)

        assert report.diagnosis.total_issues >= 1
        item = report.diagnosis.items[0]
        assert item.source == DiagnosisSource.VERIFY_REPORT
        assert item.verify_status == VerifyStatus.FAIL

    def test_verify_pass_ignored(self, tmp_path: Path) -> None:
        """Passing verify sections are not diagnosed."""
        tp = _write_minimal_toolpack(tmp_path)
        vr = _write_verify_report(tmp_path, {
            "contracts": {"status": "pass", "assertion_results": []},
        })
        engine = _make_engine(tp)
        report = engine.run(context_paths=[vr], auto_discover=False)

        assert report.diagnosis.total_issues == 0

    def test_deduplication(self, tmp_path: Path) -> None:
        """Same evidence from multiple paths is deduplicated."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved", tool_id="get_users"),
        ])
        engine = _make_engine(tp)
        # Pass the same file twice
        report = engine.run(context_paths=[audit, audit], auto_discover=False)

        assert report.diagnosis.total_issues == 1

    def test_severity_ordering(self, tmp_path: Path) -> None:
        """Diagnoses are sorted CRITICAL > ERROR > WARNING > INFO."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_redirect_not_allowlisted", tool_id="t1"),  # WARNING
            _deny_entry("denied_integrity_mismatch", tool_id="t2"),  # CRITICAL
            _deny_entry("denied_not_approved", tool_id="t3"),  # ERROR
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        severities = [item.severity for item in report.diagnosis.items]
        assert severities[0] == DriftSeverity.CRITICAL
        assert severities[1] == DriftSeverity.ERROR
        assert severities[2] == DriftSeverity.WARNING

    def test_clustering(self, tmp_path: Path) -> None:
        """Related issues share a cluster_key and are grouped."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved", tool_id="get_users"),
            _deny_entry("denied_policy", tool_id="get_users"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        # Both should be clustered under "tool:get_users"
        assert "tool:get_users" in report.diagnosis.clusters
        assert len(report.diagnosis.clusters["tool:get_users"]) == 2

    def test_context_files_used_tracked(self, tmp_path: Path) -> None:
        """Context files used are recorded in the diagnosis."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [_deny_entry("denied_policy")])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        assert str(audit) in report.diagnosis.context_files_used


# ===========================================================================
# 2. Patch generation (10 tests)
# ===========================================================================


class TestPatchGeneration:
    """Tests for diagnosis → patch mapping."""

    def test_denied_not_approved_is_approval_required(self, tmp_path: Path) -> None:
        """denied_not_approved → APPROVAL_REQUIRED, gate_allow action."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.APPROVAL_REQUIRED
        assert patch.action == PatchAction.GATE_ALLOW

    def test_denied_toolset_not_approved_is_approval_required(self, tmp_path: Path) -> None:
        """denied_toolset_not_approved → APPROVAL_REQUIRED."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_toolset_not_approved"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.APPROVAL_REQUIRED
        assert patch.action == PatchAction.GATE_ALLOW

    def test_integrity_mismatch_is_manual_investigate(self, tmp_path: Path) -> None:
        """denied_integrity_mismatch → MANUAL, investigate action."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_integrity_mismatch"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.MANUAL
        assert patch.action == PatchAction.INVESTIGATE
        assert "tamper" in patch.cli_command.lower() or "investigate" in patch.cli_command.lower()

    def test_denied_policy_is_approval_required(self, tmp_path: Path) -> None:
        """denied_policy → APPROVAL_REQUIRED, review_policy action."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_policy"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.APPROVAL_REQUIRED
        assert patch.action == PatchAction.REVIEW_POLICY

    def test_redirect_not_allowlisted_is_approval_required(self, tmp_path: Path) -> None:
        """denied_redirect_not_allowlisted → APPROVAL_REQUIRED, add_host action."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_redirect_not_allowlisted", host="cdn.example.com"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.APPROVAL_REQUIRED
        assert patch.action == PatchAction.ADD_HOST

    def test_signature_invalid_is_approval_required(self, tmp_path: Path) -> None:
        """denied_approval_signature_invalid → APPROVAL_REQUIRED, gate_reseal."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_approval_signature_invalid"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.APPROVAL_REQUIRED
        assert patch.action == PatchAction.GATE_RESEAL

    def test_breaking_drift_is_manual_remint(self, tmp_path: Path) -> None:
        """Breaking drift → MANUAL, re_mint action."""
        tp = _write_minimal_toolpack(tmp_path)
        drift = _write_drift_report(tmp_path, [
            {
                "id": "d1", "type": "breaking", "severity": "critical",
                "title": "Endpoint removed", "description": "Gone",
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[drift], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.MANUAL
        assert patch.action == PatchAction.RE_MINT

    def test_risk_drift_is_approval_required(self, tmp_path: Path) -> None:
        """Risk drift → APPROVAL_REQUIRED, gate_allow."""
        tp = _write_minimal_toolpack(tmp_path)
        drift = _write_drift_report(tmp_path, [
            {
                "id": "d1", "type": "risk", "severity": "warning",
                "title": "New write endpoint", "description": "POST /users added",
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[drift], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.APPROVAL_REQUIRED
        assert patch.action == PatchAction.GATE_ALLOW

    def test_verify_fail_is_safe_verify(self, tmp_path: Path) -> None:
        """Verify contracts fail → SAFE, verify_contracts action."""
        tp = _write_minimal_toolpack(tmp_path)
        vr = _write_verify_report(tmp_path, {
            "contracts": {"status": "fail", "assertion_results": []},
        })
        engine = _make_engine(tp)
        report = engine.run(context_paths=[vr], auto_discover=False)

        patch = report.patch_plan.patches[0]
        assert patch.kind == PatchKind.SAFE
        assert patch.action == PatchAction.VERIFY_CONTRACTS

    def test_commands_sh_aggregation(self, tmp_path: Path) -> None:
        """All patch commands are concatenated into commands_sh."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved", tool_id="t1"),
            _deny_entry("denied_policy", tool_id="t2"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        assert report.patch_plan.commands_sh  # non-empty
        assert "gate" in report.patch_plan.commands_sh.lower() or "review" in report.patch_plan.commands_sh.lower()


# ===========================================================================
# 3. Severity mapping (3 tests)
# ===========================================================================


class TestSeverityMapping:
    """Tests for deterministic severity mapping."""

    def test_integrity_mismatch_is_critical(self, tmp_path: Path) -> None:
        """denied_integrity_mismatch maps to CRITICAL."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_integrity_mismatch"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        assert report.diagnosis.items[0].severity == DriftSeverity.CRITICAL

    def test_denied_not_approved_is_error(self, tmp_path: Path) -> None:
        """denied_not_approved maps to ERROR."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        assert report.diagnosis.items[0].severity == DriftSeverity.ERROR

    def test_verify_fail_is_error_unknown_is_warning(self, tmp_path: Path) -> None:
        """Verify fail→ERROR, unknown→WARNING."""
        tp = _write_minimal_toolpack(tmp_path)
        vr = _write_verify_report(tmp_path, {
            "contracts": {"status": "fail", "assertion_results": []},
            "provenance": {"status": "unknown", "results": []},
        })
        engine = _make_engine(tp)
        report = engine.run(context_paths=[vr], auto_discover=False)

        # contracts fail → ERROR
        contracts_item = [i for i in report.diagnosis.items if "contracts" in i.title.lower()]
        assert contracts_item[0].severity == DriftSeverity.ERROR
        # provenance unknown → WARNING
        prov_item = [i for i in report.diagnosis.items if "provenance" in i.title.lower()]
        assert prov_item[0].severity == DriftSeverity.WARNING


# ===========================================================================
# 4. Exit codes (3 tests)
# ===========================================================================


class TestExitCodes:
    """Tests for exit code semantics."""

    def test_healthy_returns_0(self, tmp_path: Path) -> None:
        """No issues → exit code 0."""
        tp = _write_minimal_toolpack(tmp_path)
        engine = _make_engine(tp)
        report = engine.run(context_paths=[], auto_discover=False)

        assert report.exit_code == 0

    def test_issues_found_returns_1(self, tmp_path: Path) -> None:
        """Issues found → exit code 1."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        assert report.exit_code == 1

    def test_report_json_has_detailed_breakdown(self, tmp_path: Path) -> None:
        """repair.json includes safe/approval/manual counts."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved"),
            _deny_entry("denied_integrity_mismatch"),
        ])
        vr = _write_verify_report(tmp_path, {
            "contracts": {"status": "fail", "assertion_results": []},
        })
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit, vr], auto_discover=False)

        assert report.patch_plan.approval_required_count >= 1
        assert report.patch_plan.manual_count >= 1
        assert report.patch_plan.safe_count >= 1


# ===========================================================================
# 5. Schema version (1 test)
# ===========================================================================


class TestSchemaVersion:
    """Tests for schema versioning."""

    def test_repair_schema_version_present(self, tmp_path: Path) -> None:
        """RepairReport has repair_schema_version = '0.1'."""
        tp = _write_minimal_toolpack(tmp_path)
        engine = _make_engine(tp)
        report = engine.run(context_paths=[], auto_discover=False)

        assert report.repair_schema_version == "0.1"


# ===========================================================================
# 6. Verify snapshot (2 tests)
# ===========================================================================


class TestVerifySnapshot:
    """Tests for the Phase 3 artifact-only verify snapshot."""

    def test_verify_snapshot_runs_contracts(self, tmp_path: Path) -> None:
        """Verify snapshot runs contracts mode and returns status."""
        tp = _write_minimal_toolpack(tmp_path)
        engine = _make_engine(tp)
        report = engine.run(context_paths=[], auto_discover=False)

        # Should have a verify_before snapshot (any valid status; empty contracts may fail)
        assert report.verify_before is not None
        assert report.verify_before.verify_status in (
            VerifyStatus.PASS, VerifyStatus.FAIL, VerifyStatus.SKIPPED, VerifyStatus.UNKNOWN,
        )

    def test_verify_graceful_on_missing_artifacts(self, tmp_path: Path) -> None:
        """Returns skipped when tools.json doesn't exist."""
        import yaml

        # Create toolpack pointing to nonexistent artifacts
        tp_dir = tmp_path / "tp_missing"
        tp_dir.mkdir()
        toolpack = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "toolpack_id": "tp_missing",
            "created_at": "2026-02-20T00:00:00Z",
            "capture_id": "c", "artifact_id": "a",
            "scope": "test", "allowed_hosts": [],
            "origin": {"start_url": "https://x.com", "name": "X"},
            "paths": {
                "tools": "artifact/tools.json",  # does not exist
                "toolsets": "artifact/toolsets.yaml",
                "policy": "artifact/policy.yaml",
                "baseline": "artifact/baseline.json",
                "lockfiles": {},
            },
        }
        tp_file = tp_dir / "toolpack.yaml"
        tp_file.write_text(yaml.safe_dump(toolpack, sort_keys=False))

        engine = _make_engine(tp_file)
        report = engine.run(context_paths=[], auto_discover=False)

        # verify_before should be None or skipped — not crash
        if report.verify_before is not None:
            assert report.verify_before.verify_status == VerifyStatus.SKIPPED


# ===========================================================================
# 7. Redaction (3 tests)
# ===========================================================================


class TestRedaction:
    """Tests for evidence redaction."""

    def test_authorization_header_redacted(self, tmp_path: Path) -> None:
        """Authorization headers are stripped from raw_evidence in output."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            {
                **_deny_entry("denied_policy"),
                "extra": {
                    "request_headers": {"Authorization": "Bearer sk-secret-123"},
                    "host": "api.example.com",
                },
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        # The raw_evidence should not contain the original token
        for item in report.diagnosis.items:
            evidence_str = json.dumps(item.raw_evidence)
            assert "sk-secret-123" not in evidence_str

    def test_cookie_header_redacted(self, tmp_path: Path) -> None:
        """Cookie values are stripped from evidence."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            {
                **_deny_entry("denied_policy"),
                "extra": {
                    "request_headers": {"Cookie": "session=abc123xyz"},
                },
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        for item in report.diagnosis.items:
            evidence_str = json.dumps(item.raw_evidence)
            assert "abc123xyz" not in evidence_str

    def test_redaction_summary_populated(self, tmp_path: Path) -> None:
        """RedactionSummary has non-zero counts when redaction occurs."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            {
                **_deny_entry("denied_policy"),
                "extra": {
                    "request_headers": {"Authorization": "Bearer sk-secret"},
                    "Cookie": "session=abc",
                },
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        assert report.redaction_summary.redacted_field_count >= 1
        assert len(report.redaction_summary.redacted_keys) >= 1

    def test_drift_evidence_redacted(self, tmp_path: Path) -> None:
        """Authorization headers in drift report evidence are redacted."""
        tp = _write_minimal_toolpack(tmp_path)
        drift = _write_drift_report(tmp_path, [
            {
                "id": "d1",
                "type": "breaking",
                "severity": "critical",
                "endpoint_id": "get_users",
                "path": "/users",
                "method": "GET",
                "title": "Breaking: field removed",
                "description": "Field removed",
                "request_headers": {"Authorization": "Bearer drift-secret-token"},
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[drift], auto_discover=False)

        for item in report.diagnosis.items:
            evidence_str = json.dumps(item.raw_evidence)
            assert "drift-secret-token" not in evidence_str

    def test_verify_evidence_redacted(self, tmp_path: Path) -> None:
        """Sensitive data in verify report evidence is redacted."""
        tp = _write_minimal_toolpack(tmp_path)
        vr = _write_verify_report(tmp_path, {
            "contracts": {
                "status": "fail",
                "assertion_results": [],
                "request_headers": {"X-API-Key": "verify-api-key-secret"},
            },
        })
        engine = _make_engine(tp)
        report = engine.run(context_paths=[vr], auto_discover=False)

        for item in report.diagnosis.items:
            evidence_str = json.dumps(item.raw_evidence)
            assert "verify-api-key-secret" not in evidence_str

    def test_drift_redaction_counted_in_summary(self, tmp_path: Path) -> None:
        """Redaction from drift/verify evidence counts toward redaction_summary."""
        tp = _write_minimal_toolpack(tmp_path)
        drift = _write_drift_report(tmp_path, [
            {
                "id": "d1",
                "type": "breaking",
                "severity": "critical",
                "endpoint_id": "ep1",
                "path": "/x",
                "method": "GET",
                "title": "Break",
                "description": "Desc",
                "Cookie": "session=secret123",
            },
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[drift], auto_discover=False)

        assert report.redaction_summary.redacted_field_count >= 1
        assert "cookie" in report.redaction_summary.redacted_keys


# ===========================================================================
# 8. Auto-discover (2 tests)
# ===========================================================================


class TestAutoDiscover:
    """Tests for auto-discovery of context files."""

    def test_auto_discover_skipped_when_from_provided(self, tmp_path: Path) -> None:
        """Auto-discover does NOT run when --from is provided."""
        tp = _write_minimal_toolpack(tmp_path)

        # Place an audit log next to toolpack (would be auto-discovered)
        tp_dir = tp.parent
        _write_audit_log(tp_dir, [_deny_entry("denied_policy", tool_id="sneaky")])

        # But provide an empty explicit context
        (tmp_path / "explicit").mkdir(exist_ok=True)
        empty_audit = _write_audit_log(tmp_path / "explicit", [_allow_entry()])

        engine = _make_engine(tp)
        report = engine.run(context_paths=[empty_audit], auto_discover=False)

        # Should NOT find the sneaky deny from auto-discovery
        tool_ids = [i.tool_id for i in report.diagnosis.items]
        assert "sneaky" not in tool_ids

    def test_auto_discover_lists_files_used(self, tmp_path: Path) -> None:
        """Auto-discovered files are listed in context_files_used."""
        tp = _write_minimal_toolpack(tmp_path)
        tp_dir = tp.parent
        _write_audit_log(tp_dir, [_deny_entry("denied_not_approved")])

        engine = _make_engine(tp)
        report = engine.run(context_paths=[], auto_discover=True)

        # Should have found and listed the audit log
        assert len(report.diagnosis.context_files_used) >= 1


# ===========================================================================
# 9. PatchItem structured fields (2 tests)
# ===========================================================================


class TestPatchItemStructure:
    """Tests for PatchItem.action and PatchItem.args."""

    def test_patch_action_populated(self, tmp_path: Path) -> None:
        """Every patch has a non-empty action field."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        for patch in report.patch_plan.patches:
            assert patch.action  # non-empty PatchAction
            assert isinstance(patch.action, PatchAction)

    def test_patch_args_contains_toolpack_path(self, tmp_path: Path) -> None:
        """Patches with gate commands include toolpack_path in args."""
        tp = _write_minimal_toolpack(tmp_path)
        audit = _write_audit_log(tmp_path, [
            _deny_entry("denied_not_approved"),
        ])
        engine = _make_engine(tp)
        report = engine.run(context_paths=[audit], auto_discover=False)

        gate_patches = [p for p in report.patch_plan.patches if p.action == PatchAction.GATE_ALLOW]
        assert len(gate_patches) >= 1
        assert "toolpack_path" in gate_patches[0].args


# ===========================================================================
# 10. Verify snapshot error detail (1 test)
# ===========================================================================


class TestVerifySnapshotErrorDetail:
    """Tests for verify snapshot error reporting."""

    def test_verify_error_includes_exception_type(self, tmp_path: Path) -> None:
        """When verify engine errors, summary includes exception info."""
        import yaml

        # Create toolpack with invalid tools.json (will cause verify to fail)
        tp_dir = tmp_path / "tp_broken"
        tp_dir.mkdir()
        artifact_dir = tp_dir / "artifact"
        artifact_dir.mkdir()
        # Write invalid tools.json that will parse but cause verify engine issues
        (artifact_dir / "tools.json").write_text("not valid json at all {{{{")
        (artifact_dir / "contracts.yaml").write_text(yaml.safe_dump({"contracts": []}))

        toolpack = {
            "version": "1.0.0",
            "schema_version": "1.0",
            "toolpack_id": "tp_broken",
            "created_at": "2026-02-20T00:00:00Z",
            "capture_id": "c", "artifact_id": "a",
            "scope": "test", "allowed_hosts": [],
            "origin": {"start_url": "https://x.com", "name": "X"},
            "paths": {
                "tools": "artifact/tools.json",
                "toolsets": "artifact/toolsets.yaml",
                "policy": "artifact/policy.yaml",
                "baseline": "artifact/baseline.json",
                "contracts": "artifact/contracts.yaml",
                "lockfiles": {},
            },
        }
        tp_file = tp_dir / "toolpack.yaml"
        tp_file.write_text(yaml.safe_dump(toolpack, sort_keys=False))

        from toolwright.core.repair.engine import RepairEngine
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        toolpack_obj = load_toolpack(tp_file)
        resolved = resolve_toolpack_paths(toolpack=toolpack_obj, toolpack_path=tp_file)
        engine = RepairEngine(
            toolpack=toolpack_obj,
            toolpack_path=tp_file.resolve(),
            resolved=resolved,
        )
        report = engine.run(context_paths=[], auto_discover=False)

        # Should gracefully handle the error and include detail
        if report.verify_before is not None:
            assert report.verify_before.verify_status == VerifyStatus.SKIPPED
            # Summary should include error_type for debugging
            assert "error_type" in report.verify_before.summary


# ===========================================================================
# 11. Provenance patch wording (1 test)
# ===========================================================================


class TestProvenancePatchWording:
    """Tests for provenance patch description clarity."""

    def test_provenance_patch_explains_source(self, tmp_path: Path) -> None:
        """Provenance patch description clarifies it came from a supplied report."""
        tp = _write_minimal_toolpack(tmp_path)
        vr = _write_verify_report(tmp_path, {
            "provenance": {"status": "unknown", "results": []},
        })
        engine = _make_engine(tp)
        report = engine.run(context_paths=[vr], auto_discover=False)

        prov_patches = [
            p for p in report.patch_plan.patches
            if p.action == PatchAction.VERIFY_PROVENANCE
        ]
        assert len(prov_patches) >= 1
        patch = prov_patches[0]
        # Description should mention it's from a supplied/external report
        desc_lower = (patch.description + " " + patch.reason).lower()
        assert "supplied" in desc_lower or "external" in desc_lower or "report" in desc_lower


# ===========================================================================
# 12. Artifact digest verification (2 tests)
# ===========================================================================


class TestArtifactDigestVerification:
    """Repair engine should detect artifact tampering by comparing digests."""

    def _materialize_snapshot(self, tp_path: Path) -> Path:
        """Create a snapshot with digests.json for the toolpack."""
        from toolwright.utils.digests import build_digests_payload

        tp_dir = tp_path.parent
        artifact_dir = tp_dir / "artifact"
        artifacts = {
            "tools.json": artifact_dir / "tools.json",
            "toolsets.yaml": artifact_dir / "toolsets.yaml",
            "policy.yaml": artifact_dir / "policy.yaml",
            "baseline.json": artifact_dir / "baseline.json",
        }

        digests_payload = build_digests_payload(artifacts)
        snapshot_dir = tp_dir / ".toolwright" / "approvals" / "appr_test" / "artifacts"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        digests_path = snapshot_dir.parent / "digests.json"
        digests_path.write_text(json.dumps(digests_payload), encoding="utf-8")
        return snapshot_dir

    def test_tampered_artifact_detected_as_critical(self, tmp_path: Path) -> None:
        """Modifying tools.json after snapshot → repair should report CRITICAL."""
        tp = _write_minimal_toolpack(tmp_path)
        self._materialize_snapshot(tp)

        # Tamper tools.json after snapshot
        tp_dir = tp.parent
        tools_path = tp_dir / "artifact" / "tools.json"
        tampered = json.loads(tools_path.read_text())
        tampered["actions"].append({"name": "injected", "method": "DELETE", "path": "/pwned"})
        tools_path.write_text(json.dumps(tampered))

        engine = _make_engine(tp)
        report = engine.run(context_paths=[], auto_discover=False)

        # Should have at least one CRITICAL diagnosis item for integrity
        critical_items = [
            item for item in report.diagnosis.items
            if item.severity == DriftSeverity.CRITICAL
        ]
        assert len(critical_items) >= 1, (
            f"Expected CRITICAL diagnosis for tampered artifact. "
            f"Got items: {[(i.title, i.severity) for i in report.diagnosis.items]}"
        )
        # The critical item should mention integrity or digest
        titles = " ".join(i.title.lower() for i in critical_items)
        assert "integrity" in titles or "digest" in titles or "tamper" in titles

    def test_no_snapshot_reports_info_not_critical(self, tmp_path: Path) -> None:
        """No snapshot → repair should note missing snapshot, not panic."""
        tp = _write_minimal_toolpack(tmp_path)
        # No snapshot materialized — should not produce CRITICAL

        engine = _make_engine(tp)
        report = engine.run(context_paths=[], auto_discover=False)

        critical_items = [
            item for item in report.diagnosis.items
            if item.severity == DriftSeverity.CRITICAL
        ]
        assert len(critical_items) == 0, (
            f"Should not have CRITICAL items without a snapshot. "
            f"Got: {[(i.title, i.severity) for i in critical_items]}"
        )
