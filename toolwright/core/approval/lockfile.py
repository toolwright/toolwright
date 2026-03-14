"""Lockfile management for tool approvals.

The lockfile (toolwright.lock.yaml) tracks:
- Tool versions and signatures
- Approval status (pending, approved, rejected)
- Who approved and when
- Drift between versions

This enables:
- CI to fail on unapproved tools
- Human-in-the-loop approval workflow
- Version tracking over time
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from toolwright.utils.schema_version import (
    CURRENT_SCHEMA_VERSION,
    resolve_generated_at,
    resolve_schema_version,
)


class ApprovalStatus(StrEnum):
    """Status of a tool approval."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolApproval(BaseModel):
    """Approval record for a single tool."""

    # Tool identity
    tool_id: str
    tool_version: int = 1
    signature_id: str
    endpoint_id: str | None = None

    # Tool metadata
    name: str
    method: str
    path: str
    host: str
    risk_tier: str = "low"
    toolsets: list[str] = Field(default_factory=list)
    approved_toolsets: list[str] = Field(default_factory=list)

    # Approval status
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_at: datetime | None = None
    approved_by: str | None = None
    approval_reason: str | None = None
    approval_signature: str | None = None
    approval_alg: str | None = None
    approval_key_id: str | None = None
    approval_mode: str = "1-of-1"
    rejection_reason: str | None = None

    # Change tracking
    previous_signature: str | None = None
    changed_at: datetime | None = None
    change_type: str | None = None  # "new", "modified", "risk_changed"


class Lockfile(BaseModel):
    """The toolwright.lock.yaml file structure."""

    version: str = "1.0.0"
    schema_version: str = CURRENT_SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    capture_id: str | None = None
    scope: str | None = None
    artifacts_digest: str | None = None
    evidence_summary_sha256: str | None = None
    baseline_snapshot_dir: str | None = None
    baseline_snapshot_digest: str | None = None
    baseline_snapshot_id: str | None = None

    # Tool approvals indexed by tool_id
    tools: dict[str, ToolApproval] = Field(default_factory=dict)

    # Summary stats
    total_tools: int = 0
    approved_count: int = 0
    pending_count: int = 0
    rejected_count: int = 0


class LockfileManager:
    """Manage tool approvals in a lockfile.

    The lockfile enables:
    - Tracking tool versions over time
    - Requiring approval for new/changed tools
    - CI integration (fail on unapproved)
    - Audit trail of approvals
    """

    DEFAULT_FILENAME = "toolwright.lock.yaml"

    def __init__(self, lockfile_path: str | Path | None = None) -> None:
        """Initialize the lockfile manager.

        Args:
            lockfile_path: Path to lockfile (default: ./toolwright.lock.yaml)
        """
        if lockfile_path:
            self.lockfile_path = Path(lockfile_path)
        else:
            self.lockfile_path = Path.cwd() / self.DEFAULT_FILENAME

        self.lockfile: Lockfile | None = None

    def exists(self) -> bool:
        """Return True when the lockfile exists."""
        return self.lockfile_path.exists()

    def load(self) -> Lockfile:
        """Load the lockfile from disk.

        Returns:
            Loaded lockfile (or empty if doesn't exist)
        """
        if self.lockfile_path.exists():
            with open(self.lockfile_path) as f:
                data = yaml.safe_load(f)
                if data:
                    schema_version = resolve_schema_version(
                        data,
                        artifact="lockfile",
                        allow_legacy=True,
                    )
                    # Convert tools dict to ToolApproval objects
                    tools: dict[str, ToolApproval] = {}
                    for tool_id, tool_data in data.get("tools", {}).items():
                        tool = ToolApproval(**tool_data)
                        key = self._approval_key(
                            tool.signature_id,
                            fallback=tool.tool_id or tool.name or tool_id,
                        )
                        # Keep first-seen record if duplicate keys appear.
                        tools.setdefault(key, tool)
                    data["tools"] = tools
                    data["schema_version"] = schema_version
                    self.lockfile = Lockfile(**data)
                else:
                    self.lockfile = Lockfile()
        else:
            self.lockfile = Lockfile()

        return self.lockfile

    def save(self) -> None:
        """Save the lockfile to disk."""
        if self.lockfile is None:
            self.lockfile = Lockfile()

        for tool in self.lockfile.tools.values():
            tool.toolsets = sorted(set(tool.toolsets))
            tool.approved_toolsets = sorted(set(tool.approved_toolsets))

        # Update counts
        self._update_counts()

        # Convert to dict for YAML serialization
        data = self.lockfile.model_dump(mode="json")
        data["tools"] = self._sorted_tools_payload(data.get("tools", {}))

        # Convert datetime objects to ISO strings
        if data.get("generated_at"):
            data["generated_at"] = self.lockfile.generated_at.isoformat()

        for _tool_id, tool in data.get("tools", {}).items():
            if tool.get("approved_at"):
                tool["approved_at"] = tool["approved_at"]
            if tool.get("changed_at"):
                tool["changed_at"] = tool["changed_at"]

        from toolwright.utils.files import atomic_write_text

        atomic_write_text(
            self.lockfile_path,
            yaml.dump(data, default_flow_style=False, sort_keys=False),
        )

    def _sorted_tools_payload(self, tools: dict[str, Any]) -> dict[str, Any]:
        """Return tool payload sorted by tool_id for deterministic diffs."""
        return {tool_id: tools[tool_id] for tool_id in sorted(tools)}

    def _approval_key(self, signature_id: str | None, fallback: str) -> str:
        """Build the canonical lockfile key (signature-first)."""
        signature = (signature_id or "").strip()
        return signature if signature else fallback

    def _resolve_tool_key(self, identifier: str) -> str | None:
        """Resolve a lockfile entry by key, signature, tool_id, or display name."""
        if self.lockfile is None:
            self.load()
        assert self.lockfile is not None

        if identifier in self.lockfile.tools:
            return identifier

        for key, tool in self.lockfile.tools.items():
            if identifier in {tool.signature_id, tool.tool_id, tool.name}:
                return key

        return None

    def get_tool(self, identifier: str) -> ToolApproval | None:
        """Get a tool approval by key, signature, tool_id, or display name."""
        key = self._resolve_tool_key(identifier)
        if key is None:
            return None
        assert self.lockfile is not None
        return self.lockfile.tools.get(key)

    def _update_counts(self) -> None:
        """Update summary counts in lockfile."""
        if self.lockfile is None:
            return

        self.lockfile.total_tools = len(self.lockfile.tools)
        self.lockfile.approved_count = sum(
            1 for t in self.lockfile.tools.values() if t.status == ApprovalStatus.APPROVED
        )
        self.lockfile.pending_count = sum(
            1 for t in self.lockfile.tools.values() if t.status == ApprovalStatus.PENDING
        )
        self.lockfile.rejected_count = sum(
            1 for t in self.lockfile.tools.values() if t.status == ApprovalStatus.REJECTED
        )

    def set_artifacts_digest(self, artifacts_digest: str) -> None:
        """Set integrity digest for governed runtime artifacts."""
        if self.lockfile is None:
            self.load()
        assert self.lockfile is not None
        self.lockfile.artifacts_digest = artifacts_digest

    def set_evidence_summary_sha256(self, digest: str | None) -> None:
        """Set evidence summary hash for verification governance."""
        if self.lockfile is None:
            self.load()
        assert self.lockfile is not None
        self.lockfile.evidence_summary_sha256 = digest

    def set_baseline_snapshot(self, snapshot_dir: str, snapshot_digest: str) -> None:
        """Set baseline snapshot metadata for governance."""
        if self.lockfile is None:
            self.load()
        assert self.lockfile is not None
        self.lockfile.baseline_snapshot_dir = snapshot_dir
        self.lockfile.baseline_snapshot_digest = snapshot_digest
        self.lockfile.baseline_snapshot_id = f"appr_{snapshot_digest[:12]}"

    def sync_from_manifest(
        self,
        manifest: dict[str, Any],
        capture_id: str | None = None,
        scope: str | None = None,
        toolsets: dict[str, Any] | None = None,
        deterministic: bool = False,
        prune_removed: bool = False,
    ) -> dict[str, list[str]]:
        """Sync lockfile with a tools manifest.

        Compares the manifest against the lockfile and:
        - Adds new tools as pending
        - Marks changed tools for re-approval
        - Tracks removed tools

        Args:
            manifest: Tools manifest dict (from tools.json)
            capture_id: Optional capture ID
            scope: Optional scope name
            toolsets: Optional toolsets artifact payload (from toolsets.yaml)
            deterministic: If True, use deterministic timestamps
            prune_removed: If True, remove tools no longer present in the manifest

        Returns:
            Dict with lists of: new, modified, removed, unchanged tool IDs
        """
        if self.lockfile is None:
            self.load()

        assert self.lockfile is not None

        # Update metadata
        sync_time = resolve_generated_at(deterministic=deterministic)
        self.lockfile.generated_at = sync_time
        if capture_id:
            self.lockfile.capture_id = capture_id
        if scope:
            self.lockfile.scope = scope

        # Track changes
        changes: dict[str, list[str]] = {
            "new": [],
            "modified": [],
            "removed": [],
            "unchanged": [],
        }

        manifest_actions: list[dict[str, Any]] = manifest.get("actions", [])
        toolsets_by_action = self._build_toolset_lookup(toolsets)
        existing_tools = self.lockfile.tools
        original_existing_keys = set(existing_tools.keys())

        existing_by_signature: dict[str, str] = {}
        existing_by_endpoint: dict[str, str] = {}
        existing_by_name: dict[str, str] = {}
        existing_by_tool_id: dict[str, str] = {}
        for key, tool in existing_tools.items():
            if tool.signature_id:
                existing_by_signature[tool.signature_id] = key
            if tool.endpoint_id:
                existing_by_endpoint[tool.endpoint_id] = key
            existing_by_name[tool.name] = key
            existing_by_tool_id[tool.tool_id] = key

        matched_existing_keys: set[str] = set()

        for action in sorted(
            manifest_actions,
            key=lambda item: (
                str(item.get("host", "")),
                str(item.get("method", "")).upper(),
                str(item.get("path", "")),
                str(item.get("signature_id", "")),
                str(item.get("name", "")),
            ),
        ):
            action_name = action["name"]
            action_signature = str(action.get("signature_id", ""))
            action_endpoint_id = action.get("endpoint_id")
            action_tool_id = str(action.get("tool_id", action_signature or action_name))
            action_toolsets = sorted(toolsets_by_action.get(action_name, set()))
            action_key = self._approval_key(action_signature, fallback=action_name)

            existing_key: str | None = None
            if action_signature and action_signature in existing_by_signature:
                existing_key = existing_by_signature[action_signature]
            elif action_tool_id in existing_by_tool_id:
                existing_key = existing_by_tool_id[action_tool_id]
            elif (
                not action_signature
                and action_endpoint_id
                and action_endpoint_id in existing_by_endpoint
            ):
                existing_key = existing_by_endpoint[action_endpoint_id]
            elif action_name in existing_by_name:
                existing_key = existing_by_name[action_name]

            if existing_key is None:
                existing_tools[action_key] = ToolApproval(
                    tool_id=action_tool_id,
                    tool_version=1,
                    signature_id=action_signature,
                    endpoint_id=action_endpoint_id,
                    name=action_name,
                    method=action.get("method", "GET"),
                    path=action.get("path", "/"),
                    host=action.get("host", ""),
                    risk_tier=action.get("risk_tier", "low"),
                    toolsets=action_toolsets,
                    approved_toolsets=[],
                    status=ApprovalStatus.PENDING,
                    change_type="new",
                    changed_at=sync_time,
                )
                changes["new"].append(action_name)
                if action_signature:
                    existing_by_signature[action_signature] = action_key
                existing_by_tool_id[action_tool_id] = action_key
                if action_endpoint_id:
                    existing_by_endpoint[action_endpoint_id] = action_key
                existing_by_name[action_name] = action_key
                continue

            matched_existing_keys.add(existing_key)
            existing = existing_tools[existing_key]

            if action_signature and existing_key != action_key and action_key not in existing_tools:
                existing_tools[action_key] = existing
                del existing_tools[existing_key]
                existing_key = action_key
                existing_by_signature[action_signature] = action_key

            was_modified = False
            if action_signature and action_signature != existing.signature_id:
                existing.previous_signature = existing.signature_id
                existing.signature_id = action_signature
                existing.tool_version += 1
                existing.status = ApprovalStatus.PENDING
                existing.change_type = "modified"
                existing.changed_at = sync_time
                existing.approved_at = None
                existing.approved_by = None
                was_modified = True

            new_risk = action.get("risk_tier", "low")
            if self._risk_escalated(existing.risk_tier, new_risk):
                existing.status = ApprovalStatus.PENDING
                existing.change_type = "risk_changed"
                existing.changed_at = sync_time
                existing.approved_at = None
                existing.approved_by = None
                existing.approved_toolsets = []
                was_modified = True

            previous_toolsets = set(existing.toolsets)
            next_toolsets = set(action_toolsets)
            if previous_toolsets != next_toolsets:
                # Preserve approvals only for still-member toolsets; new memberships require approval.
                existing.approved_toolsets = sorted(
                    ts for ts in existing.approved_toolsets if ts in next_toolsets
                )
                existing.toolsets = action_toolsets
                if next_toolsets and not next_toolsets.issubset(set(existing.approved_toolsets)):
                    existing.status = ApprovalStatus.PENDING
                    existing.change_type = "modified"
                    existing.changed_at = sync_time
                    existing.approved_at = None
                    existing.approved_by = None
                    was_modified = True
            else:
                existing.toolsets = action_toolsets

            existing.risk_tier = new_risk
            existing.name = action_name
            existing.tool_id = action_tool_id
            existing.method = action.get("method", existing.method)
            existing.path = action.get("path", existing.path)
            existing.host = action.get("host", existing.host)
            existing.endpoint_id = action_endpoint_id
            existing.approved_toolsets = sorted(set(existing.approved_toolsets))
            existing_by_name[action_name] = existing_key
            existing_by_tool_id[action_tool_id] = existing_key

            if was_modified:
                changes["modified"].append(action_name)
            else:
                changes["unchanged"].append(action_name)

        removed_keys = sorted(original_existing_keys - matched_existing_keys)
        for key in removed_keys:
            removed_tool = existing_tools.get(key)
            if removed_tool:
                changes["removed"].append(removed_tool.name)
            if prune_removed:
                existing_tools.pop(key, None)

        self.lockfile.tools = {
            tool_id: self.lockfile.tools[tool_id]
            for tool_id in sorted(self.lockfile.tools)
        }
        for change_type in changes:
            changes[change_type].sort()

        return changes

    def _build_toolset_lookup(
        self,
        toolsets: dict[str, Any] | None,
    ) -> dict[str, set[str]]:
        """Build action -> set(toolset names) lookup from toolsets artifact."""
        lookup: dict[str, set[str]] = {}
        if not toolsets:
            return lookup

        for toolset_name, payload in sorted(toolsets.get("toolsets", {}).items()):
            for action_name in payload.get("actions", []):
                lookup.setdefault(str(action_name), set()).add(str(toolset_name))
        return lookup

    def _risk_escalated(self, old_risk: str, new_risk: str) -> bool:
        """Check if risk tier escalated."""
        risk_levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        old_level = risk_levels.get(old_risk, 0)
        new_level = risk_levels.get(new_risk, 0)
        return new_level > old_level

    def _default_approval_root(self) -> Path:
        """Resolve canonical root for approval signing key material.

        Search order:
        1. TOOLWRIGHT_ROOT env var
        2. .toolwright ancestor in the lockfile path
        3. Toolpack-local .toolwright (next to toolpack.yaml)
        4. .toolwright sibling to lockfile directory
        """
        from toolwright.core.approval.signing import resolve_approval_root

        # When lockfiles live outside a `.toolwright` tree (exports, temp dirs, tests),
        # default to a sibling `.toolwright` root next to the lockfile for portability.
        fallback = self.lockfile_path.parent / ".toolwright" / "state" / "confirmations.db"
        resolved = resolve_approval_root(
            lockfile_path=self.lockfile_path,
            fallback_root=fallback,
        )

        # If the resolved path has no trust store, check for toolpack-local trust store.
        trust_store = resolved / "state" / "keys" / "trusted_signers.json"
        if not trust_store.exists():
            from toolwright.core.approval.snapshot import resolve_toolpack_root

            toolpack_root = resolve_toolpack_root(self.lockfile_path)
            if toolpack_root is not None:
                toolpack_trust_root = toolpack_root / ".toolwright"
                toolpack_trust_store = (
                    toolpack_trust_root / "state" / "keys" / "trusted_signers.json"
                )
                if toolpack_trust_store.exists():
                    return toolpack_trust_root

        return resolved

    def approve(
        self,
        tool_id: str,
        approved_by: str | None = None,
        toolset: str | None = None,
        reason: str | None = None,
        approval_signature: str | None = None,
        approval_alg: str | None = None,
        approval_key_id: str | None = None,
        approved_at: datetime | None = None,
    ) -> bool:
        """Approve a tool.

        Args:
            tool_id: Tool ID to approve
            approved_by: Who is approving (default: current user)
            toolset: Optional toolset name for scoped approval

        Returns:
            True if approved, False if tool not found
        """
        if self.lockfile is None:
            self.load()

        assert self.lockfile is not None

        resolved_tool_id = self._resolve_tool_key(tool_id)
        if resolved_tool_id is None:
            return False

        tool = self.lockfile.tools[resolved_tool_id]
        actor = approved_by if approved_by is not None else (os.environ.get("USER") or "unknown")
        approval_time = approved_at or datetime.now(UTC)

        if toolset:
            if toolset not in tool.toolsets:
                return False
            approved_toolsets = set(tool.approved_toolsets)
            approved_toolsets.add(toolset)
            tool.approved_toolsets = sorted(approved_toolsets)
            if set(tool.toolsets).issubset(approved_toolsets):
                tool.status = ApprovalStatus.APPROVED
            elif tool.status == ApprovalStatus.REJECTED:
                tool.status = ApprovalStatus.PENDING
        else:
            tool.status = ApprovalStatus.APPROVED
            tool.approved_toolsets = sorted(set(tool.toolsets))

        tool.rejection_reason = None
        tool.approved_at = approval_time
        tool.approved_by = actor
        tool.approval_reason = reason

        if approval_signature is None:
            from toolwright.core.approval.signing import ApprovalSigner

            signer = ApprovalSigner(root_path=self._default_approval_root())
            approval_signature = signer.sign_approval(
                tool=tool,
                approved_by=actor,
                approved_at=approval_time,
                reason=reason,
                mode=tool.approval_mode,
            )
            approval_alg = signer.algorithm
            approval_key_id = signer.key_id

        tool.approval_signature = approval_signature
        tool.approval_alg = approval_alg
        tool.approval_key_id = approval_key_id

        return True

    def approve_all(
        self,
        approved_by: str | None = None,
        toolset: str | None = None,
        reason: str | None = None,
    ) -> int:
        """Approve all pending tools.

        Args:
            approved_by: Who is approving
            toolset: Optional toolset name for scoped approvals

        Returns:
            Number of tools approved
        """
        if self.lockfile is None:
            self.load()

        assert self.lockfile is not None

        count = 0
        for tool_id, tool in self.lockfile.tools.items():
            if toolset and toolset not in tool.toolsets:
                continue
            if toolset:
                if toolset in tool.approved_toolsets:
                    continue
                if self.approve(tool_id, approved_by, toolset=toolset, reason=reason):
                    count += 1
                continue
            if tool.status == ApprovalStatus.PENDING:
                self.approve(tool_id, approved_by, toolset=None, reason=reason)
                count += 1

        return count

    def reject(
        self,
        tool_id: str,
        reason: str | None = None,
    ) -> bool:
        """Reject a tool.

        Args:
            tool_id: Tool ID to reject
            reason: Reason for rejection

        Returns:
            True if rejected, False if tool not found
        """
        if self.lockfile is None:
            self.load()

        assert self.lockfile is not None

        resolved_tool_id = self._resolve_tool_key(tool_id)
        if resolved_tool_id is None:
            return False

        tool = self.lockfile.tools[resolved_tool_id]
        tool.status = ApprovalStatus.REJECTED
        tool.approved_toolsets = []
        tool.rejection_reason = reason
        tool.approved_at = None
        tool.approved_by = None
        tool.approval_reason = None
        tool.approval_signature = None

        return True

    def get_pending(self, toolset: str | None = None) -> list[ToolApproval]:
        """Get all pending tool approvals.

        Returns:
            List of pending tools
        """
        if self.lockfile is None:
            self.load()

        assert self.lockfile is not None

        if toolset:
            pending = [
                t
                for t in self.lockfile.tools.values()
                if toolset in t.toolsets and toolset not in t.approved_toolsets
            ]
        else:
            pending = [t for t in self.lockfile.tools.values() if t.status == ApprovalStatus.PENDING]
        return sorted(pending, key=lambda t: (t.name, t.method, t.path))

    def get_approved(self) -> list[ToolApproval]:
        """Get all approved tools.

        Returns:
            List of approved tools
        """
        if self.lockfile is None:
            self.load()

        assert self.lockfile is not None

        approved = [t for t in self.lockfile.tools.values() if t.status == ApprovalStatus.APPROVED]
        return sorted(approved, key=lambda t: (t.name, t.method, t.path))

    def has_pending(self, toolset: str | None = None) -> bool:
        """Check if there are pending approvals.

        Returns:
            True if any tools are pending
        """
        return len(self.get_pending(toolset=toolset)) > 0

    def verify_signatures(
        self,
        root_path: str | Path | None = None,
    ) -> tuple[bool, str]:
        """Verify Ed25519 signatures for all approved tools in the lockfile.

        Returns:
            Tuple of (all_valid, message). On failure, message names the
            first tool whose signature is invalid and suggests a recovery action.
        """
        if self.lockfile is None:
            self.load()
        assert self.lockfile is not None

        from toolwright.core.approval.signing import ApprovalSigner

        resolved_root = Path(root_path) if root_path else self._default_approval_root()

        try:
            signer = ApprovalSigner(root_path=resolved_root, read_only=True)
        except Exception:
            return False, (
                "Lockfile integrity check failed: unable to load signing trust store. "
                "Run 'toolwright gate sync' to regenerate."
            )

        failed_tools: list[str] = []
        for tool in self.lockfile.tools.values():
            if tool.status != ApprovalStatus.APPROVED:
                continue

            if not tool.approval_signature:
                failed_tools.append(tool.name)
                continue

            if not tool.approved_by or tool.approved_at is None:
                failed_tools.append(tool.name)
                continue

            valid = signer.verify_approval(
                tool=tool,
                approved_by=str(tool.approved_by),
                approved_at=tool.approved_at,
                reason=tool.approval_reason,
                mode=tool.approval_mode,
                signature=str(tool.approval_signature),
            )
            if not valid:
                failed_tools.append(tool.name)

        if failed_tools:
            names = ", ".join(failed_tools[:5])
            suffix = f" (and {len(failed_tools) - 5} more)" if len(failed_tools) > 5 else ""
            return False, (
                f"Lockfile integrity check failed: signature mismatch for tool "
                f"'{names}'{suffix}. Run 'toolwright gate sync' to regenerate."
            )

        return True, "All approval signatures verified"

    def check_approvals(self, toolset: str | None = None) -> tuple[bool, str]:
        """Check approval state (status only, no cryptographic verification).

        For full integrity checking including Ed25519 signature verification,
        use ``check_ci()`` or call ``verify_signatures()`` explicitly.
        """
        if self.lockfile is None:
            self.load()

        assert self.lockfile is not None

        if toolset:
            in_toolset = [t for t in self.lockfile.tools.values() if toolset in t.toolsets]
            rejected = [t for t in in_toolset if t.status == ApprovalStatus.REJECTED]
            pending = [t for t in in_toolset if toolset not in t.approved_toolsets]

            if not in_toolset:
                return True, f"No tools in toolset '{toolset}'"

            if rejected:
                tool_names = [t.name for t in rejected]
                return False, f"Rejected tools in '{toolset}': {', '.join(tool_names)}"

            if pending:
                tool_names = [t.name for t in pending]
                return False, f"Pending approval in '{toolset}': {', '.join(tool_names)}"

            return True, f"All tools approved in '{toolset}'"

        pending = self.get_pending()
        rejected = [t for t in self.lockfile.tools.values() if t.status == ApprovalStatus.REJECTED]

        if rejected:
            tool_names = [t.name for t in rejected]
            return False, f"Rejected tools: {', '.join(tool_names)}"

        if pending:
            tool_names = [t.name for t in pending]
            return False, f"Pending approval: {', '.join(tool_names)}"

        return True, "All tools approved"

    def check_ci(self, toolset: str | None = None) -> tuple[bool, str]:
        """Check if CI should pass.

        Performs status checks, Ed25519 signature verification, snapshot
        validation, and evidence summary checks.

        Returns:
            Tuple of (should_pass, message)
        """
        approvals_passed, message = self.check_approvals(toolset=toolset)
        if not approvals_passed:
            return False, message

        if self.lockfile is None:
            self.load()
        assert self.lockfile is not None

        if not self.lockfile.baseline_snapshot_dir or not self.lockfile.baseline_snapshot_digest:
            return False, "baseline snapshot missing; run toolwright gate snapshot"

        from toolwright.core.approval.snapshot import (
            load_snapshot_digest,
            resolve_toolpack_root,
        )
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

        toolpack_root = resolve_toolpack_root(self.lockfile_path)
        if toolpack_root is None:
            return False, "toolpack.yaml not found; check_ci requires toolpack context"

        # Verify Ed25519 signatures for all approved tools.
        # Try toolpack-local trust store first (seeded by `gate allow`),
        # then fall back to default approval root resolution.
        toolpack_trust_root = toolpack_root / ".toolwright"
        toolpack_trust_store = toolpack_trust_root / "state" / "keys" / "trusted_signers.json"
        if toolpack_trust_store.exists():
            sig_passed, sig_message = self.verify_signatures(root_path=toolpack_trust_root)
            if not sig_passed:
                # Toolpack trust store may be stale; try default root as fallback.
                sig_passed2, sig_message2 = self.verify_signatures()
                if not sig_passed2:
                    return False, sig_message
        else:
            sig_passed, sig_message = self.verify_signatures()
            if not sig_passed:
                return False, sig_message

        snapshot_dir = toolpack_root / self.lockfile.baseline_snapshot_dir
        try:
            digest = load_snapshot_digest(snapshot_dir)
        except Exception:
            return False, "baseline snapshot missing; run toolwright gate snapshot"
        if digest != self.lockfile.baseline_snapshot_digest:
            return False, "baseline snapshot digest mismatch; re-run toolwright gate snapshot"

        toolpack_file = toolpack_root / "toolpack.yaml"
        try:
            toolpack = load_toolpack(toolpack_file)
        except Exception:
            return False, "toolpack.yaml invalid; check_ci requires toolpack context"
        resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_file)

        expected_hash = self.lockfile.evidence_summary_sha256
        if expected_hash:
            actual_hash = None
            sha_path = resolved.evidence_summary_sha256_path
            if sha_path and sha_path.exists():
                actual_hash = sha_path.read_text().strip()
            if actual_hash != expected_hash:
                return False, "evidence summary hash mismatch; re-run verification"

        return True, f"{message} with verified baseline snapshot"

    def to_yaml(self) -> str:
        """Serialize lockfile to YAML string.

        Returns:
            YAML string
        """
        if self.lockfile is None:
            self.load()

        assert self.lockfile is not None

        self._update_counts()
        data = self.lockfile.model_dump(mode="json")
        data["tools"] = self._sorted_tools_payload(data.get("tools", {}))
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
