# Toolwright Control Plane — Implementation Plan

## Goal
Transform Toolwright's monitoring dashboard into a real-time agent operations console with WorkItem-based governance.

## Architecture Summary
- **WorkItem model**: First-class objects representing human-actionable items with deterministic IDs
- **EventStore**: Persistent event store with atomic file writes, ring buffer for SSE replay, audit JSONL log
- **Action handlers**: POST endpoints that perform side effects BEFORE resolving WorkItems
- **SSE stream**: Resumable with Last-Event-ID, sync events, status events
- **Console frontend**: Single HTML file (<80KB), dark theme, vanilla JS
- **Integration points**: Pipeline, server startup, breaker, reconcile, meta-server

## Build Sequence

### Phase 1: Foundation (WorkItem + EventStore + Actions)
1. **WorkItem model** (`toolwright/models/work_item.py`)
   - WorkItemKind, WorkItemStatus, WorkItemAction, WorkItem dataclasses
   - Deterministic IDs, to_dict/from_dict serialization

2. **WorkItem factories** (`toolwright/core/work_items.py`)
   - create_tool_approval_item, create_confirmation_item, create_circuit_breaker_item
   - create_repair_patch_item, create_rule_draft_item, create_capability_request_item

3. **EventStore** (`toolwright/mcp/event_store.py`)
   - ConsoleEvent dataclass
   - EventStore: ring buffer (5000), audit JSONL, per-item JSON persistence
   - Atomic writes (tmp + os.replace), asyncio.Lock for critical section
   - Reconstruct from files on startup, expiration logic with confirmation_store.deny()
   - SSE subscription via asyncio.Queue

4. **Action handlers** (`toolwright/mcp/action_handlers.py`)
   - Side-effect-before-resolution pattern (critical)
   - Routes: gate/allow (bulk), gate/block, confirm/grant, confirm/deny, kill, enable
   - Routes: rules/activate, rules/dismiss, repair/apply, repair/dismiss
   - GET routes: work-items, work-items/{id}, status

5. **SSE stream** (in http_transport.py)
   - Last-Event-ID support for reconnection
   - Three event types: message (with work_item), sync, status
   - Keepalive every 30s

### Phase 2: Integration Wiring
6. **Pipeline integration** (pipeline.py)
   - Confirmation gate creates CONFIRMATION WorkItems
   - Tool calls emit events to EventStore

7. **Server startup integration** (server.py)
   - Pending tools → TOOL_APPROVAL WorkItems on serve startup

8. **Breaker integration** (core/kill/breaker.py)
   - Trip → CIRCUIT_BREAKER WorkItem (upsert)
   - Recovery → resolve existing WorkItem

9. **Reconcile integration** (core/reconcile/loop.py)
   - Drift detection → REPAIR_PATCH WorkItems

10. **Meta-server integration** (meta_server.py)
    - toolwright_pending_actions meta-tool
    - toolwright_suggest_rule → RULE_DRAFT WorkItem

### Phase 3: Console Frontend
11. **Console HTML** (`toolwright/assets/console/index.html`)
    - Status bar, filter bar, event feed, work item cards
    - SSE with reconnection + client-side merge rules
    - All 6 WorkItem kinds + generic unknown handler
    - Blocking timer, bulk approval, card transitions

### Phase 4: Tests
12. **Unit tests**: work_item, event_store, action_handlers
13. **Integration tests**: pipeline events, meta work items, SSE reconnect

## Key Files
### New
- `toolwright/models/work_item.py`
- `toolwright/core/work_items.py`
- `toolwright/mcp/event_store.py`
- `toolwright/mcp/action_handlers.py`
- `toolwright/assets/console/index.html`

### Modified
- `toolwright/mcp/http_transport.py` (routes, SSE, expiration loop)
- `toolwright/mcp/pipeline.py` (confirmation -> WorkItem)
- `toolwright/mcp/server.py` (startup -> TOOL_APPROVAL items)
- `toolwright/mcp/meta_server.py` (pending_actions, suggest_rule)
- `toolwright/core/kill/breaker.py` (trip/recovery -> WorkItems)
- `toolwright/core/reconcile/loop.py` (drift -> REPAIR_PATCH items)
- `toolwright/mcp/auth.py` (Referrer-Policy header)

## Critical Design Decisions
1. **Side effect BEFORE resolution**: Action handlers must perform the actual action (e.g., confirmation_store.grant()) before transitioning the WorkItem to terminal state
2. **Deterministic IDs**: All WorkItem IDs are deterministic to handle reconnects and dedup
3. **Atomic file writes**: tmp + os.replace pattern for crash safety
4. **Upsert policy**: Re-publishing an existing OPEN WorkItem updates evidence without resetting created_at
5. **Expiration + deny**: Expired confirmation WorkItems MUST call confirmation_store.deny() to unblock agents
