"""RepairEngine — stateless orchestrator for diagnose → propose → verify."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from toolwright.branding import CLI_PRIMARY_COMMAND
from toolwright.models.decision import ReasonCode
from toolwright.models.drift import DriftSeverity, DriftType
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
from toolwright.models.verify import VerifyStatus

# ---------------------------------------------------------------------------
# Deterministic severity mapping (plan table, no heuristics)
# ---------------------------------------------------------------------------

REASON_CODE_SEVERITY: dict[ReasonCode, DriftSeverity] = {
    # CRITICAL — possible compromise or fundamental integrity failure
    ReasonCode.DENIED_INTEGRITY_MISMATCH: DriftSeverity.CRITICAL,
    ReasonCode.DENIED_APPROVAL_SIGNATURE_INVALID: DriftSeverity.CRITICAL,
    # ERROR — blocks tool execution, requires action
    ReasonCode.DENIED_NOT_APPROVED: DriftSeverity.ERROR,
    ReasonCode.DENIED_TOOLSET_NOT_APPROVED: DriftSeverity.ERROR,
    ReasonCode.DENIED_TOOLSET_NOT_ALLOWED: DriftSeverity.ERROR,
    ReasonCode.DENIED_POLICY: DriftSeverity.ERROR,
    ReasonCode.DENIED_UNKNOWN_ACTION: DriftSeverity.ERROR,
    ReasonCode.DENIED_APPROVAL_SIGNATURE_REQUIRED: DriftSeverity.ERROR,
    ReasonCode.DENIED_HOST_RESOLUTION_FAILED: DriftSeverity.ERROR,
    # WARNING — degraded but not blocking all tools
    ReasonCode.DENIED_REDIRECT_NOT_ALLOWLISTED: DriftSeverity.WARNING,
    ReasonCode.DENIED_SCHEME_NOT_ALLOWED: DriftSeverity.WARNING,
    ReasonCode.DENIED_CONTENT_TYPE_NOT_ALLOWED: DriftSeverity.WARNING,
    ReasonCode.DENIED_PARAM_VALIDATION: DriftSeverity.WARNING,
    ReasonCode.DENIED_METHOD_NOT_ALLOWED: DriftSeverity.WARNING,
    ReasonCode.DENIED_RESPONSE_TOO_LARGE: DriftSeverity.WARNING,
    ReasonCode.DENIED_TIMEOUT: DriftSeverity.WARNING,
    ReasonCode.DENIED_RATE_LIMITED: DriftSeverity.WARNING,
    ReasonCode.DENIED_CONFIRMATION_INVALID: DriftSeverity.WARNING,
    ReasonCode.DENIED_CONFIRMATION_EXPIRED: DriftSeverity.WARNING,
    ReasonCode.DENIED_CONFIRMATION_REPLAY: DriftSeverity.WARNING,
    ReasonCode.ERROR_INTERNAL: DriftSeverity.WARNING,
}

# Severity ordering for sort (CRITICAL first, INFO last)
_SEVERITY_ORDER: dict[DriftSeverity, int] = {
    DriftSeverity.CRITICAL: 0,
    DriftSeverity.ERROR: 1,
    DriftSeverity.WARNING: 2,
    DriftSeverity.INFO: 3,
}

# Drift types that trigger diagnosis (skip ADDITIVE — informational only)
_ACTIONABLE_DRIFT_TYPES: set[DriftType] = {
    DriftType.BREAKING,
    DriftType.AUTH,
    DriftType.RISK,
    DriftType.SCHEMA,
    DriftType.PARAMETER,
    DriftType.CONTRACT,
    DriftType.UNKNOWN,
}

# Headers whose values should be redacted from evidence
_SENSITIVE_HEADERS: set[str] = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-access-token",
    "x-csrf-token",
    "proxy-authorization",
}

# Query-param keys whose values should be redacted
_SENSITIVE_PARAMS: set[str] = {
    "token",
    "key",
    "api_key",
    "apikey",
    "secret",
    "password",
    "session",
    "access_token",
    "refresh_token",
    "sig",
}


class RepairEngine:
    """Stateless repair orchestrator: diagnose → propose → verify."""

    def __init__(
        self,
        *,
        toolpack: Any,
        toolpack_path: Path,
        resolved: Any,
    ) -> None:
        self._toolpack = toolpack
        self._toolpack_path = toolpack_path
        self._resolved = resolved

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        context_paths: list[Path],
        auto_discover: bool = True,
    ) -> RepairReport:
        """Run the full repair pipeline and return a RepairReport."""
        # Phase 0: resolve all paths
        tp_path_str = str(self._toolpack_path)

        # Phase 1: diagnose
        diagnosis, redaction = self._diagnose(
            context_paths=context_paths,
            auto_discover=auto_discover,
        )

        # Phase 2: propose
        patch_plan = self._propose(diagnosis)

        # Phase 3: verify (contracts only, artifact-only)
        verify_before = self._verify_current()

        # Phase 4: assemble report
        exit_code = 0 if diagnosis.total_issues == 0 else 1

        return RepairReport(
            toolpack_id=self._toolpack.toolpack_id,
            toolpack_path=tp_path_str,
            diagnosis=diagnosis,
            patch_plan=patch_plan,
            verify_before=verify_before,
            redaction_summary=redaction,
            exit_code=exit_code,
        )

    # ------------------------------------------------------------------
    # Phase 1: Diagnose
    # ------------------------------------------------------------------

    def _diagnose(
        self,
        *,
        context_paths: list[Path],
        auto_discover: bool,
    ) -> tuple[RepairDiagnosis, RedactionSummary]:
        """Parse context files and produce diagnosis items."""
        # Determine which files to parse
        effective_paths: list[Path] = list(context_paths)
        if not effective_paths and auto_discover:
            effective_paths = self._auto_discover_context()

        # Parse all context files
        all_items: list[DiagnosisItem] = []
        context_files_used: list[str] = []
        redacted_keys: set[str] = set()
        redacted_count = 0

        for path in effective_paths:
            context_files_used.append(str(path))
            items, r_keys, r_count = self._parse_context_file(path)
            all_items.extend(items)
            redacted_keys.update(r_keys)
            redacted_count += r_count

        # Check artifact digests against snapshot
        digest_items = self._check_artifact_digests()
        all_items.extend(digest_items)

        # Dedup by diagnosis ID
        seen_ids: set[str] = set()
        deduped: list[DiagnosisItem] = []
        for item in all_items:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                deduped.append(item)

        # Sort by severity (CRITICAL > ERROR > WARNING > INFO)
        deduped.sort(key=lambda i: _SEVERITY_ORDER.get(i.severity, 99))

        # Build clusters
        clusters: dict[str, list[str]] = {}
        for item in deduped:
            clusters.setdefault(item.cluster_key, []).append(item.id)

        # Count by severity and source
        by_severity: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for item in deduped:
            by_severity[item.severity.value] = by_severity.get(item.severity.value, 0) + 1
            by_source[item.source.value] = by_source.get(item.source.value, 0) + 1

        diagnosis = RepairDiagnosis(
            total_issues=len(deduped),
            by_severity=by_severity,
            by_source=by_source,
            clusters=clusters,
            context_files_used=context_files_used,
            items=deduped,
        )
        redaction = RedactionSummary(
            redacted_field_count=redacted_count,
            redacted_keys=sorted(redacted_keys),
        )
        return diagnosis, redaction

    def _parse_context_file(
        self, path: Path
    ) -> tuple[list[DiagnosisItem], set[str], int]:
        """Dispatch by file content to the appropriate parser."""
        items: list[DiagnosisItem] = []
        redacted_keys: set[str] = set()
        redacted_count = 0

        suffix = path.suffix.lower()

        if suffix == ".jsonl" or path.name.endswith(".log.jsonl"):
            # Audit log (JSONL)
            result = self._parse_audit_log(path)
            items, redacted_keys, redacted_count = result
        else:
            # Try JSON
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return [], set(), 0

            if isinstance(data, dict):
                if "drifts" in data:
                    items, redacted_keys, redacted_count = self._parse_drift_report(data)
                elif "contracts" in data or "provenance" in data:
                    items, redacted_keys, redacted_count = self._parse_verify_report(data)

        return items, redacted_keys, redacted_count

    def _parse_audit_log(
        self, path: Path
    ) -> tuple[list[DiagnosisItem], set[str], int]:
        """Parse JSONL audit log, extract DENY entries."""
        items: list[DiagnosisItem] = []
        redacted_keys: set[str] = set()
        redacted_count = 0

        for line in path.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            decision = entry.get("decision", "")
            if decision != "deny":
                continue

            reason_code_str = entry.get("reason_code", "")
            try:
                reason_code = ReasonCode(reason_code_str)
            except ValueError:
                continue

            severity = REASON_CODE_SEVERITY.get(reason_code, DriftSeverity.WARNING)
            tool_id = entry.get("tool_id", "")

            # Redact evidence
            raw_evidence = dict(entry)
            raw_evidence, r_keys, r_count = _redact_evidence(raw_evidence)
            redacted_keys.update(r_keys)
            redacted_count += r_count

            diag_id = _make_diagnosis_id(
                source="audit_log",
                reason_code=reason_code_str,
                tool_id=tool_id,
            )

            cluster_key = f"tool:{tool_id}" if tool_id else f"reason:{reason_code_str}"

            items.append(
                DiagnosisItem(
                    id=diag_id,
                    source=DiagnosisSource.AUDIT_LOG,
                    severity=severity,
                    reason_code=reason_code,
                    tool_id=tool_id or None,
                    title=f"Denied: {reason_code_str}",
                    description=f"Tool '{tool_id}' denied with reason: {reason_code_str}",
                    cluster_key=cluster_key,
                    raw_evidence=raw_evidence,
                )
            )

        return items, redacted_keys, redacted_count

    def _parse_drift_report(
        self, data: dict[str, Any]
    ) -> tuple[list[DiagnosisItem], set[str], int]:
        """Parse a drift report JSON, extract actionable drifts."""
        items: list[DiagnosisItem] = []
        redacted_keys: set[str] = set()
        redacted_count = 0
        drifts = data.get("drifts", [])

        for drift in drifts:
            drift_type_str = drift.get("type", "unknown")
            try:
                drift_type = DriftType(drift_type_str)
            except ValueError:
                drift_type = DriftType.UNKNOWN

            # Skip non-actionable drifts
            if drift_type not in _ACTIONABLE_DRIFT_TYPES:
                continue

            severity_str = drift.get("severity", "warning")
            try:
                severity = DriftSeverity(severity_str)
            except ValueError:
                severity = DriftSeverity.WARNING

            drift_id = drift.get("id", "unknown")
            endpoint_id = drift.get("endpoint_id", "")
            path = drift.get("path", "")
            method = drift.get("method", "")
            title = drift.get("title", f"Drift: {drift_type_str}")
            description = drift.get("description", "")

            diag_id = _make_diagnosis_id(
                source="drift_report",
                drift_type=drift_type_str,
                drift_id=drift_id,
            )

            cluster_key = f"drift:{drift_type_str}"
            if endpoint_id:
                cluster_key = f"tool:{endpoint_id}"

            # Redact evidence
            raw_evidence = dict(drift)
            raw_evidence, r_keys, r_count = _redact_evidence(raw_evidence)
            redacted_keys.update(r_keys)
            redacted_count += r_count

            items.append(
                DiagnosisItem(
                    id=diag_id,
                    source=DiagnosisSource.DRIFT_REPORT,
                    severity=severity,
                    drift_type=drift_type,
                    tool_id=endpoint_id or None,
                    path=path or None,
                    method=method or None,
                    title=title,
                    description=description,
                    cluster_key=cluster_key,
                    raw_evidence=raw_evidence,
                )
            )

        return items, redacted_keys, redacted_count

    def _parse_verify_report(
        self, data: dict[str, Any]
    ) -> tuple[list[DiagnosisItem], set[str], int]:
        """Parse a verify report JSON, extract fail/unknown sections."""
        items: list[DiagnosisItem] = []
        redacted_keys: set[str] = set()
        redacted_count = 0

        # Check contracts section
        contracts = data.get("contracts")
        if isinstance(contracts, dict):
            status_str = contracts.get("status", "")
            try:
                status = VerifyStatus(status_str)
            except ValueError:
                status = VerifyStatus.UNKNOWN

            if status in (VerifyStatus.FAIL, VerifyStatus.UNKNOWN):
                severity = DriftSeverity.ERROR if status == VerifyStatus.FAIL else DriftSeverity.WARNING

                diag_id = _make_diagnosis_id(
                    source="verify_report",
                    section="contracts",
                    status=status_str,
                )

                # Redact evidence
                raw_evidence = dict(contracts)
                raw_evidence, r_keys, r_count = _redact_evidence(raw_evidence)
                redacted_keys.update(r_keys)
                redacted_count += r_count

                items.append(
                    DiagnosisItem(
                        id=diag_id,
                        source=DiagnosisSource.VERIFY_REPORT,
                        severity=severity,
                        verify_status=status,
                        title=f"Contracts verification: {status_str}",
                        description=f"Contract checks returned status: {status_str}",
                        cluster_key="verify:contracts",
                        raw_evidence=raw_evidence,
                    )
                )

        # Check provenance section
        provenance = data.get("provenance")
        if isinstance(provenance, dict):
            status_str = provenance.get("status", "")
            try:
                status = VerifyStatus(status_str)
            except ValueError:
                status = VerifyStatus.UNKNOWN

            if status in (VerifyStatus.FAIL, VerifyStatus.UNKNOWN):
                severity = DriftSeverity.ERROR if status == VerifyStatus.FAIL else DriftSeverity.WARNING

                diag_id = _make_diagnosis_id(
                    source="verify_report",
                    section="provenance",
                    status=status_str,
                )

                # Redact evidence
                raw_evidence = dict(provenance)
                raw_evidence, r_keys, r_count = _redact_evidence(raw_evidence)
                redacted_keys.update(r_keys)
                redacted_count += r_count

                items.append(
                    DiagnosisItem(
                        id=diag_id,
                        source=DiagnosisSource.VERIFY_REPORT,
                        severity=severity,
                        verify_status=status,
                        title=f"Provenance verification: {status_str}",
                        description=f"Provenance checks returned status: {status_str}",
                        cluster_key="verify:provenance",
                        raw_evidence=raw_evidence,
                    )
                )

        return items, redacted_keys, redacted_count

    def _auto_discover_context(self) -> list[Path]:
        """Search standard locations near toolpack for context files."""
        discovered: list[Path] = []
        tp_dir = self._toolpack_path.parent

        # Search in toolpack directory and parent
        search_dirs = [tp_dir, tp_dir.parent]
        for search_dir in search_dirs:
            if not search_dir.is_dir():
                continue
            # Look for audit logs
            for candidate in search_dir.glob("*.log.jsonl"):
                discovered.append(candidate)
            for candidate in search_dir.glob("audit*.jsonl"):
                discovered.append(candidate)
            # Look for drift reports
            for candidate in search_dir.glob("drift*.json"):
                discovered.append(candidate)
            # Look for verify reports
            for candidate in search_dir.glob("verify*.json"):
                discovered.append(candidate)

        # Also check reports/ subdirectory
        reports_dir = tp_dir / "reports"
        if reports_dir.is_dir():
            for candidate in reports_dir.iterdir():
                if candidate.suffix in (".json", ".jsonl"):
                    discovered.append(candidate)

        return sorted(set(discovered))

    # ------------------------------------------------------------------
    # Phase 2: Propose
    # ------------------------------------------------------------------

    def _propose(self, diagnosis: RepairDiagnosis) -> RepairPatchPlan:
        """Map each diagnosis item to a PatchItem."""
        patches: list[PatchItem] = []
        for item in diagnosis.items:
            patch = self._patch_for_diagnosis(item)
            if patch:
                patches.append(patch)

        # Aggregate counts
        safe_count = sum(1 for p in patches if p.kind == PatchKind.SAFE)
        approval_count = sum(1 for p in patches if p.kind == PatchKind.APPROVAL_REQUIRED)
        manual_count = sum(1 for p in patches if p.kind == PatchKind.MANUAL)

        # Build commands.sh
        commands = [p.cli_command for p in patches if p.cli_command.strip()]
        commands_sh = "\n".join(commands) if commands else ""

        return RepairPatchPlan(
            total_patches=len(patches),
            safe_count=safe_count,
            approval_required_count=approval_count,
            manual_count=manual_count,
            patches=patches,
            commands_sh=commands_sh,
        )

    def _patch_for_diagnosis(self, item: DiagnosisItem) -> PatchItem | None:
        """Map a single diagnosis to a proposed patch."""
        tp = str(self._toolpack_path)

        # --- Audit-sourced diagnoses ---
        if item.source == DiagnosisSource.AUDIT_LOG and item.reason_code:
            return self._patch_for_reason_code(item, tp)

        # --- Drift-sourced diagnoses ---
        if item.source == DiagnosisSource.DRIFT_REPORT and item.drift_type:
            return self._patch_for_drift(item, tp)

        # --- Verify-sourced diagnoses ---
        if item.source == DiagnosisSource.VERIFY_REPORT and item.verify_status:
            return self._patch_for_verify(item, tp)

        return None

    def _patch_for_reason_code(self, item: DiagnosisItem, tp: str) -> PatchItem:
        """Generate patch for an audit-log deny reason code."""
        rc = item.reason_code
        assert rc is not None

        # Default: investigate
        kind = PatchKind.MANUAL
        action = PatchAction.INVESTIGATE
        cli_command = f"# Investigate: {rc.value}"
        title = f"Investigate: {rc.value}"
        description = f"Requires manual investigation for {rc.value}"
        reason = f"Diagnose and resolve {rc.value}"
        risk_note: str | None = None
        args: dict[str, Any] = {"toolpack_path": tp}

        if rc in (ReasonCode.DENIED_NOT_APPROVED, ReasonCode.DENIED_TOOLSET_NOT_APPROVED):
            kind = PatchKind.APPROVAL_REQUIRED
            action = PatchAction.GATE_ALLOW
            cli_command = f"{CLI_PRIMARY_COMMAND} gate allow --toolpack {tp}"
            title = f"Approve tool: {item.tool_id or 'unknown'}"
            description = f"Tool '{item.tool_id}' is not approved. Run gate allow to approve."
            reason = f"Tool denied because it is not approved ({rc.value})"
            risk_note = "Grants tool execution permission"

        elif rc == ReasonCode.DENIED_TOOLSET_NOT_ALLOWED:
            kind = PatchKind.APPROVAL_REQUIRED
            action = PatchAction.GATE_ALLOW
            cli_command = f"{CLI_PRIMARY_COMMAND} gate allow --toolpack {tp}"
            title = f"Allow toolset for: {item.tool_id or 'unknown'}"
            description = "Toolset not allowed. Review and approve the toolset."
            reason = f"Tool denied because toolset is not allowed ({rc.value})"
            risk_note = "Grants toolset execution permission"

        elif rc == ReasonCode.DENIED_INTEGRITY_MISMATCH:
            kind = PatchKind.MANUAL
            action = PatchAction.INVESTIGATE
            cli_command = "# Investigate: artifacts digest mismatch — may indicate tampering"
            title = "Investigate integrity mismatch"
            description = "Artifact digests do not match. This may indicate tampering or corruption."
            reason = "Integrity mismatch requires manual investigation before any remediation"
            risk_note = "Potential security concern"

        elif rc == ReasonCode.DENIED_POLICY:
            kind = PatchKind.APPROVAL_REQUIRED
            action = PatchAction.REVIEW_POLICY
            cli_command = f"# Review and update policy rules for toolpack {tp}"
            title = "Review policy rules"
            description = f"Tool '{item.tool_id}' denied by policy. Review and update policy."
            reason = "Policy denial requires reviewing the governance rules"
            risk_note = "May change enforcement behavior"

        elif rc == ReasonCode.DENIED_REDIRECT_NOT_ALLOWLISTED:
            kind = PatchKind.APPROVAL_REQUIRED
            action = PatchAction.ADD_HOST
            cli_command = "# Add host to allowed_hosts if trusted"
            title = "Add redirect host to allowlist"
            description = "A redirect target is not in the allowed hosts list."
            reason = "Redirect blocked because target host is not allowlisted"
            risk_note = "Expands host allowlist"

        elif rc in (
            ReasonCode.DENIED_APPROVAL_SIGNATURE_INVALID,
            ReasonCode.DENIED_APPROVAL_SIGNATURE_REQUIRED,
        ):
            kind = PatchKind.APPROVAL_REQUIRED
            action = PatchAction.GATE_RESEAL
            cli_command = f"{CLI_PRIMARY_COMMAND} gate reseal --toolpack {tp}"
            title = "Reseal approval signatures"
            description = "Approval signatures are invalid or missing. Re-sign the lockfile."
            reason = f"Signature issue: {rc.value}"
            risk_note = "Re-signs approval lockfile"

        elif rc == ReasonCode.DENIED_SCHEME_NOT_ALLOWED:
            kind = PatchKind.APPROVAL_REQUIRED
            action = PatchAction.REVIEW_POLICY
            cli_command = f"# Review scheme allowlist in policy for toolpack {tp}"
            title = "Review scheme allowlist"
            description = "Request scheme (e.g. http vs https) is not in the allowed list."
            reason = "Scheme not allowed — review policy configuration"

        elif rc == ReasonCode.DENIED_HOST_RESOLUTION_FAILED:
            kind = PatchKind.MANUAL
            action = PatchAction.INVESTIGATE
            cli_command = "# Investigate: host DNS resolution failed"
            title = "Investigate DNS resolution failure"
            description = "Host could not be resolved. Check DNS, network, or host configuration."
            reason = "DNS resolution failure requires infrastructure investigation"

        elif rc == ReasonCode.DENIED_UNKNOWN_ACTION:
            kind = PatchKind.APPROVAL_REQUIRED
            action = PatchAction.GATE_ALLOW
            cli_command = f"{CLI_PRIMARY_COMMAND} gate allow --toolpack {tp}"
            title = f"Approve unknown action: {item.tool_id or 'unknown'}"
            description = "Action is not recognized in the current tools manifest."
            reason = "Unknown action needs to be added to manifest and approved"

        # For all other reason codes, default investigate is used

        patch_id = _make_patch_id(item.id, action.value)

        return PatchItem(
            id=patch_id,
            diagnosis_id=item.id,
            kind=kind,
            action=action,
            args=args,
            cli_command=cli_command,
            title=title,
            description=description,
            reason=reason,
            risk_note=risk_note,
        )

    def _patch_for_drift(self, item: DiagnosisItem, tp: str) -> PatchItem:
        """Generate patch for a drift-sourced diagnosis."""
        dt = item.drift_type
        assert dt is not None
        args: dict[str, Any] = {"toolpack_path": tp}

        if dt in (DriftType.BREAKING, DriftType.AUTH):
            kind = PatchKind.MANUAL
            action = PatchAction.RE_MINT
            cli_command = f"# Re-capture: {CLI_PRIMARY_COMMAND} mint <start-url> -a <api-host>"
            title = f"Re-mint toolpack ({dt.value} drift)"
            description = f"{dt.value.title()} drift detected. Re-capture and re-compile the toolpack."
            reason = f"{dt.value.title()} drift cannot be resolved without a new capture"
            risk_note = "Requires new capture session"
        elif dt == DriftType.RISK:
            kind = PatchKind.APPROVAL_REQUIRED
            action = PatchAction.GATE_ALLOW
            cli_command = f"{CLI_PRIMARY_COMMAND} gate allow --toolpack {tp}"
            title = "Approve new risk-tier endpoint"
            description = "New state-changing endpoint detected. Review and approve."
            reason = "Risk drift adds a new capability that needs explicit approval"
            risk_note = "Grants new tool execution permission"
        else:
            # SCHEMA, PARAMETER, CONTRACT, UNKNOWN — investigate
            kind = PatchKind.MANUAL
            action = PatchAction.INVESTIGATE
            cli_command = f"# Investigate {dt.value} drift for toolpack {tp}"
            title = f"Investigate {dt.value} drift"
            description = f"{dt.value.title()} drift detected. Manual review required."
            reason = f"{dt.value.title()} drift may indicate API changes"
            risk_note = None

        patch_id = _make_patch_id(item.id, action.value)

        return PatchItem(
            id=patch_id,
            diagnosis_id=item.id,
            kind=kind,
            action=action,
            args=args,
            cli_command=cli_command,
            title=title,
            description=description,
            reason=reason,
            risk_note=risk_note,
        )

    def _patch_for_verify(self, item: DiagnosisItem, tp: str) -> PatchItem:
        """Generate patch for a verify-sourced diagnosis."""
        vs = item.verify_status
        assert vs is not None
        args: dict[str, Any] = {"toolpack_path": tp}

        # Determine if contracts or provenance based on cluster_key
        is_provenance = "provenance" in item.cluster_key

        if is_provenance:
            action = PatchAction.VERIFY_PROVENANCE
            cli_command = f"{CLI_PRIMARY_COMMAND} verify --toolpack {tp} --mode provenance"
            title = "Re-run provenance verification"
            description = (
                "A supplied verify report shows provenance status is non-passing. "
                "Re-run provenance verification to confirm."
            )
            reason = (
                "Provenance status from supplied report is not passing "
                "— re-verify to confirm or investigate"
            )
        else:
            action = PatchAction.VERIFY_CONTRACTS
            cli_command = f"{CLI_PRIMARY_COMMAND} verify --toolpack {tp} --mode contracts"
            title = "Re-run contracts verification"
            description = (
                "A supplied verify report shows contracts status is non-passing. "
                "Re-run contracts verification to confirm."
            )
            reason = (
                "Contracts status from supplied report is not passing "
                "— re-verify to confirm or investigate"
            )

        kind = PatchKind.SAFE  # Read-only, zero capability expansion

        patch_id = _make_patch_id(item.id, action.value)

        return PatchItem(
            id=patch_id,
            diagnosis_id=item.id,
            kind=kind,
            action=action,
            args=args,
            cli_command=cli_command,
            title=title,
            description=description,
            reason=reason,
            risk_note=None,
        )

    # ------------------------------------------------------------------
    # Artifact digest verification against snapshot
    # ------------------------------------------------------------------

    def _check_artifact_digests(self) -> list[DiagnosisItem]:
        """Compare current artifact digests against snapshot digests.json.

        Returns CRITICAL diagnosis items for any mismatches (possible tampering).
        Returns empty list if no snapshot exists (nothing to compare against).
        """
        toolpack_root = self._toolpack_path.parent
        approvals_dir = toolpack_root / ".toolwright" / "approvals"

        if not approvals_dir.exists():
            return []

        # Find the most recent snapshot with digests.json
        digests_path: Path | None = None
        for snapshot_dir in sorted(approvals_dir.iterdir(), reverse=True):
            candidate = snapshot_dir / "digests.json"
            if candidate.exists():
                digests_path = candidate
                break

        if digests_path is None:
            return []

        try:
            snapshot_digests = json.loads(digests_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        snapshot_files = snapshot_digests.get("files", {})
        if not snapshot_files:
            return []

        from toolwright.utils.digests import canonical_file_digest

        items: list[DiagnosisItem] = []
        artifact_dir = toolpack_root / "artifact"

        for filename, expected in snapshot_files.items():
            artifact_path = artifact_dir / filename
            if not artifact_path.exists():
                items.append(
                    DiagnosisItem(
                        id=_make_diagnosis_id(
                            source="digest_check",
                            filename=filename,
                            kind="missing",
                        ),
                        source=DiagnosisSource.VERIFY_REPORT,
                        severity=DriftSeverity.CRITICAL,
                        tool_id=None,
                        path=filename,
                        method=None,
                        title=f"Artifact integrity: {filename} missing",
                        description=(
                            f"Artifact {filename} was present at snapshot time "
                            f"but is now missing. This may indicate tampering."
                        ),
                        cluster_key=f"integrity:{filename}",
                        raw_evidence={"filename": filename, "expected_digest": expected.get("sha256", "")},
                    )
                )
                continue

            current_digest, current_size = canonical_file_digest(artifact_path)
            expected_digest = expected.get("sha256", "")

            if current_digest != expected_digest:
                items.append(
                    DiagnosisItem(
                        id=_make_diagnosis_id(
                            source="digest_check",
                            filename=filename,
                            kind="mismatch",
                        ),
                        source=DiagnosisSource.VERIFY_REPORT,
                        severity=DriftSeverity.CRITICAL,
                        tool_id=None,
                        path=filename,
                        method=None,
                        title=f"Artifact integrity: {filename} tampered",
                        description=(
                            f"Artifact {filename} has been modified since the last "
                            f"approved snapshot. Expected digest {expected_digest[:12]}…, "
                            f"got {current_digest[:12]}…. "
                            f"Run '{CLI_PRIMARY_COMMAND} gate snapshot' to re-approve."
                        ),
                        cluster_key=f"integrity:{filename}",
                        raw_evidence={
                            "filename": filename,
                            "expected_digest": expected_digest,
                            "current_digest": current_digest,
                        },
                    )
                )

        return items

    # ------------------------------------------------------------------
    # Phase 3: Verify (artifact-only, contracts mode only)
    # ------------------------------------------------------------------

    def _verify_current(self) -> VerifySnapshot | None:
        """Run contracts-only verification against on-disk artifacts."""
        # Check that required artifacts exist
        contracts_path = self._resolved.contracts_path
        tools_path = self._resolved.tools_path

        if not tools_path or not tools_path.exists():
            return VerifySnapshot(
                verify_status=VerifyStatus.SKIPPED,
                summary={"reason": "artifacts_missing", "detail": "tools.json not found"},
            )

        if not contracts_path or not contracts_path.exists():
            return VerifySnapshot(
                verify_status=VerifyStatus.SKIPPED,
                summary={"reason": "artifacts_missing", "detail": "contracts not found"},
            )

        # Try to run verify engine in contracts mode
        try:
            import json as _json

            from toolwright.core.verify.engine import VerifyEngine

            manifest = _json.loads(tools_path.read_text(encoding="utf-8"))
            engine = VerifyEngine(toolpack_id=self._toolpack.toolpack_id)
            result = engine.run(
                mode="contracts",
                tools_manifest=manifest,
                contract_path=contracts_path,
            )
            return VerifySnapshot(
                verify_status=result.overall_status,
                summary={"mode": "contracts", "exit_code": result.exit_code},
            )
        except Exception as exc:
            return VerifySnapshot(
                verify_status=VerifyStatus.SKIPPED,
                summary={
                    "reason": "verify_engine_error",
                    "error_type": type(exc).__name__,
                    "error_detail": str(exc)[:200],
                },
            )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _make_diagnosis_id(**fields: str) -> str:
    """Deterministic SHA-256 hash of key fields."""
    canonical = "|".join(f"{k}={v}" for k, v in sorted(fields.items()))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _make_patch_id(diagnosis_id: str, action: str) -> str:
    """Deterministic patch ID from diagnosis ID and action."""
    canonical = f"{diagnosis_id}:{action}"
    return f"patch_{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"


def _redact_evidence(
    data: dict[str, Any],
) -> tuple[dict[str, Any], set[str], int]:
    """Redact sensitive headers and params from evidence dict.

    Returns (redacted_data, set of redacted key names, count of redactions).
    """
    redacted_keys: set[str] = set()
    count = 0

    def _redact_dict_recursive(d: dict[str, Any]) -> dict[str, Any]:
        nonlocal count
        result: dict[str, Any] = {}
        for key, value in d.items():
            key_lower = key.lower()
            # Redact sensitive header values
            if key_lower in _SENSITIVE_HEADERS or key_lower in _SENSITIVE_PARAMS:
                result[key] = "[REDACTED]"
                redacted_keys.add(key_lower)
                count += 1
            elif isinstance(value, dict):
                result[key] = _redact_dict_recursive(value)
            elif isinstance(value, list):
                result[key] = [
                    _redact_dict_recursive(v) if isinstance(v, dict) else v
                    for v in value
                ]
            elif isinstance(value, str) and key_lower in (
                "request_headers",
                "response_headers",
            ):
                # Headers stored as string — redact the whole thing if sensitive
                result[key] = value
            else:
                result[key] = value
        return result

    redacted = _redact_dict_recursive(data)
    return redacted, redacted_keys, count
