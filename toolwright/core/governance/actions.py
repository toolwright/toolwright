"""Action handlers for the Toolwright Control Plane console.

All POST action handlers follow the critical pattern:
1. Look up WorkItem (404 if not found)
2. Check idempotent (200 if already in target state)
3. Check conflict (409 if already terminal in different state)
4. Perform side effect FIRST (e.g., confirmation_store.grant())
5. If side effect fails, return 500 — WorkItem stays OPEN
6. Resolve WorkItem to terminal state
7. Publish event
"""

from __future__ import annotations

import logging
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from toolwright.core.governance.event_store import ConsoleEvent, EventStore
from toolwright.models.work_item import WorkItemKind, WorkItemStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared context — set by http_transport at startup
# ---------------------------------------------------------------------------


class ActionContext:
    """Holds references to subsystems needed by action handlers."""

    def __init__(
        self,
        event_store: EventStore,
        lockfile_manager: Any = None,
        confirmation_store: Any = None,
        circuit_breaker: Any = None,
        rule_engine: Any = None,
    ) -> None:
        self.event_store = event_store
        self.lockfile_manager = lockfile_manager
        self.confirmation_store = confirmation_store
        self.circuit_breaker = circuit_breaker
        self.rule_engine = rule_engine


# Module-level context set by http_transport
_ctx: ActionContext | None = None


def set_context(ctx: ActionContext) -> None:
    global _ctx
    _ctx = ctx


def _get_ctx() -> ActionContext:
    if _ctx is None:
        raise RuntimeError("ActionContext not initialized")
    return _ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(msg: str, status: int = 400, **extra: Any) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg, **extra}, status_code=status)


def _publish_resolution_event(
    event_store: EventStore,
    event_type: str,
    severity: str,
    summary: str,
    tool_id: str | None = None,
    work_item_id: str | None = None,
) -> None:
    event_store.publish_event(
        ConsoleEvent(
            id="",
            timestamp=time.time(),
            event_type=event_type,
            severity=severity,
            summary=summary,
            tool_id=tool_id,
            work_item_id=work_item_id,
        )
    )


# ---------------------------------------------------------------------------
# POST /api/act/gate/allow — Bulk tool approval
# ---------------------------------------------------------------------------


async def handle_gate_allow(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    tool_ids = data.get("tool_ids", [])
    if not tool_ids:
        return _error("tool_ids required")

    results = []
    for tool_id in tool_ids:
        item_id = f"wi_approval_{tool_id}"
        item = ctx.event_store.get_work_item(item_id)

        if item is None:
            results.append({"tool_id": tool_id, "ok": False, "error": "not_found"})
            continue

        if item.status == WorkItemStatus.APPROVED:
            results.append({"tool_id": tool_id, "ok": True, "work_item": item.to_dict()})
            continue

        if item.is_terminal():
            results.append({
                "tool_id": tool_id, "ok": False, "error": "conflict",
                "message": f"Already {item.status.value}",
                "work_item": item.to_dict(),
            })
            continue

        # Side effect: approve in lockfile
        try:
            if ctx.lockfile_manager:
                ctx.lockfile_manager.approve(tool_id, approved_by="console")
                ctx.lockfile_manager.save()
        except Exception as e:
            logger.exception("Failed to approve %s", tool_id)
            results.append({"tool_id": tool_id, "ok": False, "error": "action_failed", "message": str(e)})
            continue

        # Resolve
        resolved, _ = await ctx.event_store.resolve_work_item(
            item_id, WorkItemStatus.APPROVED, resolved_by="console", reason="Approved via console"
        )
        assert resolved is not None

        _publish_resolution_event(
            ctx.event_store, "tool_approved", "success",
            f"Tool approved: {tool_id}", tool_id=tool_id, work_item_id=item_id,
        )
        results.append({"tool_id": tool_id, "ok": True, "work_item": resolved.to_dict()})

    all_ok = all(r.get("ok", False) for r in results)
    return JSONResponse({"ok": all_ok, "results": results})


# ---------------------------------------------------------------------------
# POST /api/act/gate/block
# ---------------------------------------------------------------------------


async def handle_gate_block(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    tool_id = data.get("tool_id", "")
    if not tool_id:
        return _error("tool_id required")

    item_id = f"wi_approval_{tool_id}"
    item = ctx.event_store.get_work_item(item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.DENIED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    try:
        if ctx.lockfile_manager:
            ctx.lockfile_manager.reject(tool_id, reason="Blocked via console")
            ctx.lockfile_manager.save()
    except Exception as e:
        logger.exception("Failed to block %s", tool_id)
        return _error("action_failed", 500, message=str(e))

    resolved, _ = await ctx.event_store.resolve_work_item(
        item_id, WorkItemStatus.DENIED, resolved_by="console", reason="Blocked via console"
    )
    assert resolved is not None

    _publish_resolution_event(
        ctx.event_store, "tool_blocked", "warn",
        f"Tool blocked: {tool_id}", tool_id=tool_id, work_item_id=item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/act/confirm/grant
# ---------------------------------------------------------------------------


async def handle_confirm_grant(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    work_item_id = data.get("work_item_id", "")
    if not work_item_id:
        return _error("work_item_id required")

    item = ctx.event_store.get_work_item(work_item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.APPROVED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    # Side effect: grant confirmation token
    token_id = item.subject_id
    try:
        if ctx.confirmation_store:
            ok = ctx.confirmation_store.grant(token_id)
            if not ok:
                return _error("action_failed", 500, message="Token already consumed or expired")
    except Exception as e:
        logger.exception("Failed to grant confirmation %s", token_id)
        return _error("action_failed", 500, message=str(e))

    resolved, _ = await ctx.event_store.resolve_work_item(
        work_item_id, WorkItemStatus.APPROVED, resolved_by="console", reason="Confirmed via console"
    )
    assert resolved is not None

    tool_id = item.evidence.get("tool_id", item.subject_label)
    _publish_resolution_event(
        ctx.event_store, "confirmation_granted", "success",
        f"Confirmation granted: {tool_id}", tool_id=tool_id, work_item_id=work_item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/act/confirm/deny
# ---------------------------------------------------------------------------


async def handle_confirm_deny(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    work_item_id = data.get("work_item_id", "")
    if not work_item_id:
        return _error("work_item_id required")

    item = ctx.event_store.get_work_item(work_item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.DENIED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    token_id = item.subject_id
    try:
        if ctx.confirmation_store:
            ctx.confirmation_store.deny(token_id, reason="Denied via console")
    except Exception as e:
        logger.exception("Failed to deny confirmation %s", token_id)
        return _error("action_failed", 500, message=str(e))

    resolved, _ = await ctx.event_store.resolve_work_item(
        work_item_id, WorkItemStatus.DENIED, resolved_by="console", reason="Denied via console"
    )
    assert resolved is not None

    tool_id = item.evidence.get("tool_id", item.subject_label)
    _publish_resolution_event(
        ctx.event_store, "confirmation_denied", "warn",
        f"Confirmation denied: {tool_id}", tool_id=tool_id, work_item_id=work_item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/act/kill
# ---------------------------------------------------------------------------


async def handle_kill_tool(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    work_item_id = data.get("work_item_id", "")
    if not work_item_id:
        return _error("work_item_id required")

    item = ctx.event_store.get_work_item(work_item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.DISMISSED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    tool_id = item.subject_id
    try:
        if ctx.circuit_breaker:
            ctx.circuit_breaker.kill_tool(tool_id, reason="Killed via console")
    except Exception as e:
        logger.exception("Failed to kill %s", tool_id)
        return _error("action_failed", 500, message=str(e))

    resolved, _ = await ctx.event_store.resolve_work_item(
        work_item_id, WorkItemStatus.DISMISSED, resolved_by="console", reason="Killed via console"
    )
    assert resolved is not None

    _publish_resolution_event(
        ctx.event_store, "breaker_killed", "error",
        f"Tool killed permanently: {tool_id}", tool_id=tool_id, work_item_id=work_item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/act/enable
# ---------------------------------------------------------------------------


async def handle_enable_tool(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    work_item_id = data.get("work_item_id", "")
    if not work_item_id:
        return _error("work_item_id required")

    item = ctx.event_store.get_work_item(work_item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.APPROVED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    tool_id = item.subject_id
    try:
        if ctx.circuit_breaker:
            ctx.circuit_breaker.enable_tool(tool_id)
    except Exception as e:
        logger.exception("Failed to enable %s", tool_id)
        return _error("action_failed", 500, message=str(e))

    resolved, _ = await ctx.event_store.resolve_work_item(
        work_item_id, WorkItemStatus.APPROVED, resolved_by="console", reason="Re-enabled via console"
    )
    assert resolved is not None

    _publish_resolution_event(
        ctx.event_store, "breaker_enabled", "success",
        f"Tool re-enabled: {tool_id}", tool_id=tool_id, work_item_id=work_item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/act/rules/activate
# ---------------------------------------------------------------------------


async def handle_rule_activate(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    work_item_id = data.get("work_item_id", "")
    if not work_item_id:
        return _error("work_item_id required")

    item = ctx.event_store.get_work_item(work_item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.APPLIED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    rule_id = item.subject_id
    try:
        if ctx.rule_engine:
            from toolwright.models.rule import RuleStatus

            ctx.rule_engine.update_rule(rule_id, status=RuleStatus.ACTIVE)
    except Exception as e:
        logger.exception("Failed to activate rule %s", rule_id)
        return _error("action_failed", 500, message=str(e))

    resolved, _ = await ctx.event_store.resolve_work_item(
        work_item_id, WorkItemStatus.APPLIED, resolved_by="console", reason="Rule activated via console"
    )
    assert resolved is not None

    _publish_resolution_event(
        ctx.event_store, "rule_activated", "success",
        f"Rule activated: {rule_id}", work_item_id=work_item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/act/rules/dismiss
# ---------------------------------------------------------------------------


async def handle_rule_dismiss(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    work_item_id = data.get("work_item_id", "")
    if not work_item_id:
        return _error("work_item_id required")

    item = ctx.event_store.get_work_item(work_item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.DISMISSED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    rule_id = item.subject_id
    try:
        if ctx.rule_engine:
            ctx.rule_engine.remove_rule(rule_id)
    except KeyError:
        pass  # Already removed
    except Exception as e:
        logger.exception("Failed to dismiss rule %s", rule_id)
        return _error("action_failed", 500, message=str(e))

    resolved, _ = await ctx.event_store.resolve_work_item(
        work_item_id, WorkItemStatus.DISMISSED, resolved_by="console", reason="Rule dismissed via console"
    )
    assert resolved is not None

    _publish_resolution_event(
        ctx.event_store, "rule_dismissed", "warn",
        f"Rule dismissed: {rule_id}", work_item_id=work_item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/act/repair/apply
# ---------------------------------------------------------------------------


async def handle_repair_apply(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    work_item_id = data.get("work_item_id", "")
    if not work_item_id:
        return _error("work_item_id required")

    item = ctx.event_store.get_work_item(work_item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.APPLIED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    # For now, just mark as applied. Full repair integration deferred to Phase 2.
    resolved, _ = await ctx.event_store.resolve_work_item(
        work_item_id, WorkItemStatus.APPLIED, resolved_by="console", reason="Repair applied via console"
    )
    assert resolved is not None

    _publish_resolution_event(
        ctx.event_store, "repair_applied", "success",
        f"Repair patch applied: {item.subject_label}", work_item_id=work_item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/act/repair/dismiss
# ---------------------------------------------------------------------------


async def handle_repair_dismiss(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    data = await request.json()
    work_item_id = data.get("work_item_id", "")
    if not work_item_id:
        return _error("work_item_id required")

    item = ctx.event_store.get_work_item(work_item_id)
    if item is None:
        return _error("not_found", 404)
    if item.status == WorkItemStatus.DISMISSED:
        return JSONResponse({"ok": True, "work_item": item.to_dict()})
    if item.is_terminal():
        return _error("conflict", 409, message=f"Already {item.status.value}", work_item=item.to_dict())

    resolved, _ = await ctx.event_store.resolve_work_item(
        work_item_id, WorkItemStatus.DISMISSED, resolved_by="console", reason="Repair dismissed via console"
    )
    assert resolved is not None

    _publish_resolution_event(
        ctx.event_store, "repair_dismissed", "warn",
        f"Repair patch dismissed: {item.subject_label}", work_item_id=work_item_id,
    )
    return JSONResponse({"ok": True, "work_item": resolved.to_dict()})


# ---------------------------------------------------------------------------
# GET /api/work-items
# ---------------------------------------------------------------------------


async def handle_list_work_items(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    kind_param = request.query_params.get("kind")
    kind = WorkItemKind(kind_param) if kind_param else None
    items = ctx.event_store.open_work_items(kind=kind)
    return JSONResponse({"items": [i.to_dict() for i in items]})


# ---------------------------------------------------------------------------
# GET /api/work-items/{item_id}
# ---------------------------------------------------------------------------


async def handle_get_work_item(request: Request) -> JSONResponse:
    ctx = _get_ctx()
    item_id = request.path_params["item_id"]
    item = ctx.event_store.get_work_item(item_id)
    if item is None:
        return _error("not_found", 404)
    return JSONResponse({"work_item": item.to_dict()})


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------


async def handle_status_counts(_request: Request) -> JSONResponse:
    ctx = _get_ctx()
    return JSONResponse(ctx.event_store.work_item_counts())
