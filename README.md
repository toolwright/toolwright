# Toolwright

The trusted MCP supply chain for AI tools.

Capture APIs or wrap existing MCP servers. Keep credentials out of model context, approve changes with signed lockfiles, enforce fail-closed runtime controls, detect drift, verify behavior, and auto-repair safely.

The immune system for AI tools.

```bash
pip install "toolwright[all]"

toolwright create github
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ghp_yourToken"
toolwright config
# Paste the emitted MCP config into Claude Desktop, restart — done.
```

Generation is the on-ramp. The value is what happens after the tools exist: fail-closed governance, signed change control, and bounded self-healing for production drift.

## Why Toolwright

- **Credentials never enter model context** — auth is injected at runtime, not exposed in tool definitions, logs, or prompts.
- **Every tool change is signed and approved before it runs** — new tools and changed capabilities land behind a lockfile review loop.
- **With watch or verify enabled, upstream API changes are surfaced before your agent breaks** — drift detection, verification, and bounded self-healing keep the runtime stable after launch.

## Quickstarts

- **[GitHub API in 60 seconds](docs/quickstarts/github.md)** — `toolwright create github`
- **[Any REST API](docs/quickstarts/any-rest-api.md)** — browser capture for custom APIs
- **[User Guide](docs/user-guide.md)** — full lifecycle, operations, and repair flows

## Start from an API

For custom APIs, use `mint` to capture from a browser:

```bash
toolwright mint https://app.example.com -a api.example.com
toolwright gate allow --all
toolwright serve
```

Other inputs work too:

| You have... | Run |
|------------|-----|
| A web app | `toolwright mint https://app.example.com -a api.example.com` |
| An OpenAPI spec | `toolwright capture import openapi.yaml -a api.example.com` |
| A HAR file | `toolwright capture import traffic.har -a api.example.com` |
| OTEL traces | `toolwright capture import traces.json --input-format otel -a api.example.com` |

All paths produce the same governed supply chain artifacts: tools, policy, lockfile, baselines, and verification contracts.

## Already have an MCP server? Wrap it.

```bash
toolwright wrap npx -y @modelcontextprotocol/server-github
toolwright wrap --url https://mcp.sentry.dev/mcp --header "Authorization: Bearer $TOKEN"
```

`wrap` discovers an existing MCP server's tools and puts them behind the same approval, rules, circuit breaker, and fail-closed enforcement loop. Lead with API capture if you are creating tools for the first time; reach for `wrap` when the tool surface already exists.

## How the supply chain works

```
                    ┌──────────────────────────────────────────────┐
  Browser traffic   │                                              │
  OpenAPI spec   ──>│   mint / capture   ──>   compile   ──>      │
  HAR file          │                                              │
                    │   toolpack (tools + policy + lockfile)        │
                    │                                              │
                    │   serve  ──>  governed MCP server             │
                    │     ├── auth injection (proxy layer)          │
                    │     ├── signed approval gates                 │
                    │     ├── circuit breakers                      │
                    │     └── drift / verify / repair               │
                    └──────────────────────────────────────────────┘
```

1. **`create` / `mint` / `capture import`** turn real API behavior into deterministic tool artifacts.
2. **`gate allow`** records approvals in a signed lockfile. Nothing new runs until it is reviewed.
3. **`serve` / `run`** expose only the approved tool surface with auth isolation, rules, and circuit breakers.
4. **`drift` / `verify` / `repair`** catch upstream changes early and keep the tool surface trustworthy over time.

If you already have an MCP server, `wrap` discovers the upstream tools and applies the same approval, breaker, and rule enforcement loop without recreating them.

## Serving options

```bash
toolwright serve                                    # stdio (Claude Desktop)
toolwright serve --http                             # HTTP with web dashboard
toolwright serve --scope repos,issues               # serve specific tool groups
toolwright serve --max-risk low                     # cap risk tier exposure
toolwright serve -H "Notion-Version: 2022-06-28"   # inject custom headers
toolwright serve --watch --auto-heal safe           # continuous drift detection
```

**Tool groups** keep context manageable. Toolwright auto-groups tools by URL path during compilation. Use `--scope` to serve subsets:

```bash
toolwright groups list                    # see available groups
toolwright groups show repos              # inspect a group
toolwright serve --scope repos            # serve just that group
```

Bounded self-healing is opt-in and defaults to the safe path:

```bash
toolwright serve --watch --auto-heal safe
```

## Commands

```bash
# Quick start
toolwright create github                 # create tools from a known API
toolwright mint <url> -a <api-host>      # capture from browser + compile
toolwright gate allow --all              # approve tools
toolwright serve                         # start MCP server

# Operations
toolwright groups list                   # browse tool groups
toolwright wrap npx -y @modelcontextprotocol/server-github  # govern an existing MCP server
toolwright recipes list                  # list bundled API recipes
toolwright recipes show shopify          # show recipe details
toolwright auth check                    # verify auth configuration
toolwright drift                         # detect API changes
toolwright config                        # generate MCP client config

# Advanced
toolwright repair plan                   # Terraform-style drift repair
toolwright rules add --kind rate ...     # behavioral constraints
toolwright rules template list           # browse bundled rule templates
toolwright rules template apply crud-safety  # create DRAFT rules from template
toolwright kill <tool> --reason "..."    # circuit breaker kill switch
toolwright serve --watch --auto-heal safe # continuous reconciliation

# All commands
toolwright --help
```

## How is this different from other MCP servers?

Most MCP tooling focuses on generation, connectivity, or hosted catalogs. Toolwright focuses on the trusted supply chain around those tools: auth isolation, signed approvals, fail-closed runtime enforcement, drift detection, verification, and bounded self-healing.

Toolwright can compile tools from real traffic or wrap an existing MCP server, but it does not stop at creation. Credentials never enter model context. Tool changes stay behind a signed lockfile. Runtime stays fail-closed. With watch or verify enabled, drift is surfaced before your agent breaks. Safe maintenance can auto-heal with snapshots, available rollback, and escalation when human review is needed.

## Install

```bash
pip install "toolwright[all]"             # MCP server + browser capture + TUI
python -m playwright install chromium     # use the same interpreter you installed with; on some systems use python3
```

Or install components separately:

```bash
pip install toolwright                    # core
pip install "toolwright[mcp]"             # + MCP server
pip install "toolwright[playwright]"      # + browser capture
```

`tw` works as shorthand for `toolwright`.

## Documentation

- [User Guide](docs/user-guide.md) — full reference
- [Architecture](docs/architecture.md) — how it works internally
- [Quickstart: GitHub](docs/quickstarts/github.md)
- [Quickstart: Any REST API](docs/quickstarts/any-rest-api.md)
- [Known Limitations](docs/known-limitations.md)
- [Troubleshooting](docs/troubleshooting.md)

## License

MIT
