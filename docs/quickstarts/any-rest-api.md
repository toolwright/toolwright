# Any REST API

Give Claude access to any REST API through governed MCP tools.

This guide works with any API that uses bearer token or API key authentication. You'll point Toolwright at the API's web interface, browse it to capture traffic, and get a governed MCP server.

> **Guided experience:** `toolwright ship` walks you through each step interactively. This quickstart does it step-by-step so you understand what's happening.

> **Check for a recipe first:** Run `toolwright recipes list` to see if a bundled recipe exists for your API. If so, use `toolwright mint --recipe <name>` to pre-fill hosts, headers, and rules.

## Prerequisites

- Python 3.11+
- An API you want to connect (you'll need: the web URL and an auth token)
- Claude Desktop installed ([download](https://claude.ai/download))

## Step 1: Install Toolwright

```bash
pip install "toolwright[all]"
python -m playwright install chromium    # use the same interpreter you installed with; on some systems use python3
```

## Step 2: Identify your API host

Most web apps talk to a separate API host. Examples:

| Web URL | API Host |
|---------|----------|
| `https://dashboard.stripe.com` | `api.stripe.com` |
| `https://app.notion.so` | `api.notion.com` |
| `https://linear.app` | `api.linear.app` |
| `https://github.com` | `api.github.com` |

If you're not sure, open your browser's DevTools (Network tab), use the app, and look at the XHR/Fetch requests to find the API domain.

## Step 3: Mint your toolpack

```bash
toolwright mint https://your-app.example.com -a api.example.com
```

Replace:
- `https://your-app.example.com` with the web URL you browse
- `api.example.com` with the API host (from Step 2)

This does three things:
1. **Probes** the API host — detects auth requirements and OpenAPI specs
2. **Opens a browser** — navigate the app to capture API traffic
3. **Compiles** captured traffic into governed MCP tools

**Browse thoroughly.** Navigate to different pages, open different resources, use search and filters. More pages = more API endpoints captured = more tools.

When done, close the browser window or press `Ctrl+C`.

**Expected output:**

```
Minting toolpack from https://your-app.example.com...
  Capturing traffic from api.example.com... Browse normally, then close the browser when done.
  Captured 23 API calls from 1 host(s).

Probing your-app.example.com...
  ⚠ api.example.com — Auth required: Bearer (401)
    export TOOLWRIGHT_AUTH_API_EXAMPLE_COM="Bearer <your-token>"
  ○ No OpenAPI spec detected
  ○ No GraphQL endpoint detected

  Compiling artifacts...
  Packaging toolpack...

Mint complete: api-example-com
  Toolpack: .toolwright/toolpacks/api-example-com/toolpack.yaml

  Gate: 23 pending
  Rules: crud-safety (3 rules applied)

  Example tool: get_products
    GET /products
    Parameters: page (integer), limit (integer)

  23 tools in 5 groups
    products (8)        orders (6)          users (5)           ...
```

## Step 4: Set auth

The probe output (or the post-mint summary) shows the exact export command. Copy it and set your token:

```bash
export TOOLWRIGHT_AUTH_API_EXAMPLE_COM="Bearer your-token-here"
```

The env var name follows a pattern: `TOOLWRIGHT_AUTH_` + your API host with dots/hyphens replaced by underscores, uppercased. Examples:

| API Host | Env Var |
|----------|---------|
| `api.stripe.com` | `TOOLWRIGHT_AUTH_API_STRIPE_COM` |
| `api.notion.com` | `TOOLWRIGHT_AUTH_API_NOTION_COM` |
| `api-v2.example.co.uk` | `TOOLWRIGHT_AUTH_API_V2_EXAMPLE_CO_UK` |

## Step 5: Review and approve

Check what tools were created:

```bash
toolwright gate status
```

Then approve:

```bash
toolwright gate allow --all
```

`gate status` shows tools by risk tier. `gate allow --all` approves everything — fine for getting started. In production, review and approve selectively.

## Step 6: Serve

```bash
toolwright serve
```

> **Too many tools?** Serve a subset with `--scope`:
> ```bash
> toolwright groups list                      # see available groups
> toolwright serve --scope products,orders    # serve specific groups
> ```

## Step 7: Connect to Claude Desktop

```bash
toolwright config
```

Paste the output into your Claude Desktop config:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

Make sure the toolpack path is absolute. Restart Claude Desktop.

## Step 8: Try it

Open Claude Desktop and ask something about your API:

> "List all products" or "Show recent orders" or "Search for users named Alice"

## Tips

**More traffic = better tools.** Browse different sections of the app. Open detail pages, use search, navigate pagination. Each new API call becomes a tool.

**Multiple API hosts.** Some apps call multiple backends. Add more hosts with `-a`:
```bash
toolwright mint https://app.example.com -a api.example.com -a auth.example.com
```

**Custom headers.** Some APIs require extra headers (version headers, workspace IDs). Store them in the toolpack with `-H`:
```bash
toolwright mint https://app.notion.so -a api.notion.com -H "Notion-Version: 2022-06-28"
```

**OpenAPI import.** If your API publishes an OpenAPI spec, import it for complete coverage:
```bash
toolwright capture import https://api.example.com/openapi.json -a api.example.com
toolwright compile --capture <capture-id>
```

**Check what was captured.**
```bash
toolwright groups list              # list tool groups
toolwright groups show products     # see tools in a group
```

**Verify auth works.**
```bash
toolwright auth check
```

## Troubleshooting

**"No API traffic was captured"**

The browser didn't make requests to the host you specified with `-a`. Common causes:
- Wrong API host (check DevTools Network tab)
- The app uses the same domain for UI and API (use the web URL as both arguments)
- Single-page app that loaded all data before you started browsing

**"Auth required" in probe output**

Set the env var shown in the probe output before serving. The token is injected by Toolwright's proxy — Claude never sees it.

**"Refusing to serve N tools"**

Use `--scope` to narrow:
```bash
toolwright groups list
toolwright serve --scope <group1>,<group2>
```

Or override the limit: `toolwright serve --no-tool-limit`

## What's next

- [GitHub API quickstart](github.md) — specific walkthrough for GitHub
- Detect API drift: `toolwright drift`
- Continuous monitoring: `toolwright serve --watch --auto-heal safe`
- Add behavioral rules: `toolwright rules add --help`
- Full user guide: [docs/user-guide.md](../user-guide.md)
