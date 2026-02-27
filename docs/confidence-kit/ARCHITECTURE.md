# Toolwright Architecture (Confidence Kit)

**Toolwright is a build system that compiles observed web/API traffic into safe, versioned, lockfile-governed MCP tools for AI agents.**

## Kernel Loop

```
traffic (HAR/OTEL/OpenAPI) ──► capture + normalize
         │
         ▼
    compile (tools.json, policy.yaml, toolsets.yaml, baseline.json)
         │
         ▼
    toolpack assembly (toolpack.yaml + artifacts + pending lockfile)
         │
         ▼
    gate (approve/block per-tool via Ed25519-signed lockfile)
         │
         ▼
    serve (fail-closed MCP stdio server, lockfile required)
         │
         ▼
    verify (contracts, baseline-check, provenance)
         │
         ▼
    drift (baseline → new capture delta)  ──►  repair (propose fixes)
```

**One-command shortcut:** `toolwright mint` = capture + compile + toolpack + pending lockfile.
**One-command proof:** `toolwright demo` = mint (offline fixture) + gate + serve (dry-run replay) + parity check.

## Module Boundaries

| Layer | Path | Responsibility |
|-------|------|----------------|
| **CLI** | `toolwright/cli/` | Click commands, argument wiring, user output |
| **Core** | `toolwright/core/` | Domain logic: capture, normalize, compile, approval, enforce, verify, drift, repair, scopes |
| **Models** | `toolwright/models/` | Pydantic data models (capture, decision, endpoints) |
| **MCP Server** | `toolwright/mcp/` | MCP stdio server (`server.py`) and meta-introspection server (`meta_server.py`) |
| **UI** | `toolwright/ui/` | Interactive TUI flows (gate review, snapshot) |
| **Storage** | `toolwright/storage.py` | `.toolwright/` directory structure management |
| **Assets** | `toolwright/assets/demo/` | Bundled offline fixtures (`sample.har`) |

## Sources of Truth

| Concern | File / Directory | Notes |
|---------|-----------------|-------|
| Network safety (SSRF) | `toolwright/core/network_safety.py` | Single shared impl for all runtimes |
| Approval signing | `toolwright/core/approval/signing.py` | Ed25519 key management + signature format |
| Lockfile schema | `toolwright/core/approval/lockfile.py` | Lockfile sync, approve, verify, save |
| Integrity digests | `toolwright/core/approval/integrity.py` | SHA-256 artifact hashing |
| Policy enforcement | `toolwright/core/enforce/decision_engine.py` | Runtime allow/deny/confirm decisions |
| Toolpack model | `toolwright/core/toolpack.py` | Toolpack YAML schema + path resolution |
| State root | `.toolwright/` | captures, artifacts, toolpacks, state/keys, reports, repairs |
| Artifact layout | `.toolwright/toolpacks/<id>/` | `toolpack.yaml`, `artifact/`, `lockfile/` |
| Approved lockfile | `.toolwright/toolpacks/<id>/lockfile/toolwright.lock.yaml` | Per-tool status + Ed25519 signatures |
| Signing keys | `.toolwright/state/keys/` | `approval_ed25519_{private,public}.pem`, `trusted_signers.json` |
