# Troubleshooting

Common issues and how to fix them.

## Installation

### `pip install toolwright` fails with Python version error

Toolwright requires Python 3.11+. Check your version:

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

### `toolwright mint` opens browser but nothing is captured

Make sure you pass the correct API host with `-a`:

```bash
toolwright mint https://app.example.com -a api.example.com
```

Only requests matching the allowlisted host(s) are captured. If your app makes API calls to a different domain, add it with another `-a` flag:

```bash
toolwright mint https://app.example.com -a api.example.com -a cdn.example.com
```

### CloudFlare / bot detection blocking capture

Some sites block automated browsers. Try:

1. Use `--headed` mode to interact with the browser manually
2. Import a HAR file from your browser's DevTools instead:
   - Open DevTools (F12) -> Network tab
   - Use the app normally
   - Right-click -> "Save all as HAR"
   - `toolwright capture import traffic.har -a api.example.com`

### OpenAPI import doesn't detect the spec format

Toolwright auto-detects OpenAPI specs by looking for `openapi:` or `swagger:` keys. If detection fails, check that the file is valid YAML or JSON and contains the spec version field.

## Compilation

### `toolwright compile` produces no tools

This usually means no endpoints matched the allowlist. Check:

1. Your capture file contains requests (inspect the HAR file)
2. The `-a` host matches the actual API domain in the traffic
3. Endpoints aren't being filtered out by scope rules

### Tool names look wrong or duplicate

Tool names are derived from the HTTP method and path. If you have conflicting paths (e.g., `/api/v1/users` and `/api/v2/users`), they may collide. Use `toolwright diff` to inspect the generated tools.

## Governance

### `toolwright serve` fails with "no lockfile found"

Toolwright enforces fail-closed governance. You must approve tools before serving:

```bash
# Generate lockfile entries
toolwright gate sync --toolpack .toolwright/toolpacks/my-api/toolpack.yaml

# Approve all tools
toolwright gate allow --all --toolpack .toolwright/toolpacks/my-api/toolpack.yaml

# Now serve
toolwright serve --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

### `toolwright gate check` exits non-zero in CI

This means not all tools are approved. The `gate check` output will suggest the approval command. Run `toolwright gate status` to see which tools are pending or blocked:

```bash
toolwright gate status --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

Then approve or explicitly block the remaining tools:

```bash
toolwright gate allow tool_name_1 tool_name_2 --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
toolwright gate block dangerous_tool --reason "Not needed in production" --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

### Signature verification failed

Lockfile signatures use Ed25519. Verification fails if:

1. The lockfile was manually edited (signatures become invalid)
2. The signing key changed

To re-sign with the current key:

```bash
toolwright gate reseal
```

## Runtime

### Host not in allowlist

The MCP server blocks requests to hosts not in the toolpack's allowlist. This is by design (safe by default). To add a host:

1. Re-capture traffic including the new host: `toolwright mint ... -a new-host.example.com`
2. Or manually add it to the toolpack configuration

### SSRF / private range / metadata endpoint blocked

Toolwright enforces network safety at two levels:

- **Cloud metadata endpoints** (169.254.169.254, fd00::, etc.) are unconditionally blocked. No flag overrides this.
- **Private IP ranges** (10.x, 172.16-31.x, 192.168.x) are blocked by default. Use `--allow-private-cidr` to allow specific private ranges when needed (e.g., internal APIs). All requests to private ranges are audit-logged.
- **Redirects** are blocked by default. Use `--allow-redirects` to permit redirects; SSRF checks still apply to each redirect target.

### Auth pre-check failures

If tools fail at runtime with auth errors:

1. Check that your auth credentials/tokens are still valid
2. Set auth via environment variable (recommended):
   ```bash
   export TOOLWRIGHT_AUTH_HEADER="Bearer your-token-here"
   toolwright serve --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
   ```
3. For multi-host toolpacks, use per-host env vars:
   ```bash
   export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer github-token"
   ```
   Naming: replace dots/hyphens with underscores, uppercase everything.
4. Verify auth priority: `--auth` flag > `TOOLWRIGHT_AUTH_<HOST>` > `TOOLWRIGHT_AUTH_HEADER`
5. Use `toolwright health --tools <path>` to check which endpoints have auth issues — failures will be classified as `auth_expired`

### `toolwright health` shows `auth_expired` for all endpoints

Your auth token is missing or expired. Set it via env var:

```bash
export TOOLWRIGHT_AUTH_HEADER="Bearer your-fresh-token"
toolwright health --tools .toolwright/toolpacks/my-api/artifact/tools.json
```

## Circuit Breakers

### Tool calls are being blocked unexpectedly

A circuit breaker may have tripped. Check the quarantine report:

```bash
toolwright quarantine
```

If a tool was manually killed, re-enable it:

```bash
toolwright enable <tool_id>
```

If it tripped automatically (5 consecutive failures), it will auto-recover after 60 seconds via HALF_OPEN state.

### Circuit breaker state file is corrupted

Delete the state file and restart. All breakers will reset to CLOSED:

```bash
rm .toolwright/state/circuit_breakers.json
toolwright serve --toolpack .toolwright/toolpacks/my-api/toolpack.yaml
```

## Reconciliation & Watch Mode

### `--watch` mode isn't detecting API changes

Reconciliation probes endpoints on a risk-tier schedule (critical: 120s, high: 300s, medium: 600s, low: 1800s). If drift isn't being detected:

1. Verify watch is running: `toolwright watch status`
2. Check that the endpoint is actually reachable from your environment
3. Review the event log for probe errors: `toolwright watch log --tool <tool_name> --last 10`

### Auto-heal applied an unwanted patch

Every auto-repair is preceded by a snapshot. Restore the previous state:

```bash
toolwright snapshots           # find the snapshot before the unwanted patch
toolwright rollback <snapshot-id>
```

To prevent future auto-applies, set `--auto-heal off` or configure specific tools in `.toolwright/watch.yaml`.

### Watch mode stopped after a failure

If the reconciliation loop exits unexpectedly, check the server logs for the root cause. Common issues:

- State file corruption: delete `.toolwright/state/watch_state.json` and restart
- Permission errors on the state directory: ensure `.toolwright/state/` is writable

## MCP Client Connection

### Claude Desktop can't connect to Toolwright MCP server

1. Verify the config in `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-api": {
      "command": "toolwright",
      "args": ["serve", "--toolpack", "/absolute/path/to/toolpack.yaml"]
    }
  }
}
```

2. Make sure the path to `toolpack.yaml` is **absolute**, not relative
3. Make sure `toolwright` is in your PATH (try running `toolwright --version` in a terminal)
4. Restart Claude Desktop after config changes

### `toolwright config` output doesn't work

Use the correct format for your client:

```bash
# Claude Desktop / Cursor (JSON)
toolwright config --toolpack .toolwright/toolpacks/*/toolpack.yaml --format json

# Codex (TOML)
toolwright config --toolpack .toolwright/toolpacks/*/toolpack.yaml --format codex
```

## Drift Detection

### `toolwright drift` reports unexpected changes

Drift detection compares the current tool surface against a baseline. Common causes of drift:

- API added new endpoints
- Endpoint schemas changed (new fields, type changes)
- Hosts were added or removed

Review the drift report, then update your toolpack:

```bash
# Re-capture and recompile
toolwright mint https://app.example.com -a api.example.com

# Review changes
toolwright diff --toolpack .toolwright/toolpacks/*/toolpack.yaml

# Re-approve
toolwright gate allow --all
```

## Still Stuck?

- Check [Known Limitations](known-limitations.md) for documented caveats
- Open a [GitHub Issue](https://github.com/toolwright/Toolwright/issues) with:
  - What you ran (full command)
  - What happened (full error output)
  - Your environment (`python3 --version`, `toolwright --version`, OS)
