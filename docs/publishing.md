# Publishing Toolwright

## PyPI

This repository includes `.github/workflows/publish-pypi.yaml` to publish from tags
using PyPI Trusted Publishing.

Install-doc truth gate:

- README install section must match the currently published path (`pip install toolwright`).
- Keep command snippets defaulted to `toolwright` (not `cask`).

### One-time setup

1. Create/register the `toolwright` project on PyPI.
2. In PyPI project settings, add a Trusted Publisher:
   - Owner: `Toolwright`
   - Repository: `Toolwright`
   - Workflow: `publish-pypi.yaml`
   - Environment: `pypi`
3. In GitHub repo settings, create an Environment named `pypi`.

### Release

1. Bump version in:
   - `pyproject.toml`
   - `toolwright/__init__.py`
2. Update `CHANGELOG.md` (canonical release history).
   - `docs/releases/` contains historical alpha notes and should not be treated as the primary release ledger.
3. Tag and push (recommended to mirror PEP 440):

```bash
git tag v<pep440-version>
git push origin v<pep440-version>
```

4. GitHub Actions builds and publishes to PyPI.

Tag naming guidance:

- Package version uses PEP 440 (example: `0.2.0b1`).
- Prefer matching tag format `v<pep440-version>` for consistency.
- If legacy `v0.1.0-alpha.4` tags are used, document the mapping in release notes.

### Verify

```bash
pip install -U toolwright
toolwright --help
```

## Official MCP Registry

MCP Registry publishing is managed by the official publisher tooling.

Pre-reqs:
- README includes an `mcp-name` marker (already present):
  - `io.github.toolwright/toolwright`
- Root `server.json` is present and kept in sync with released package version.
- Repository is public.

Run:

```bash
npx -y @modelcontextprotocol/mcp-publisher@latest publish
```

Follow prompts to authenticate and submit metadata.

Notes:
- Registry metadata and packaging paths may differ by ecosystem.
- Some examples in official docs are npm-oriented; for Python packages,
  ensure metadata points to the published PyPI package and repo docs.
