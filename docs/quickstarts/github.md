# GitHub API in 5 Minutes

Give Claude access to GitHub's API through governed MCP tools.

> **Quick start with recipe:** `toolwright mint --recipe github https://github.com -n github-tools`
> This pre-fills hosts, auth headers, and rule templates. Skip to Step 3 below.

## Prerequisites

- Python 3.11+
- A GitHub personal access token ([create one here](https://github.com/settings/tokens) — select "repo" scope at minimum)
- Claude Desktop installed ([download](https://claude.ai/download))

## Step 1: Install Toolwright

```bash
pip install "toolwright[all]"
python -m playwright install chromium
```

`toolwright[all]` installs the MCP server, browser capture, and TUI extras. The second command installs the Chromium browser binary that Toolwright uses for traffic capture.

## Step 2: Set your GitHub token

```bash
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ghp_yourTokenHere"
```

Replace `ghp_yourTokenHere` with your actual token. Toolwright uses per-host environment variables to inject auth at the proxy layer — your token never enters the LLM context.

## Step 3: Mint your GitHub toolpack

```bash
toolwright mint https://github.com -a api.github.com
```

This does three things:
1. **Probes** api.github.com — detects auth requirements, checks for an OpenAPI spec
2. **Opens a browser** to github.com — browse repos, issues, pull requests to capture API traffic
3. **Compiles** the captured traffic into governed MCP tools

When you're done browsing, close the browser window or press `Ctrl+C`.

**Expected output:**

```
Minting toolpack from https://github.com...
  Capturing traffic (120s)...

Probing github.com...
  ⚠ api.github.com — Auth required: Bearer (401)
    export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer <your-token>"
  ✓ OpenAPI spec found: https://api.github.com/openapi.json
  ○ No GraphQL endpoint detected

  Compiling artifacts...
  Packaging toolpack...

Mint complete: api-github-com
  Capture: cap_...
  Toolpack: .toolwright/toolpacks/api-github-com/toolpack.yaml
  Pending approvals: 47

  47 tools in 12 groups
    repos (15)          issues (8)          pulls (7)           users (5)
    ...

  Serve subset: toolwright serve --scope repos
  All groups:  toolwright groups list
```

The exact number of tools depends on which pages you visited. More browsing = more tools captured.

> **Want complete API coverage?** The probe detected GitHub's OpenAPI spec. Import it for all 1000+ endpoints:
> ```bash
> toolwright capture import https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json -a api.github.com
> toolwright compile --capture <capture-id-from-output>
> ```

## Step 4: Approve the tools

```bash
toolwright gate allow --all
```

Every tool requires explicit approval before it can execute. This approves all pending tools at once — fine for getting started. In production, review tools individually with `toolwright gate status` and approve selectively.

**Expected output:**

```
Approved 47 tools (0 already approved, 0 blocked)
Lockfile written: .toolwright/toolpacks/api-github-com/lockfile/toolwright.lock.yaml
```

## Step 5: Serve the toolpack

```bash
toolwright serve
```

If you have a single toolpack, Toolwright auto-resolves it. The server starts on stdio (the transport Claude Desktop uses).

**Expected output:**

```
╭──────────────────────────────────────────────╮
│  Toolwright — api-github-com                 │
│  Tools:    47 (32 read · 12 write · 3 admin)│
│  Risk:     28 low · 12 med · 4 high · 3 crit│
│  Context:  ~18,000 tokens · ~383 per tool    │
╰──────────────────────────────────────────────╯
```

> **Too many tools?** Use `--scope` to serve a subset:
> ```bash
> toolwright serve --scope repos
> ```

## Step 6: Connect to Claude Desktop

Generate the config snippet:

```bash
toolwright config
```

Copy the JSON output and paste it into your Claude Desktop config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

The config looks like this:

```json
{
  "mcpServers": {
    "api-github-com": {
      "command": "toolwright",
      "args": ["serve", "--toolpack", ".toolwright/toolpacks/api-github-com/toolpack.yaml"]
    }
  }
}
```

Make sure the toolpack path is absolute (full path from root, not relative).

Restart Claude Desktop to pick up the new config.

## Step 7: Try it

Open Claude Desktop and ask:

> "List my GitHub repositories"

Claude will use the governed GitHub tools to call the API on your behalf. Your token is injected at the proxy layer — Claude never sees it.

## What just happened

1. `mint` opened a browser and captured the HTTP traffic between GitHub's web UI and api.github.com
2. `compile` (inside mint) inferred the API schema, generated MCP tool definitions, classified risk tiers, and created tool groups
3. `gate allow` approved the tools by signing them into a lockfile
4. `serve` started an MCP server that Claude Desktop connects to via stdio
5. Your GitHub token is injected by Toolwright's proxy — it never appears in Claude's context

## Troubleshooting

**"Playwright not installed"**
```bash
pip install "toolwright[playwright]"
python -m playwright install chromium
```

**"mcp not installed"**
```bash
pip install "toolwright[mcp]"
```

**"No auth configured for api.github.com"**

Check your environment variable:
```bash
echo $TOOLWRIGHT_AUTH_API_GITHUB_COM
```
It should start with `Bearer `.

**"No API traffic was captured"**

The browser didn't make any requests to api.github.com during your session. Try browsing to specific repo pages, issue lists, or pull requests. Or import the OpenAPI spec directly (see Step 3 note).

**"Refusing to serve N tools"**

Toolwright blocks serving more than 200 tools to protect agent performance. Use `--scope` to narrow:
```bash
toolwright groups list
toolwright serve --scope repos,issues
```

**Claude Desktop doesn't see the tools**

1. Make sure the toolpack path in the config is absolute
2. Restart Claude Desktop after editing the config
3. Check `toolwright serve` runs without errors when executed manually

## Next steps

- Browse your tools: `toolwright groups list`
- Inspect a group: `toolwright groups show repos`
- Check auth: `toolwright auth check`
- Detect API drift: `toolwright drift`
- See all commands: `toolwright --help`
