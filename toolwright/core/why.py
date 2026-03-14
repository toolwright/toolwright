"""Explain governance decisions in plain English."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Explanation:
    """An explanation of a governance decision."""

    tool_name: str
    status: str  # approved, pending, rejected, unknown, not_in_lockfile
    reasons: list[str]
    timeline: list[str]  # chronological events
    next_steps: list[str]


def explain_tool(
    *,
    tool_name: str,
    toolpack_path: str | Path,
    root: Path,
) -> Explanation:
    """Explain the governance state and decisions for a specific tool."""
    from toolwright.core.approval.lockfile import ApprovalStatus, LockfileManager
    from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths

    tp_path = Path(toolpack_path)
    toolpack = load_toolpack(tp_path)
    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=tp_path)

    reasons: list[str] = []
    timeline: list[str] = []
    next_steps: list[str] = []
    status = "unknown"

    # Check if tool exists in tools.json
    tools_path = resolved.tools_path
    tool_exists = False
    if tools_path and tools_path.exists():
        data = json.loads(tools_path.read_text())
        tool_names = [a.get("name") for a in data.get("actions", [])]
        if tool_name in tool_names:
            tool_exists = True
            timeline.append(f"Tool '{tool_name}' found in tools manifest")
        else:
            reasons.append(f"Tool '{tool_name}' not found in tools manifest")
            # Try fuzzy match
            close = [
                n
                for n in tool_names
                if tool_name.lower() in n.lower() or n.lower() in tool_name.lower()
            ]
            if close:
                next_steps.append(f"Did you mean: {', '.join(close[:3])}?")
            else:
                next_steps.append(f"Available tools: {', '.join(sorted(tool_names)[:10])}")
            return Explanation(
                tool_name=tool_name,
                status="unknown",
                reasons=reasons,
                timeline=timeline,
                next_steps=next_steps,
            )

    # Check lockfile status
    lockfile_path = resolved.approved_lockfile_path or resolved.pending_lockfile_path
    if lockfile_path and lockfile_path.exists():
        try:
            manager = LockfileManager(lockfile_path)
            manager.load()
            tool_approval = manager.get_tool(tool_name)
            if tool_approval:
                status = tool_approval.status.value
                timeline.append(f"Lockfile status: {status}")

                if tool_approval.status == ApprovalStatus.APPROVED:
                    reasons.append("Tool was reviewed and approved")
                    if tool_approval.approved_at:
                        timeline.append(f"Approved at: {tool_approval.approved_at}")
                    if tool_approval.approved_by:
                        timeline.append(f"Approved by: {tool_approval.approved_by}")
                    if tool_approval.approval_reason:
                        reasons.append(f"Reason: {tool_approval.approval_reason}")
                elif tool_approval.status == ApprovalStatus.PENDING:
                    reasons.append("Tool is awaiting human review")
                    reasons.append("Pending tools are not served to MCP clients")
                    next_steps.append("Run 'toolwright gate allow' to approve this tool")
                elif tool_approval.status == ApprovalStatus.REJECTED:
                    reasons.append("Tool was explicitly rejected by a reviewer")
                    if tool_approval.rejection_reason:
                        reasons.append(f"Rejection reason: {tool_approval.rejection_reason}")
                    reasons.append("Rejected tools are never served to MCP clients")
                    next_steps.append("Run 'toolwright gate allow <tool>' to reconsider")

                if tool_approval.risk_tier:
                    reasons.append(f"Risk tier: {tool_approval.risk_tier}")
                if tool_approval.change_type:
                    timeline.append(f"Change type: {tool_approval.change_type}")
            else:
                status = "not_in_lockfile"
                reasons.append("Tool exists in manifest but has no lockfile entry")
                next_steps.append("Run 'toolwright compile' to generate lockfile entries")
        except Exception as e:
            reasons.append(f"Could not read lockfile: {e}")
    else:
        reasons.append("No lockfile found -- governance not yet initialized")
        next_steps.append("Run 'toolwright gate allow' to create a lockfile")

    # Check audit log for recent events about this tool
    try:
        from toolwright.core.reconcile.event_log import ReconcileEventLog

        log = ReconcileEventLog(str(root))
        if log.log_path.exists():
            events = log.events_for_tool(tool_name, n=5)
            for event in events:
                ts = event.get("timestamp", "")[:19]
                kind = event.get("kind", "unknown")
                desc = event.get("description", "")
                timeline.append(f"[{ts}] {kind}: {desc}")
    except Exception:
        pass  # Audit log is optional

    if not next_steps and status == "approved":
        next_steps.append("This tool is ready to use. Run 'toolwright serve' to start.")

    return Explanation(
        tool_name=tool_name,
        status=status,
        reasons=reasons,
        timeline=timeline,
        next_steps=next_steps,
    )
