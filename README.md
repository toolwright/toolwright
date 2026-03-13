# Toolwright

**The immune system for AI tools.**

Capture any API — or wrap an existing MCP server — and get a governed tool supply chain: credentials isolated from model context, signed approvals, fail-closed runtime, drift detection, and bounded self-healing.

[![PyPI version](https://img.shields.io/pypi/v/toolwright.svg)](https://pypi.org/project/toolwright/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://www.python.org/downloads/)

---

<table>
<tr>
<td width="50%">

**Without governance**

```
# Token hardcoded in tool config
{"auth": "Bearer ghp_s3cr3t..."}

# Model sees the token in context
# No approval before tool runs
# API changes → silent agent failure
# No audit trail
```

</td>
<td width="50%">

**With Toolwright**

```bash
toolwright create github
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ..."
toolwright serve

# Token injected at runtime, never in context
# Signed lockfile gates every change
# Drift detected before agents break
# Every decision audited
```

</td>
</tr>
</table>

---

## Why this matters

Every AI agent needs tools. But the way tools connect to APIs today is broken:

- **Credentials leak into model context** — API keys land in tool definitions, logs, and prompts where the model can see and misuse them
- **Tool changes happen silently** — new capabilities and changed schemas go live with no human review
- **APIs drift and agents break** — upstream changes cause silent failures with no alerting or recovery

Generation is the on-ramp. **Governance is the moat.**

| Concern | Typical AI tools | With Toolwright |
|---|---|---|
| Credentials | In config, visible to model | Injected at runtime, never in context |
| New tools | Available immediately | Gated behind signed lockfile |
| API changes | Silent breakage | Drift detected, repair proposed |
| Failures | Retry or crash | Circuit breakers, quarantine, rollback |
| Audit trail | None | Every decision logged with reason codes |
| Recovery | Manual rebuild | Bounded self-healing with snapshots |

## Install

```bash
pip install toolwright
```

`tw` works as shorthand. Add extras only when you need them:
- browser capture: `pip install "toolwright[playwright]"`
- dashboard UI: `pip install "toolwright[tui]"`

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

That's it. GitHub tools — risk-classified, with behavioral rules applied. Your agent can now list repos, create issues, and manage pull requests, all under governance.

> **Start narrow for Claude/Desktop.** The GitHub recipe produces a large tool surface. If you want a smaller first setup, serve a subset such as `repos,issues`.

## Works with anything you have

| Starting point | Command |
|---|---|
| A known API | `toolwright create github` |
| A web app | `toolwright mint https://app.example.com -a api.example.com` |
| An OpenAPI spec | `toolwright capture import openapi.yaml -a api.example.com` |
| A HAR file | `toolwright capture import traffic.har -a api.example.com` |
| OTEL traces | `toolwright capture import traces.json --input-format otel -a api.example.com` |
| An MCP server | `toolwright wrap npx -y @modelcontextprotocol/server-github` |

All paths produce the same governed artifacts: tools, policy, lockfile, baselines, and verification contracts.

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

## Core capabilities

### Credentials never touch model context

Auth is resolved at runtime via environment variables — per-host, isolated. Tool definitions, logs, evidence bundles, and agent prompts are all credential-free.

```bash
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ghp_..."
export TOOLWRIGHT_AUTH_API_STRIPE_COM="Bearer sk_..."
# Toolwright injects the right token for each upstream call
```

### Every change is signed before it runs

Ed25519 signatures on a lockfile. New tools, changed schemas, expanded capabilities — all gated behind explicit approval. No silent privilege escalation.

```bash
toolwright gate allow --all              # interactive review
toolwright gate check                    # verify lockfile integrity
toolwright gate block delete_user        # block a specific tool
```

### Fail-closed by default

Default deny. Explicit allowlists only. Network safety is hardcoded: SSRF prevention, private CIDR filtering, redirect validation, and response size limits.

### Drift detection and bounded self-healing

Continuous health probing catches upstream changes before your agent breaks. Safe patches auto-apply. Risky ones escalate for approval. Snapshots enable instant rollback.

```bash
toolwright drift                              # one-shot check
toolwright serve --watch --auto-heal safe      # continuous monitoring
```

### Behavioral rules and circuit breakers

Composable constraints at invocation time. Kill misbehaving tools instantly.

```bash
toolwright rules template apply crud-safety   # require read before delete
toolwright kill search_api --reason "500s"    # circuit breaker kill switch
toolwright enable search_api                  # bring it back
```

## Already have an MCP server? Wrap it.

```bash
toolwright wrap npx -y @modelcontextprotocol/server-github
toolwright wrap --url https://mcp.sentry.dev/mcp --header "Authorization: Bearer $TOKEN"
```

`wrap` discovers an upstream server's tools and applies the same approval, rules, circuit breaker, and fail-closed enforcement. No tool recreation — just governance.

## Serving options

```bash
toolwright serve                                    # stdio (Claude Desktop)
toolwright serve --http                             # HTTP + web dashboard
toolwright serve --scope repos,issues               # serve specific groups
toolwright serve --max-risk low                     # cap risk tier exposure
toolwright serve --watch --auto-heal safe           # continuous healing
```

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
pip install "toolwright[playwright]"      # + browser capture
pip install "toolwright[tui]"             # + dashboard
pip install "toolwright[all]"             # everything
python -m playwright install chromium     # for browser capture (use same interpreter)
```

Or install only what you need:

```bash
pip install toolwright                    # core
pip install "toolwright[mcp]"             # + explicit MCP dependency bundle
pip install "toolwright[playwright]"      # + browser capture
pip install "toolwright[tui]"             # + dashboard TUI
```

## License

MIT
