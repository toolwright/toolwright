# Toolwright

**The immune system for AI tools.**

Point at any API. Get governed, self-healing AI tools in seconds.

![toolwright create — governed tools in seconds](demos/outputs/hero.gif)

```bash
pip install toolwright
toolwright create github                    # from a bundled recipe
toolwright create --spec ./openapi.json     # from any OpenAPI spec
```

[![PyPI version](https://img.shields.io/pypi/v/toolwright.svg)](https://pypi.org/project/toolwright/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-3097%20passing-brightgreen.svg)](tests/)

---

## What toolwright does

Five pillars. One supply chain. Every command runnable.

### 🔌 CONNECT — Capture any API into governed tools

```bash
toolwright create github                           # from a recipe
toolwright create --spec ./openapi.yaml            # from any OpenAPI spec
toolwright mint https://app.example.com -a api.example.com  # from a live web app
toolwright wrap npx -y @modelcontextprotocol/server-github  # wrap existing MCP
```

### 🔒 GOVERN — Signed approvals gate every change

```bash
toolwright gate allow --all              # interactive review
toolwright gate check                    # verify lockfile integrity
toolwright gate block delete_user        # block a specific tool
```

Ed25519-signed lockfile. New tools, changed schemas, expanded capabilities — all gated behind explicit approval. No silent privilege escalation.

### 📏 CORRECT — Behavioral rules constrain invocations

```bash
toolwright rules template apply crud-safety   # require read before delete
toolwright rules template apply rate-limit    # rate limit tool calls
```

Six composable rule types: `precondition`, `postcondition`, `sequencing`, `rate_limit`, `context_required`, `parameter_constraint`. Applied at invocation time, enforced by the runtime.

### 🩺 HEAL — Drift detection and bounded self-repair

```bash
toolwright drift                              # one-shot check
toolwright serve --watch --auto-heal safe     # continuous monitoring
toolwright repair plan                        # terraform-style repair plan
```

A k8s-style reconciliation loop probes tool endpoints on risk-tier intervals. Safe changes auto-merge. Risky changes escalate for approval. Snapshots enable instant rollback.

### ⚡ KILL — Circuit breakers block broken tools instantly

```bash
toolwright kill search_api --reason "upstream 500s"
toolwright quarantine                    # list all quarantined tools
toolwright enable search_api             # bring it back
```

Three-state circuit breaker (CLOSED → OPEN → HALF_OPEN → CLOSED). After 5 consecutive failures, agents can't call it. After recovery, 3 successes required to fully restore.

---

## Tools that heal themselves

APIs change. Toolwright detects the change, classifies the risk, and either fixes it or tells you exactly what to do.

A k8s-style reconciliation loop continuously probes your tool endpoints. When a response shape changes, toolwright diffs it against the compiled baseline:

- **SAFE** changes (new fields, safe type widenings) → auto-merge into the baseline
- **APPROVAL_REQUIRED** changes (nullability shifts, removed optional fields) → logged for review
- **MANUAL** changes (removed required fields, incompatible type changes) → repair guidance surfaced

If a tool starts failing, the circuit breaker trips after 5 consecutive failures, blocking agents from calling a broken endpoint. After recovery, it enters half-open mode and requires 3 successes before fully restoring.

```bash
toolwright serve --toolpack my-api/toolpack.yaml --watch
# Probes tool endpoints on risk-tier intervals (critical: 2min, low: 30min)
# Auto-heals SAFE drift, logs APPROVAL_REQUIRED, guides MANUAL

toolwright watch status
# Tool                          Status       Healthy  Unhealthy  Last Probe
# get_products                  HEALTHY      12       0          2026-03-13T10:30:00Z
# create_order                  DEGRADED     8        2          2026-03-13T10:28:00Z

toolwright repair plan
# Repair Plan (3 patches)
#   SAFE: 1  APPROVAL REQUIRED: 1  MANUAL: 1
#
# --- SAFE (1) ---
#   New optional response field: category
#     $ toolwright verify --mode contracts

toolwright kill create_order --reason "upstream 500s"
toolwright quarantine
# 1 tool(s) in quarantine:
#   create_order  [open]  reason=upstream 500s
```

Every probe, drift, and repair decision is logged to `.toolwright/state/reconcile.log.jsonl` — a full audit trail of what changed and why.

---

## How fast?

```
$ toolwright demo

  ◆ toolwright demo — governance in action

  Compiling 8 tools from OpenAPI spec...           ✓
  Signing lockfile (Ed25519)...                    ✓  20ms
  Blocking unapproved tool...                      ✓  blocked
  Running approved tool (deterministic)...         ✓  deterministic
  Detecting drift (endpoint removed)...            ✓  clean
  Tripping circuit breaker...                      ✓  clean

  Full lifecycle governance in under 1 second.
```

---

## Works with anything you have

| Starting point | Command |
|---|---|
| GitHub API | `toolwright create github` |
| Stripe API | `toolwright create stripe` |
| Any OpenAPI spec | `toolwright create --spec ./openapi.yaml` |
| Any URL | `toolwright create https://api.example.com` |
| A web app | `toolwright mint https://app.example.com -a api.example.com` |
| A HAR file | `toolwright capture import traffic.har -a api.example.com` |
| An MCP server | `toolwright wrap npx -y @modelcontextprotocol/server-github` |

All paths produce the same governed artifacts: tools, policy, lockfile, baselines, and verification contracts.

---

## How the supply chain works

```
                     ┌──────────────────────────────────────────────┐
  Browser traffic    │                                              │
  OpenAPI spec   ──> │   capture / mint   ──>   compile   ──>       │
  HAR / OTEL         │                                              │
                     │   toolpack (tools + policy + lockfile)       │
                     │                                              │
                     │   serve  ──>  governed MCP server            │
                     │     ├── credential injection (proxy layer)   │
                     │     ├── signed approval gates                │
                     │     ├── circuit breakers                     │
                     │     └── drift / verify / repair              │
                     └──────────────────────────────────────────────┘
```

1. **Capture** — Record real API behavior from any source
2. **Compile** — Generate deterministic tool definitions with schemas, risk tiers, and policies
3. **Approve** — Sign changes with Ed25519 keys. Nothing runs until reviewed.
4. **Serve** — Expose tools via MCP with auth injection, policy enforcement, and circuit breakers
5. **Heal** — Detect drift, verify behavior, and auto-repair within safety bounds

---

## Credentials never touch model context

Auth is resolved at runtime via environment variables — per-host, isolated. Tool definitions, logs, evidence bundles, and agent prompts are all credential-free.

```bash
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ghp_..."
export TOOLWRIGHT_AUTH_API_STRIPE_COM="Bearer sk_..."
# Toolwright injects the right token for each upstream call
```

---

## Get started in 60 seconds

```bash
# Create governed tools from GitHub's API
toolwright create github

# Set your token (never enters model context)
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ghp_yourToken"

# Get the config snippet for Claude Desktop
toolwright config

# Paste into Claude Desktop config → restart → done.
```

> **Start narrow.** The GitHub recipe produces 1062 tools. Serve a focused subset: `toolwright serve --scope repos,issues`

---

## Already have an MCP server? Wrap it.

```bash
toolwright wrap npx -y @modelcontextprotocol/server-github
toolwright wrap --url https://mcp.sentry.dev/mcp --header "Authorization: Bearer $TOKEN"
```

`wrap` discovers an upstream server's tools and applies the same approval, rules, circuit breaker, and fail-closed enforcement. No tool recreation — just governance.

---

## Serving options

```bash
toolwright serve                                    # stdio (Claude Desktop)
toolwright serve --http                             # HTTP + web dashboard
toolwright serve --scope repos,issues               # serve specific groups
toolwright serve --max-risk low                     # cap risk tier exposure
toolwright serve --watch --auto-heal safe           # continuous healing
```

---

## Roadmap

- Transport-agnostic governance (CLI + REST adapters alongside MCP)
- Governance maturity scoring (`toolwright score`)
- GitHub Action for CI governance checks
- Public toolpack registry

---

## Documentation

- **[GitHub API in 60 seconds](docs/quickstarts/github.md)** — quickstart with `toolwright create github`
- **[Any REST API](docs/quickstarts/any-rest-api.md)** — browser capture for custom APIs
- [User Guide](docs/user-guide.md) — full lifecycle reference
- [Architecture](docs/architecture.md) — internals
- [Known Limitations](docs/known-limitations.md) | [Troubleshooting](docs/troubleshooting.md) | [Glossary](docs/glossary.md)

Run `toolwright --help` for the quick reference. Run `toolwright --help-all` for every command.

## Install options

```bash
pip install toolwright                    # core CLI + governed runtime
pip install "toolwright[playwright]"      # + browser capture (for mint command)
pip install "toolwright[tui]"             # + full-screen dashboard
pip install "toolwright[all]"             # everything
```

`tw` works as shorthand for `toolwright`.

## License

MIT
