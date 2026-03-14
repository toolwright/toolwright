# Publishing Toolwright

## PyPI

This repository publishes to PyPI with:

- `.github/workflows/ci.yml` for required release checks
- `.github/workflows/publish.yml` for trusted publishing after those checks pass

Install-doc truth gate:

- README install section must match the currently published path (`pip install toolwright`).
- Keep the public alpha docs centered on the supported path: `demo`, `create github`, `config`, `serve`, and basic `gate` / `status`.

### One-time setup

1. Create/register the `toolwright` project on PyPI.
2. In PyPI project settings, add a Trusted Publisher:
   - Owner: `Toolwright`
   - Repository: `Toolwright`
   - Workflow: `publish.yml`
   - Environment: `pypi`
3. In GitHub repo settings, create an Environment named `pypi`.

### Release

1. Bump version in:
   - `pyproject.toml`
   - `toolwright/__init__.py`
2. Update `CHANGELOG.md` (canonical release history) for the exact version being released.
   - `docs/releases/` contains historical alpha notes and should not be treated as the primary release ledger.
3. Ensure `.github/workflows/ci.yml` is green for the release commit.
4. Tag and push (recommended to mirror PEP 440):

```bash
git tag v<pep440-version>
git push origin v<pep440-version>
```

5. Publish a GitHub release from that tag. `.github/workflows/publish.yml` re-runs the reusable CI checks, builds fresh distributions, and publishes to PyPI only if they pass.

Tag naming guidance:

- Package version uses PEP 440 (example: `0.2.0b1`).
- Prefer matching tag format `v<pep440-version>` for consistency.
- If legacy `v0.1.0-alpha.4` tags are used, document the mapping in release notes.

### Verify

```bash
pip install -U toolwright
toolwright --help
toolwright demo --out /tmp/toolwright-release-smoke
```

## MCP Registry

MCP Registry publication is intentionally deferred for this public alpha. Ship the PyPI + GitHub path first, then add registry metadata and publication once the repo carries the required registry-specific files and release process.
