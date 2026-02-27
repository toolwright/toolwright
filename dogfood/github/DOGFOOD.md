# GitHub API Dogfood

Toolwright self-dogfood using a curated subset of the GitHub REST API.

## What's committed

| File | Purpose |
|------|---------|
| `curate_spec.py` | Downloads + curates the GitHub OpenAPI spec |
| `github-api-scoped.yaml` | Curated spec (10 paths, ~21 operations) |
| `toolpack.yaml` | Toolpack manifest |
| `artifact/` | tools.json, policy.yaml, toolsets.yaml, baseline.json |
| `lockfile/` | Pending and approved lockfiles (21 tools, all approved) |
| `snapshot/` | Baseline snapshot (digests.json + artifact copies) for CI gate check |
| `vars.env` | Reference parameters for manual runs; CI currently hardcodes paths |
| `DOGFOOD.md` | This file |

## Pinned source

- **Repo:** [github/rest-api-description](https://github.com/github/rest-api-description)
- **Commit SHA:** `f710064757236b11a150543536a59c383344474a`
- **Spec file:** `descriptions/api.github.com/api.github.com.yaml`

## Curated endpoints

| Path | Methods |
|------|---------|
| `/repos/{owner}/{repo}` | GET |
| `/repos/{owner}/{repo}/issues` | GET, POST |
| `/repos/{owner}/{repo}/issues/{issue_number}` | GET, PATCH |
| `/repos/{owner}/{repo}/issues/{issue_number}/comments` | GET, POST |
| `/repos/{owner}/{repo}/pulls` | GET |
| `/repos/{owner}/{repo}/pulls/{pull_number}` | GET |
| `/repos/{owner}/{repo}/commits` | GET |
| `/repos/{owner}/{repo}/contents/{path}` | GET, PUT, DELETE |
| `/repos/{owner}/{repo}/labels` | GET, POST |
| `/user` | GET |

## Refreshing the spec

```bash
# Re-download from the pinned commit and re-curate
python3 dogfood/github/curate_spec.py --refresh
```

To update the pinned SHA, edit `PINNED_SHA` in `curate_spec.py` and re-run.

## CI usage

**PR gate:** `.github/workflows/gate-check.yaml` runs `toolwright diff` + `toolwright gate check`
against the committed toolpack. Triggers on PRs that modify `toolwright/core/`,
`toolwright/mcp/`, `toolwright/cli/`, or `dogfood/github/`.

**Drift check:** Not wired for the GitHub dogfood. The spec is pinned at a static
commit SHA -- it can't drift. Drift detection requires a live API whose upstream
can change independently (e.g. a team's Jira or internal API). When we add a live
API dogfood target, the drift workflow template at
`.github/workflows/drift-check.yaml.example` can be instantiated with a fresh
capture step.
