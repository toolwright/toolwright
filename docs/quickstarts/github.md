# GitHub API Quickstart

Give Claude access to GitHub's API through governed MCP tools.

## Prerequisites

- Python 3.11+
- A GitHub personal access token ([create one here](https://github.com/settings/tokens) — select "repo" scope at minimum)
- Claude Desktop installed ([download](https://claude.ai/download))

---

## Quick path (60 seconds)

```bash
pip install toolwright
toolwright create github
```

`create` fetches GitHub's OpenAPI spec, compiles tools, auto-approves low/medium risk, and applies behavioral rules. The output will look like this:

```
Create complete: github

  Tools: <many> endpoints compiled
  Auto-approved: <many> (low/medium risk)
  Pending review: <many> (high/critical risk)
  Rules: crud-safety (3 rules)

  Example tool:
    get  GET /

  Auth:
    export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer <your-token>"

Connect to MCP clients:
  toolwright config --toolpack .toolwright/toolpacks/github/toolpack.yaml

  Next steps:
    1. Set your auth token
    2. Run toolwright config --toolpack .toolwright/toolpacks/github/toolpack.yaml
    3. Paste the config into Claude Desktop and restart
    4. Ask Claude about your API
```

Set your token, run `toolwright config`, paste the snippet, restart Claude Desktop — done.

> **Start narrow for Claude/Desktop.** The GitHub recipe produces a large tool surface. For a smaller first setup, use a subset such as `repos,issues` when you serve it.

```bash
toolwright serve --toolpack .toolwright/toolpacks/github/toolpack.yaml --scope repos,issues
```

---

## Custom path (5 minutes) — browser capture

Use this if you want to capture only the specific endpoints you actually use.

### Step 1: Install

```bash
pip install "toolwright[playwright]"
python -m playwright install chromium    # use the same interpreter you installed with; on some systems use python3
```

### Step 2: Mint your toolpack

```bash
toolwright mint https://github.com -a api.github.com
```

This opens a browser to github.com. Browse repos, issues, and pull requests to capture API traffic. Close the browser when done.

```
Minting toolpack from https://github.com...
  Capturing traffic from api.github.com... Browse normally, then close the browser when done.
  Captured 47 API calls from 1 host(s).
```

### Step 3: Set your token

```bash
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ghp_yourTokenHere"
```

### Step 4: Approve and serve

```bash
toolwright gate allow --all
toolwright serve
```

### Step 5: Connect to Claude Desktop

```bash
toolwright config
```

Paste the JSON output into your Claude Desktop config:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

Restart Claude Desktop.

---

## Troubleshooting

**"Playwright not installed"**
```bash
pip install "toolwright[playwright]"
python -m playwright install chromium    # use the same interpreter you installed with; on some systems use python3
```

**"No auth configured for api.github.com"** — Check: `echo $TOOLWRIGHT_AUTH_API_GITHUB_COM` (should start with `Bearer `)

**"No API traffic was captured"** — Browse more pages (repo pages, issue lists, pull requests). Or use `toolwright create github` for full OpenAPI coverage.

**"Refusing to serve N tools"** — Use `--scope`: `toolwright serve --scope repos,issues`

**Claude Desktop doesn't see the tools** — Check `toolwright config` paths are absolute, restart Claude Desktop, verify `toolwright serve` runs without errors.

## Next steps

- Browse your tools: `toolwright groups list`
- Check auth: `toolwright auth check`
- Detect API drift: `toolwright drift`
- Advanced monitoring: `toolwright serve --watch --auto-heal safe`
- See all commands: `toolwright --help`
