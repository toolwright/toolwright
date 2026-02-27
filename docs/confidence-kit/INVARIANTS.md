# Toolwright Invariants

Never-break rules. Each invariant names where it is enforced.

1. **Default deny at runtime.** The MCP server refuses all tool calls unless an approved lockfile is loaded. A single explicit escape hatch exists for development use only. (`toolwright/mcp/server.py`, `toolwright/core/enforce/decision_engine.py`)

2. **No silent privilege escalation.** Approving a tool requires an explicit `gate allow` with an Ed25519 signature recorded in the lockfile. No tool transitions from pending to approved without a signed entry. (`toolwright/core/approval/lockfile.py`, `toolwright/core/approval/signing.py`)

3. **Redirects fail closed.** HTTP redirects during tool execution are blocked by default. Enabling them requires an explicit opt-in; each hop is re-validated against the host allowlist. (`toolwright/core/network_safety.py`, `toolwright/mcp/server.py`)

4. **Approved lockfile enforced at serve time.** Serve loads the lockfile and checks per-tool approval status + signature validity before allowing any call. Unapproved or signature-invalid tools are denied with `denied_not_approved` or `denied_approval_signature_invalid`. (`toolwright/core/enforce/decision_engine.py`)

5. **One shared network safety implementation.** Both the MCP stdio server and the HTTP proxy gateway use the same `network_safety.py` for SSRF prevention, IP validation, and scheme checks. (`toolwright/core/network_safety.py`)

6. **Cloud metadata endpoint hard-blocked.** `169.254.169.254` is unconditionally blocked regardless of any allowlist. (`toolwright/core/network_safety.py:validate_network_target`)

7. **Only http/https schemes at runtime.** Any other URL scheme is rejected before execution. (`toolwright/core/network_safety.py:validate_url_scheme`)

8. **Deterministic non-interactive behavior in CI.** All interactive prompts can be disabled via a flag or environment variable. All core commands respect this setting. (`toolwright/cli/main.py`)

9. **Stable exit codes for CI gating.** `gate check` exits 0 (all approved), 1 (pending/rejected), or 2 (no lockfile). (`toolwright/cli/approve.py:run_approve_check`)

10. **Artifact integrity is hash-pinned.** The lockfile records an `artifacts_digest` (SHA-256). Tampering triggers `denied_integrity_mismatch` at runtime. (`toolwright/core/approval/integrity.py`, `toolwright/core/enforce/decision_engine.py`)

11. **Private/loopback IPs blocked by default.** Denied unless an explicit allowlist configuration permits them. (`toolwright/core/network_safety.py:is_ip_allowed`)

12. **Signing keys never leave the state root.** Private keys at `.toolwright/state/keys/` with mode 600. Never included in bundles, exports, or toolpack artifacts. (`toolwright/core/approval/signing.py`)

13. **Audit trail for all runtime decisions.** Every allow/deny/confirm decision is logged to the audit JSONL. (`toolwright/mcp/server.py`, `toolwright/core/enforce/decision_engine.py`)

14. **Toolpack paths resolved relative to toolpack.yaml.** All artifact references use relative paths. No absolute paths stored. (`toolwright/core/toolpack.py:resolve_toolpack_paths`)
