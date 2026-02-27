"""Stable operations layer for the Toolwright TUI.

Functions here call domain logic directly and return frozen dataclasses
or Pydantic models.  They are the **only** bridge between the UI layer
(flows, views, dashboard) and the core domain.

Strict rules
------------
- **Never prints** to stdout or stderr.
- **Never prompts** the user.
- **Never logs** to the console.
- **May write artifacts** only within root-managed directories (``.toolwright/``).
- **Uses transactional writes** (temp dir → atomic rename) so that
  cancellation never leaves partial state.

All existing runner.py functions are preserved here.  New operations are
added for the TUI v2 (status, preflight, fingerprint).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from toolwright.core.approval import LockfileManager
from toolwright.core.approval.lockfile import ApprovalStatus, Lockfile, ToolApproval
from toolwright.core.approval.signing import resolve_approver
from toolwright.core.approval.snapshot import materialize_snapshot
from toolwright.core.toolpack import Toolpack, load_toolpack, resolve_toolpack_paths
from toolwright.utils.deps import has_mcp_dependency
from toolwright.utils.runtime import docker_available

# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DoctorCheck:
    """A single doctor check result."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DoctorResult:
    """Aggregate doctor results."""

    checks: list[DoctorCheck]
    runtime_mode: str

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def run_doctor_checks(
    toolpack_path: str,
    runtime: str = "auto",
    require_local_mcp: bool = False,
) -> DoctorResult:
    """Run doctor checks and return structured results.

    Raises FileNotFoundError / ValueError if toolpack cannot be loaded.
    """
    from toolwright.core.approval import compute_artifacts_digest_from_paths

    checks: list[DoctorCheck] = []

    toolpack = load_toolpack(Path(toolpack_path))
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_path)
    toolpack_root = Path(toolpack_path).resolve().parent

    # Artifact existence checks
    for label, path in [
        ("tools.json", resolved.tools_path),
        ("toolsets.yaml", resolved.toolsets_path),
        ("policy.yaml", resolved.policy_path),
        ("baseline.json", resolved.baseline_path),
    ]:
        exists = path.exists()
        checks.append(DoctorCheck(
            name=label,
            passed=exists,
            detail=str(path) if exists else f"{label} missing: {path}",
        ))

    # Lockfile
    lockfile_path = resolved.approved_lockfile_path or resolved.pending_lockfile_path
    if lockfile_path is None or not lockfile_path.exists():
        checks.append(DoctorCheck(
            name="lockfile",
            passed=False,
            detail="missing; run toolwright gate sync",
        ))
    else:
        checks.append(DoctorCheck(
            name="lockfile",
            passed=True,
            detail=str(lockfile_path),
        ))

        # Artifacts digest
        if all(c.passed for c in checks[:4]):
            manager = LockfileManager(lockfile_path)
            lockfile = manager.load()
            digest = compute_artifacts_digest_from_paths(
                tools_path=resolved.tools_path,
                toolsets_path=resolved.toolsets_path,
                policy_path=resolved.policy_path,
            )
            digest_match = not lockfile.artifacts_digest or lockfile.artifacts_digest == digest
            checks.append(DoctorCheck(
                name="artifacts digest",
                passed=digest_match,
                detail="matches" if digest_match else "lockfile artifacts digest mismatch; re-run toolwright gate sync",
            ))

            # Evidence hash
            expected = lockfile.evidence_summary_sha256
            if expected:
                actual = None
                if (
                    resolved.evidence_summary_sha256_path
                    and resolved.evidence_summary_sha256_path.exists()
                ):
                    actual = resolved.evidence_summary_sha256_path.read_text().strip()
                evidence_ok = actual == expected
                checks.append(DoctorCheck(
                    name="evidence hash",
                    passed=evidence_ok,
                    detail="matches" if evidence_ok else "evidence summary hash mismatch; re-run verification",
                ))

    # Runtime checks
    mode = runtime
    if mode == "auto":
        mode = toolpack.runtime.mode if toolpack.runtime else "local"

    if mode == "local":
        if require_local_mcp:
            has_mcp = has_mcp_dependency()
            checks.append(DoctorCheck(
                name="mcp dependency",
                passed=has_mcp,
                detail="installed" if has_mcp else 'mcp not installed. Install with: pip install "toolwright[mcp]"',
            ))
    elif mode == "container":
        if toolpack.runtime is None or toolpack.runtime.container is None:
            checks.append(DoctorCheck(
                name="container config",
                passed=False,
                detail="runtime container configuration missing in toolpack",
            ))
        else:
            container = toolpack.runtime.container
            for label, rel in [
                ("Dockerfile", container.dockerfile),
                ("entrypoint", container.entrypoint),
                ("run wrapper", container.run),
                ("requirements", container.requirements),
            ]:
                p = toolpack_root / rel
                checks.append(DoctorCheck(
                    name=f"container:{label}",
                    passed=p.exists(),
                    detail=str(p) if p.exists() else f"container runtime file missing: {p}",
                ))
        docker_ok = docker_available()
        checks.append(DoctorCheck(
            name="docker",
            passed=docker_ok,
            detail="available" if docker_ok else "docker not available; install Docker or use --runtime local",
        ))
    else:
        checks.append(DoctorCheck(
            name="runtime mode",
            passed=False,
            detail=f"unknown runtime mode: {mode}",
        ))

    return DoctorResult(checks=checks, runtime_mode=mode)


# ---------------------------------------------------------------------------
# Gate approve / reject / snapshot
# ---------------------------------------------------------------------------


@dataclass
class ApproveResult:
    """Result of an approval operation."""

    approved_ids: list[str] = field(default_factory=list)
    lockfile_path: str = ""
    promoted: bool = False


def run_gate_approve(
    tool_ids: list[str],
    lockfile_path: str,
    *,
    all_pending: bool = False,
    toolset: str | None = None,
    approved_by: str | None = None,
    reason: str | None = None,
    root_path: str = ".toolwright",
) -> ApproveResult:
    """Approve tools in a lockfile. Returns structured result.

    Raises FileNotFoundError if lockfile missing, ValueError on bad args.
    """
    manager = LockfileManager(lockfile_path)
    if not manager.exists():
        raise FileNotFoundError(f"No lockfile found at: {manager.lockfile_path}")

    manager.load()
    actor = resolve_approver(approved_by)

    if all_pending:
        ids_to_approve = [t.tool_id for t in manager.get_pending()]
    elif toolset:
        ids_to_approve = [
            t.tool_id
            for t in manager.get_pending()
            if toolset in t.toolsets
        ]
    else:
        ids_to_approve = list(tool_ids)

    approved: list[str] = []
    for tid in ids_to_approve:
        tool = manager.get_tool(tid)
        if tool and tool.status == ApprovalStatus.PENDING:
            manager.approve(
                tool_id=tid,
                approved_by=actor,
                reason=reason,
            )
            approved.append(tid)

    manager.save()

    # Check if we should promote + snapshot
    promoted = False
    if not manager.get_pending():
        promoted = _try_promote(manager, root_path)

    return ApproveResult(
        approved_ids=approved,
        lockfile_path=str(manager.lockfile_path),
        promoted=promoted,
    )


def run_gate_reject(
    tool_ids: list[str],
    lockfile_path: str,
    *,
    reason: str | None = None,
) -> list[str]:
    """Reject tools in a lockfile. Returns list of rejected IDs."""
    manager = LockfileManager(lockfile_path)
    if not manager.exists():
        raise FileNotFoundError(f"No lockfile found at: {manager.lockfile_path}")

    manager.load()
    rejected: list[str] = []
    for tid in tool_ids:
        tool = manager.get_tool(tid)
        if tool:
            manager.reject(tool_id=tid, reason=reason)
            rejected.append(tid)
    manager.save()
    return rejected


def run_gate_snapshot(
    lockfile_path: str,
    root_path: str = ".toolwright",  # noqa: ARG001
) -> str | None:
    """Materialize baseline snapshot. Returns snapshot path or None."""
    manager = LockfileManager(lockfile_path)
    if not manager.exists():
        raise FileNotFoundError(f"No lockfile found at: {manager.lockfile_path}")

    manager.load()
    if manager.get_pending():
        raise ValueError("Cannot snapshot: pending tools exist")

    result = materialize_snapshot(lockfile_path=Path(lockfile_path))
    return str(result.snapshot_dir) if result.snapshot_dir else None


def load_lockfile_tools(lockfile_path: str) -> tuple[Lockfile, list[ToolApproval]]:
    """Load lockfile and return (lockfile, list of all tools)."""
    manager = LockfileManager(lockfile_path)
    if not manager.exists():
        raise FileNotFoundError(f"No lockfile found at: {manager.lockfile_path}")
    lockfile = manager.load()
    return lockfile, list(lockfile.tools.values())


def _try_promote(manager: LockfileManager, _root_path: str) -> bool:
    """Try to promote pending lockfile to approved + seed trust store."""
    try:
        lf_path = manager.lockfile_path
        if lf_path and "pending" in str(lf_path):
            approved_path = Path(str(lf_path).replace(".pending.", "."))
            if approved_path != lf_path:
                import shutil
                shutil.copy2(lf_path, approved_path)
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Status — new for TUI v2
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusModel:
    """Snapshot of governance state for a toolpack."""

    toolpack_id: str | None
    toolpack_path: str
    root: str
    lockfile_state: Literal["missing", "pending", "sealed", "stale"]
    lockfile_path: str | None
    approved_count: int
    blocked_count: int
    pending_count: int
    has_baseline: bool
    baseline_age_seconds: float | None
    drift_state: Literal["not_checked", "clean", "warnings", "breaking"]
    verification_state: Literal["not_run", "pass", "fail", "partial"]
    has_mcp_config: bool
    tool_count: int
    alerts: list[str]


def get_status(toolpack_path: str) -> StatusModel:
    """Build a governance status snapshot for a toolpack.

    Reads cached artifacts only — never runs drift/verify.
    """
    tp_path = Path(toolpack_path)
    toolpack = load_toolpack(tp_path)
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_path)
    toolpack_root = tp_path.resolve().parent

    # Determine root
    root = str(toolpack_root.parent) if toolpack_root.name != ".toolwright" else str(toolpack_root)

    # Toolpack identity
    toolpack_id = resolve_display_name(toolpack)

    # Tool count
    tool_count = 0
    if resolved.tools_path and resolved.tools_path.exists():
        try:
            tools_data = json.loads(resolved.tools_path.read_text())
            if isinstance(tools_data, dict):
                tool_count = len(tools_data.get("actions", []))
            elif isinstance(tools_data, list):
                tool_count = len(tools_data)
            else:
                tool_count = 0
        except Exception:
            pass

    # Lockfile state
    lockfile_path_resolved = resolved.approved_lockfile_path or resolved.pending_lockfile_path
    approved_count = 0
    blocked_count = 0
    pending_count = 0
    lockfile_state: Literal["missing", "pending", "sealed", "stale"] = "missing"

    if lockfile_path_resolved and lockfile_path_resolved.exists():
        try:
            manager = LockfileManager(lockfile_path_resolved)
            lockfile = manager.load()

            for tool in lockfile.tools.values():
                if tool.status == ApprovalStatus.PENDING:
                    pending_count += 1
                elif tool.status == ApprovalStatus.APPROVED:
                    approved_count += 1
                elif tool.status == ApprovalStatus.REJECTED:
                    blocked_count += 1

            if pending_count > 0:
                lockfile_state = "pending"
            else:
                # Check if artifacts digest matches (stale vs sealed)
                from toolwright.core.approval import compute_artifacts_digest_from_paths
                if all(
                    p.exists()
                    for p in [resolved.tools_path, resolved.toolsets_path, resolved.policy_path]
                    if p is not None
                ):
                    digest = compute_artifacts_digest_from_paths(
                        tools_path=resolved.tools_path,
                        toolsets_path=resolved.toolsets_path,
                        policy_path=resolved.policy_path,
                    )
                    if lockfile.artifacts_digest and lockfile.artifacts_digest != digest:
                        lockfile_state = "stale"
                    else:
                        lockfile_state = "sealed"
                else:
                    lockfile_state = "sealed"
        except Exception:
            lockfile_state = "missing"

    # Baseline
    has_baseline = bool(resolved.baseline_path and resolved.baseline_path.exists())
    baseline_age_seconds: float | None = None
    if has_baseline and resolved.baseline_path:
        import time
        baseline_age_seconds = time.time() - resolved.baseline_path.stat().st_mtime

    # Drift state — read cached report if it exists
    drift_state: Literal["not_checked", "clean", "warnings", "breaking"] = "not_checked"
    reports_dir = toolpack_root / "reports"
    if reports_dir.exists():
        drift_reports = sorted(reports_dir.glob("drift-*.json"), reverse=True)
        if drift_reports:
            try:
                report_data = json.loads(drift_reports[0].read_text())
                exit_code = report_data.get("exit_code", 0)
                if exit_code == 0:
                    drift_state = "clean"
                elif exit_code == 1:
                    drift_state = "warnings"
                else:
                    drift_state = "breaking"
            except Exception:
                pass

    # Verification state — read cached report
    verification_state: Literal["not_run", "pass", "fail", "partial"] = "not_run"
    if reports_dir.exists():
        verify_reports = sorted(reports_dir.glob("verify-*.json"), reverse=True)
        if verify_reports:
            try:
                report_data = json.loads(verify_reports[0].read_text())
                status = report_data.get("status", "unknown")
                if status == "pass":
                    verification_state = "pass"
                elif status == "fail":
                    verification_state = "fail"
                elif status == "partial":
                    verification_state = "partial"
            except Exception:
                pass

    # MCP config detection
    has_mcp_config = False
    for config_name in ("claude_desktop_config.json", "mcp.json", ".mcp.json"):
        if (Path(root) / config_name).exists():
            has_mcp_config = True
            break

    # Alerts
    alerts: list[str] = []
    if lockfile_state == "stale":
        alerts.append("Lockfile is stale — artifacts changed since last gate sync")
    if drift_state == "breaking":
        alerts.append("Breaking API surface changes detected")
    if verification_state == "fail":
        alerts.append("Verification contracts failing")

    return StatusModel(
        toolpack_id=toolpack_id,
        toolpack_path=toolpack_path,
        root=root,
        lockfile_state=lockfile_state,
        lockfile_path=str(lockfile_path_resolved) if lockfile_path_resolved else None,
        approved_count=approved_count,
        blocked_count=blocked_count,
        pending_count=pending_count,
        has_baseline=has_baseline,
        baseline_age_seconds=baseline_age_seconds,
        drift_state=drift_state,
        verification_state=verification_state,
        has_mcp_config=has_mcp_config,
        tool_count=tool_count,
        alerts=alerts,
    )


# ---------------------------------------------------------------------------
# Repair preflight — fast, focused checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreflightCheck:
    """A single preflight check result."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PreflightResult:
    """Repair preflight results — fast, focused on failure context."""

    checks: list[PreflightCheck]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def run_repair_preflight(toolpack_path: str) -> PreflightResult:
    """Run lightweight preflight checks relevant to repair context.

    Unlike full doctor, this only checks:
    - Toolpack path exists and is readable
    - Key artifact files exist
    - Lockfile exists
    - Permissions are ok
    """
    checks: list[PreflightCheck] = []
    tp = Path(toolpack_path)

    # Toolpack file exists
    if not tp.exists():
        checks.append(PreflightCheck(
            name="toolpack",
            passed=False,
            detail=f"Toolpack not found: {tp}",
        ))
        return PreflightResult(checks=checks)

    checks.append(PreflightCheck(
        name="toolpack",
        passed=True,
        detail=str(tp),
    ))

    # Readable
    try:
        load_toolpack(tp)
        checks.append(PreflightCheck(
            name="toolpack readable",
            passed=True,
            detail="valid YAML",
        ))
    except Exception as exc:
        checks.append(PreflightCheck(
            name="toolpack readable",
            passed=False,
            detail=f"Cannot parse toolpack: {exc}",
        ))
        return PreflightResult(checks=checks)

    resolved = resolve_toolpack_paths(toolpack=load_toolpack(tp), toolpack_path=toolpack_path)

    # Key artifacts
    for label, path in [
        ("tools.json", resolved.tools_path),
        ("policy.yaml", resolved.policy_path),
    ]:
        exists = path.exists() if path else False
        checks.append(PreflightCheck(
            name=label,
            passed=exists,
            detail=str(path) if exists else f"{label} missing",
        ))

    # Lockfile
    lockfile_path = resolved.approved_lockfile_path or resolved.pending_lockfile_path
    checks.append(PreflightCheck(
        name="lockfile",
        passed=bool(lockfile_path and lockfile_path.exists()),
        detail=str(lockfile_path) if lockfile_path and lockfile_path.exists() else "missing",
    ))

    return PreflightResult(checks=checks)


# ---------------------------------------------------------------------------
# Fingerprint — deterministic toolpack identity
# ---------------------------------------------------------------------------


def compute_fingerprint(toolpack_path: str) -> str:
    """Compute a deterministic fingerprint for a toolpack's key artifacts.

    Inputs hashed (when present):
    - toolpack.yaml
    - tools.json
    - policy.yaml
    - contracts.yaml
    - approved lockfile
    - baseline.json

    Returns a hex SHA-256 digest.  Same inputs always produce the same
    fingerprint, making stage-skipping deterministic and testable.
    """
    tp = Path(toolpack_path)
    toolpack = load_toolpack(tp)
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_path)

    h = hashlib.sha256()

    # Hash each artifact's content if it exists
    for path in [
        tp,
        resolved.tools_path,
        resolved.policy_path,
        resolved.baseline_path,
    ]:
        if path and path.exists():
            h.update(path.read_bytes())

    # Contracts (may be contracts.yaml or contracts.json)
    toolpack_root = tp.resolve().parent
    for contracts_name in ("contracts.yaml", "contracts.json"):
        cp = toolpack_root / contracts_name
        if cp.exists():
            h.update(cp.read_bytes())
            break

    # Approved lockfile
    if resolved.approved_lockfile_path and resolved.approved_lockfile_path.exists():
        h.update(resolved.approved_lockfile_path.read_bytes())

    # Toolsets
    if resolved.toolsets_path and resolved.toolsets_path.exists():
        h.update(resolved.toolsets_path.read_bytes())

    return h.hexdigest()


# ---------------------------------------------------------------------------
# List tools — per-toolpack tool listing for dashboard
# ---------------------------------------------------------------------------


def list_tools(toolpack_path: str) -> list[ToolApproval]:
    """Return all tools from the lockfile for a given toolpack.

    Reads the approved lockfile (falling back to pending).  Returns an
    empty list when no lockfile exists.  Never raises.
    """
    try:
        tp = Path(toolpack_path)
        toolpack = load_toolpack(tp)
        resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_path)

        lockfile_path = resolved.approved_lockfile_path or resolved.pending_lockfile_path
        if lockfile_path is None or not lockfile_path.exists():
            return []

        manager = LockfileManager(lockfile_path)
        lockfile = manager.load()
        return list(lockfile.tools.values())
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Display name resolution
# ---------------------------------------------------------------------------


def host_to_slug(host: str) -> str:
    """Convert a hostname to a short human-friendly slug.

    api.stripe.com  ->  stripe
    dummyjson.com   ->  dummyjson
    localhost       ->  localhost
    """
    # Strip port
    host = host.split(":")[0]
    # Split into parts
    parts = host.split(".")
    # Remove common prefixes/suffixes
    strip = {"api", "www", "rest", "v1", "v2", "com", "org", "net", "io", "dev", "co"}
    meaningful = [p for p in parts if p.lower() not in strip]
    return meaningful[0] if meaningful else parts[0]


def _host_slug(toolpack: Toolpack) -> str | None:
    """Derive a short display name from the toolpack's first allowed host."""
    if not toolpack.allowed_hosts:
        return None
    return host_to_slug(toolpack.allowed_hosts[0])


def resolve_display_name(toolpack: Toolpack) -> str:
    """Resolve the best human-friendly display name for a toolpack.

    Resolution order:
    1. display_name (explicitly set by user)
    2. origin.name (session name from capture)
    3. Host-derived slug (from allowed_hosts)
    4. toolpack_id (stable fallback)
    """
    if toolpack.display_name and toolpack.display_name.strip():
        return toolpack.display_name.strip()
    if toolpack.origin and toolpack.origin.name and toolpack.origin.name.strip():
        return toolpack.origin.name.strip()
    slug = _host_slug(toolpack)
    if slug:
        return slug
    return toolpack.toolpack_id
