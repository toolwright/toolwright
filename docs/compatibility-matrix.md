# Compatibility Matrix (v1)

## Command compatibility aliases

| Canonical | Alias | Status |
|---|---|---|
| `diff` | `plan` | Supported |
| `gate` | `approve` | Supported |
| `mcp inspect` | `mcp meta` | Supported |

## Lockfile compatibility

Runtime lockfile resolution order:

1. toolpack configured approved lockfile path
2. `lockfile/toolwright.lock.approved.yaml`
3. `lockfile/toolwright.lock.yaml` (legacy)

Pending lockfiles are not runtime-authoritative unless explicit unsafe mode is used.

## Artifact compatibility

- Preferred contract artifact: `contracts.yaml`
- Legacy compatibility: `contract.yaml`, `contract.json` are still read when needed

## Runtime modes

| Runtime mode | Command | Notes |
|---|---|---|
| Local MCP runtime | `run` / `mcp serve` | Default for v1 |
| HTTP gateway evaluate/proxy | `enforce` | Optional integration path |
| Control-plane introspection | `mcp inspect` | Read-only by design |

## Toolset defaults

When toolsets are present and no explicit toolset is selected, runtime defaults to `readonly`.
