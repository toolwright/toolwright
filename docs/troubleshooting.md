# Troubleshooting

Common issues and how to fix them.

## Installation

### `pip install toolwright` fails with Python version error

Cask requires Python 3.11+. Check your version:

```bash
python3 --version
```

If you're on an older version, install Python 3.11+ via [python.org](https://www.python.org/downloads/) or your package manager:

```bash
# macOS
brew install python@3.12

# Ubuntu/Debian
sudo apt install python3.12
```

### Playwright not installed / browser binaries missing

Live browser capture requires Playwright and Chromium:

```bash
pip install "toolwright[playwright]"
python -m playwright install chromium
```

If you see `BrowserType.launch: Executable doesn't exist`, run the install command again. Playwright downloads browser binaries to `~/.cache/ms-playwright/`.

## Capture

### `cask mint` opens browser but nothing is captured

Make sure you pass the correct API host with `-a`:

```bash
cask mint https://app.example.com -a api.example.com
```

Only requests matching the allowlisted host(s) are captured. If your app makes API calls to a different domain, add it with another `-a` flag:

```bash
cask mint https://app.example.com -a api.example.com -a cdn.example.com
```

### CloudFlare / bot detection blocking capture

Some sites block automated browsers. Try:

1. Use `--headed` mode to interact with the browser manually
2. Import a HAR file from your browser's DevTools instead:
   - Open DevTools (F12) -> Network tab
   - Use the app normally
   - Right-click -> "Save all as HAR"
   - `cask capture import traffic.har -a api.example.com`

### OpenAPI import doesn't detect the spec format

Cask auto-detects OpenAPI specs by looking for `openapi:` or `swagger:` keys. If detection fails, check that the file is valid YAML or JSON and contains the spec version field.

## Compilation

### `cask compile` produces no tools

This usually means no endpoints matched the allowlist. Check:

1. Your capture file contains requests (inspect the HAR file)
2. The `-a` host matches the actual API domain in the traffic
3. Endpoints aren't being filtered out by scope rules

### Tool names look wrong or duplicate

Tool names are derived from the HTTP method and path. If you have conflicting paths (e.g., `/api/v1/users` and `/api/v2/users`), they may collide. Use `cask diff` to inspect the generated tools.

## Governance

### `cask serve` fails with "no lockfile found"

Cask enforces fail-closed governance. You must approve tools before serving:

```bash
# Generate lockfile entries
cask gate sync --tools .toolwright/toolpacks/*/tools.json

# Approve all tools
cask gate allow --all

# Now serve
cask serve --toolpack .toolwright/toolpacks/*/toolpack.yaml
```

### `cask gate check` exits non-zero in CI

This means not all tools are approved. Run `cask gate status` to see which tools are pending or blocked:

```bash
cask gate status
```

Then approve or explicitly block the remaining tools:

```bash
cask gate allow tool_name_1 tool_name_2
cask gate block dangerous_tool --reason "Not needed in production"
```

### Signature verification failed

Lockfile signatures use Ed25519. Verification fails if:

1. The lockfile was manually edited (signatures become invalid)
2. The signing key changed

To re-sign with the current key:

```bash
cask gate reseal
```

## Runtime

### Host not in allowlist

The MCP server blocks requests to hosts not in the toolpack's allowlist. This is by design (safe by default). To add a host:

1. Re-capture traffic including the new host: `cask mint ... -a new-host.example.com`
2. Or manually add it to the toolpack configuration

### SSRF / metadata endpoint blocked

Cask blocks requests to cloud metadata endpoints (169.254.169.254, fd00::, etc.) and private IP ranges by default. This is a security feature and cannot be bypassed.

### Auth pre-check failures

If tools fail at runtime with auth errors:

1. Check that your auth credentials/tokens are still valid
2. Re-capture traffic with fresh credentials
3. Verify the auth configuration in your toolpack

## MCP Client Connection

### Claude Desktop can't connect to Cask MCP server

1. Verify the config in `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-api": {
      "command": "cask",
      "args": ["serve", "--toolpack", "/absolute/path/to/toolpack.yaml"]
    }
  }
}
```

2. Make sure the path to `toolpack.yaml` is **absolute**, not relative
3. Make sure `cask` is in your PATH (try running `cask --version` in a terminal)
4. Restart Claude Desktop after config changes

### `cask config` output doesn't work

Use the correct format for your client:

```bash
# Claude Desktop / Cursor (JSON)
cask config --toolpack .toolwright/toolpacks/*/toolpack.yaml --format json

# Codex (TOML)
cask config --toolpack .toolwright/toolpacks/*/toolpack.yaml --format codex
```

## Drift Detection

### `cask drift` reports unexpected changes

Drift detection compares the current tool surface against a baseline. Common causes of drift:

- API added new endpoints
- Endpoint schemas changed (new fields, type changes)
- Hosts were added or removed

Review the drift report, then update your toolpack:

```bash
# Re-capture and recompile
cask mint https://app.example.com -a api.example.com

# Review changes
cask diff --toolpack .toolwright/toolpacks/*/toolpack.yaml

# Re-approve
cask gate allow --all
```

## Still Stuck?

- Check [Known Limitations](known-limitations.md) for documented caveats
- Open a [GitHub Issue](https://github.com/toolwright/Toolwright/issues) with:
  - What you ran (full command)
  - What happened (full error output)
  - Your environment (`python3 --version`, `cask --version`, OS)
