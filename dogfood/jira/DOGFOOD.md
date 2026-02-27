# Jira Cloud Platform API Dogfood

Toolwright self-dogfood using a curated subset of the Jira Cloud Platform REST API.

## What's committed

| File | Purpose |
|------|---------|
| `curate_spec.py` | Downloads + curates the Jira OpenAPI spec |
| `jira-api-scoped.yaml` | Curated spec (10 paths, 12 operations) |
| `toolpack.yaml` | Toolpack manifest |
| `artifact/` | tools.json, policy.yaml, toolsets.yaml, baseline.json |
| `lockfile/` | Pending and approved lockfiles |
| `snapshot/` | Baseline snapshot (digests.json) for CI gate check |
| `vars.env` | Reference parameters for manual runs |
| `DOGFOOD.md` | This file |

## Source spec

- **URL:** `https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json`
- **Version:** Rolling (`1001.0.0-SNAPSHOT`) -- no pinned git SHA
- **Pinning strategy:** SHA-256 content hash of raw downloaded bytes + HTTP metadata
- **Auth:** Basic auth (`Authorization: Basic BASE64(email:api_token)`)

## Curated endpoints

The `/rest/api/3` prefix is absorbed into the server URL so the compiler does
not treat the bare `3` as a dynamic path parameter. Full URLs resolve to e.g.
`https://your-domain.atlassian.net/rest/api/3/issue/{issueIdOrKey}`.

### Read-only (GET)

| Tool path | Methods |
|-----------|---------|
| `/issue/{issueIdOrKey}` | GET |
| `/search/jql` | GET |
| `/issue/{issueIdOrKey}/comment` | GET |
| `/issue/{issueIdOrKey}/comment/{id}` | GET |
| `/issue/{issueIdOrKey}/transitions` | GET |
| `/project` | GET |
| `/project/{projectIdOrKey}` | GET |
| `/users/search` | GET |
| `/user` | GET |

### Write (behind confirmation)

| Tool path | Methods |
|-----------|---------|
| `/issue` | POST |
| `/issue/{issueIdOrKey}/comment` | POST |
| `/issue/{issueIdOrKey}/transitions` | POST |

## Confirmation flow

Write endpoints require human confirmation at runtime:

```
1. AI agent calls create_issue tool
2. Toolwright returns: confirmation required, token=cfrmv1.xxx
3. Human runs: toolwright confirm grant cfrmv1.xxx
4. AI agent retries with token -- request proceeds
```

## Refreshing the spec

```bash
# Re-download and re-curate
python3 dogfood/jira/curate_spec.py --refresh
```

## CI usage

**PR gate:** `.github/workflows/gate-check.yaml` runs `toolwright gate check`
against the committed toolpack. Triggers on PRs that modify `toolwright/core/`,
`toolwright/mcp/`, `toolwright/cli/`, or `dogfood/jira/`.

**Drift check:** The Jira spec is a rolling SNAPSHOT with no pinned version.
Drift detection uses content-hash comparison via `curate_spec.py --check`,
which is suitable for scheduled/manual runs but NOT for PR gating (the
upstream spec will change between runs). No Jira token is stored in CI.
