"""CLI tests for compile command output-format surface."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from click.testing import CliRunner

from toolwright.cli.main import cli
from toolwright.models.capture import CaptureSession, CaptureSource, HttpExchange, HTTPMethod
from toolwright.storage import Storage


def _write_capture(tmp_path: Path) -> CaptureSession:
    session = CaptureSession(
        id="cap_compile",
        name="Compile Demo",
        source=CaptureSource.HAR,
        created_at=datetime(2026, 2, 6, tzinfo=UTC),
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url="https://api.example.com/api/users",
                method=HTTPMethod.GET,
                host="api.example.com",
                path="/api/users",
                response_status=200,
                response_content_type="application/json",
            )
        ],
    )
    storage = Storage(base_path=tmp_path / ".toolwright")
    storage.save_capture(session)
    return session


def _write_graphql_capture(tmp_path: Path) -> CaptureSession:
    session = CaptureSession(
        id="cap_compile_graphql",
        name="Compile GraphQL Demo",
        source=CaptureSource.HAR,
        created_at=datetime(2026, 2, 6, tzinfo=UTC),
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url="https://api.example.com/api/graphql",
                method=HTTPMethod.POST,
                host="api.example.com",
                path="/api/graphql",
                request_body_json={
                    "operationName": "RecentlyViewedProducts",
                    "query": "query RecentlyViewedProducts($limit: Int!) { recentlyViewed(limit: $limit) { id } }",
                    "variables": {"limit": 1},
                },
                response_status=200,
                response_content_type="application/json",
                response_body_json={"data": {"recentlyViewed": [{"id": "p1"}]}},
            )
        ],
    )
    storage = Storage(base_path=tmp_path / ".toolwright")
    storage.save_capture(session)
    return session


def _write_graphql_multi_operation_capture(tmp_path: Path) -> CaptureSession:
    session = CaptureSession(
        id="cap_compile_graphql_multi",
        name="Compile GraphQL Multi Demo",
        source=CaptureSource.HAR,
        created_at=datetime(2026, 2, 6, tzinfo=UTC),
        allowed_hosts=["api.example.com"],
        exchanges=[
            HttpExchange(
                url="https://api.example.com/api/graphql",
                method=HTTPMethod.POST,
                host="api.example.com",
                path="/api/graphql",
                request_body_json={
                    "operationName": "RecentlyViewedProducts",
                    "query": "query RecentlyViewedProducts($limit: Int!) { recentlyViewed(limit: $limit) { id } }",
                    "variables": {"limit": 1},
                },
                response_status=200,
                response_content_type="application/json",
                response_body_json={"data": {"recentlyViewed": [{"id": "p1"}]}},
            ),
            HttpExchange(
                url="https://api.example.com/api/graphql",
                method=HTTPMethod.POST,
                host="api.example.com",
                path="/api/graphql",
                request_body_json={
                    "operationName": "TrackEvent",
                    "query": "mutation TrackEvent($event: String!) { trackEvent(event: $event) { ok } }",
                    "variables": {"event": "click"},
                },
                response_status=200,
                response_content_type="application/json",
                response_body_json={"data": {"trackEvent": {"ok": True}}},
            ),
        ],
    )
    storage = Storage(base_path=tmp_path / ".toolwright")
    storage.save_capture(session)
    return session


def test_compile_rejects_mcp_python_format() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["compile", "--capture", "cap_dummy", "--format", "mcp-python"],
    )

    assert result.exit_code != 0
    assert "Invalid value for '--format' / '-f'" in result.stderr


def test_compile_manifest_format_still_works(tmp_path: Path, monkeypatch) -> None:
    session = _write_capture(tmp_path)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "compile",
            "--capture",
            session.id,
            "--scope",
            "first_party_only",
            "--format",
            "manifest",
            "--output",
            ".toolwright/artifacts",
        ],
    )

    assert result.exit_code == 0
    assert "Compile complete:" in result.stdout
    artifacts_root = tmp_path / ".toolwright" / "artifacts"
    artifact_dirs = [p for p in artifacts_root.iterdir() if p.is_dir()]
    assert artifact_dirs
    artifact_dir = artifact_dirs[0]
    assert (artifact_dir / "tools.json").exists()
    assert (artifact_dir / "toolsets.yaml").exists()
    assert (artifact_dir / "policy.yaml").exists()
    assert (artifact_dir / "baseline.json").exists()
    assert (artifact_dir / "contracts.yaml").exists()
    coverage_path = artifact_dir / "coverage_report.json"
    assert coverage_path.exists()
    payload = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "coverage_report"
    assert "precision" in payload["metrics"]
    assert "recall" in payload["metrics"]


def test_compile_coverage_report_uses_action_ids_for_graphql_ops(
    tmp_path: Path, monkeypatch
) -> None:
    session = _write_graphql_capture(tmp_path)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "compile",
            "--capture",
            session.id,
            "--scope",
            "first_party_only",
            "--format",
            "manifest",
            "--output",
            ".toolwright/artifacts",
        ],
    )

    assert result.exit_code == 0
    artifacts_root = tmp_path / ".toolwright" / "artifacts"
    artifact_dirs = [p for p in artifacts_root.iterdir() if p.is_dir()]
    assert artifact_dirs
    artifact_dir = artifact_dirs[0]

    tools = json.loads((artifact_dir / "tools.json").read_text(encoding="utf-8"))
    graphql_actions = [a for a in tools["actions"] if a["path"] == "/api/graphql"]
    assert len(graphql_actions) == 1
    graphql_action = graphql_actions[0]

    coverage = json.loads((artifact_dir / "coverage_report.json").read_text(encoding="utf-8"))
    candidates = coverage["candidates"]
    match = [c for c in candidates if c["tool_id"] == graphql_action["id"]]
    assert match, "Expected coverage report to reference the published GraphQL action id"
    assert match[0]["request_fingerprint"] == graphql_action["signature_id"]


def test_compile_scopes_suggestions_reference_published_graphql_action_signatures(
    tmp_path: Path, monkeypatch
) -> None:
    session = _write_graphql_multi_operation_capture(tmp_path)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "compile",
            "--capture",
            session.id,
            "--scope",
            "first_party_only",
            "--format",
            "manifest",
            "--output",
            ".toolwright/artifacts",
        ],
    )

    assert result.exit_code == 0
    artifacts_root = tmp_path / ".toolwright" / "artifacts"
    artifact_dirs = [p for p in artifacts_root.iterdir() if p.is_dir()]
    assert artifact_dirs
    artifact_dir = artifact_dirs[0]

    tools = json.loads((artifact_dir / "tools.json").read_text(encoding="utf-8"))
    graphql_actions = [a for a in tools["actions"] if a["path"] == "/api/graphql"]
    assert len(graphql_actions) == 2
    query_actions = [a for a in graphql_actions if "read" in (a.get("tags") or [])]
    mutation_actions = [a for a in graphql_actions if "write" in (a.get("tags") or [])]
    assert len(query_actions) == 1
    assert len(mutation_actions) == 1

    query_action = query_actions[0]
    mutation_action = mutation_actions[0]

    scope_suggestions = yaml.safe_load((artifact_dir / "scopes.suggested.yaml").read_text(encoding="utf-8"))
    drafts = scope_suggestions.get("drafts") or []

    # Drafts should reference published action signature IDs (post GraphQL operation splitting),
    # not the raw endpoint signature for /api/graphql.
    by_id = {d.get("endpoint_id"): d for d in drafts if isinstance(d, dict)}
    assert query_action["signature_id"] in by_id
    assert mutation_action["signature_id"] in by_id

    assert by_id[query_action["signature_id"]]["scope_name"] == "read"
    assert by_id[mutation_action["signature_id"]]["scope_name"] == "write"


def test_compile_creates_toolpack_directory(tmp_path: Path, monkeypatch) -> None:
    """compile should create a toolpack directory with toolpack.yaml,
    so users can immediately use `toolwright serve --toolpack` without manual steps.
    This is F-004: the capture import + compile golden path must work end-to-end."""
    session = _write_capture(tmp_path)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "compile",
            "--capture",
            session.id,
            "--scope",
            "first_party_only",
            "--format",
            "all",
        ],
    )

    assert result.exit_code == 0, result.output

    # A toolpack directory should exist under .toolwright/toolpacks/
    toolpacks_dir = tmp_path / ".toolwright" / "toolpacks"
    assert toolpacks_dir.exists(), "compile should create .toolwright/toolpacks/"
    toolpack_dirs = [p for p in toolpacks_dir.iterdir() if p.is_dir()]
    assert len(toolpack_dirs) == 1, f"Expected 1 toolpack dir, got {len(toolpack_dirs)}"

    tp_dir = toolpack_dirs[0]
    toolpack_yaml = tp_dir / "toolpack.yaml"
    assert toolpack_yaml.exists(), "toolpack.yaml must exist"

    # Artifact subdirectory with compiled files
    artifact_dir = tp_dir / "artifact"
    assert artifact_dir.is_dir(), "artifact/ subdirectory must exist"
    assert (artifact_dir / "tools.json").exists()
    assert (artifact_dir / "toolsets.yaml").exists()
    assert (artifact_dir / "policy.yaml").exists()
    assert (artifact_dir / "baseline.json").exists()

    # Lockfile subdirectory with pending lockfile
    lockfile_dir = tp_dir / "lockfile"
    assert lockfile_dir.is_dir(), "lockfile/ subdirectory must exist"
    pending_files = list(lockfile_dir.glob("*.pending.*"))
    assert pending_files, "pending lockfile must exist"

    # toolpack.yaml should be loadable and reference correct paths
    tp_data = yaml.safe_load(toolpack_yaml.read_text())
    assert tp_data["capture_id"] == session.id
    assert tp_data["scope"] == "first_party_only"
    assert "tools" in tp_data["paths"]
    assert "lockfiles" in tp_data["paths"]

    # compile output should mention the toolpack path
    assert "toolpack" in result.output.lower()


def test_compile_next_steps_include_toolpack_path(tmp_path: Path, monkeypatch) -> None:
    """After compile, next-steps output must include copy-pasteable commands
    with the actual --toolpack <path> argument so users don't have to guess."""
    session = _write_capture(tmp_path)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli,
        [
            "compile",
            "--capture",
            session.id,
            "--scope",
            "first_party_only",
            "--format",
            "all",
        ],
    )

    assert result.exit_code == 0, result.output

    # Find the toolpack.yaml that was created
    toolpacks_dir = tmp_path / ".toolwright" / "toolpacks"
    toolpack_dirs = [p for p in toolpacks_dir.iterdir() if p.is_dir()]
    assert len(toolpack_dirs) == 1
    tp_dir = toolpack_dirs[0]
    toolpack_yaml = tp_dir / "toolpack.yaml"
    assert toolpack_yaml.exists()

    # The compile output uses the relative path as returned by _package_toolpack
    # (since root_path defaults to ".toolwright", the path is relative to cwd)
    toolpack_id = tp_dir.name
    expected_path = f".toolwright/toolpacks/{toolpack_id}/toolpack.yaml"

    # Output must contain copy-pasteable next-step commands with the toolpack path
    output = result.output
    assert "Next steps:" in output, "Should show 'Next steps:' header"
    assert f"toolwright gate sync --toolpack {expected_path}" in output
    assert f"toolwright gate allow --all --toolpack {expected_path}" in output
    assert f"toolwright serve --toolpack {expected_path}" in output
