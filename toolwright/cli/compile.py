"""Compile command implementation."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml

from toolwright.cli.approve import sync_lockfile
from toolwright.core.compile import (
    BaselineGenerator,
    ContractCompiler,
    PolicyGenerator,
    ToolManifestGenerator,
    ToolsetGenerator,
)
from toolwright.core.normalize import EndpointAggregator
from toolwright.core.scope import ScopeEngine
from toolwright.core.toolpack import (
    Toolpack,
    ToolpackOrigin,
    ToolpackPaths,
    ToolpackRuntime,
    write_toolpack,
)
from toolwright.models.capture import CaptureSession
from toolwright.models.scope import Scope
from toolwright.storage import Storage
from toolwright.utils.schema_version import resolve_generated_at


@dataclass(frozen=True)
class CompileResult:
    """Compiled artifact metadata and generated paths."""

    artifact_id: str
    output_path: Path
    scope: Scope
    endpoint_count: int
    generated_at: datetime
    artifacts_created: tuple[tuple[str, Path], ...]
    contracts_path: Path | None = None
    coverage_report_path: Path | None = None
    contract_yaml_path: Path | None = None
    contract_json_path: Path | None = None
    tools_path: Path | None = None
    toolsets_path: Path | None = None
    policy_path: Path | None = None
    baseline_path: Path | None = None


def compile_capture_session(
    session: CaptureSession,
    scope_name: str,
    scope_file: str | None,
    output_format: str,
    output_dir: str | Path,
    deterministic: bool = True,
    verbose: bool = False,
) -> CompileResult:
    """Compile a capture session into Toolwright artifacts."""
    if verbose:
        click.echo(f"Loaded capture: {session.id}")
        click.echo(f"  Exchanges: {len(session.exchanges)}")

    if verbose:
        click.echo("Aggregating endpoints...")

    aggregator = EndpointAggregator(first_party_hosts=session.allowed_hosts)
    endpoints = aggregator.aggregate(session)

    if verbose:
        click.echo(f"  Endpoints: {len(endpoints)}")

    scope_engine = ScopeEngine(first_party_hosts=session.allowed_hosts)
    scope = scope_engine.load_scope(scope_name, scope_file)

    filtered_endpoints = scope_engine.filter_endpoints(endpoints, scope)
    filtered_endpoints = sorted(
        filtered_endpoints,
        key=lambda ep: (ep.host, ep.method.upper(), ep.path, ep.signature_id),
    )

    if verbose:
        click.echo(f"  After scope filter: {len(filtered_endpoints)}")

    # Detect flows (parent/child endpoint dependencies)
    from toolwright.core.normalize.flow_detector import FlowDetector

    flow_graph = FlowDetector().detect(filtered_endpoints)
    if verbose and flow_graph.edges:
        click.echo(f"  Flow edges: {len(flow_graph.edges)}")

    generated_at = resolve_generated_at(
        deterministic=deterministic,
        candidate=session.created_at if deterministic else None,
    )
    artifact_id = _generate_artifact_id(
        session_id=session.id,
        scope_name=scope.name,
        output_format=output_format,
        deterministic=deterministic,
    )

    output_path = Path(output_dir) / artifact_id
    output_path.mkdir(parents=True, exist_ok=True)

    artifacts_created: list[tuple[str, Path]] = []
    contracts_path: Path | None = None
    coverage_report_path: Path | None = None
    contract_yaml_path: Path | None = None
    contract_json_path: Path | None = None
    tools_path: Path | None = None
    toolsets_path: Path | None = None
    policy_path: Path | None = None
    baseline_path: Path | None = None
    manifest: dict[str, Any] | None = None
    tool_gen: ToolManifestGenerator | None = None

    if output_format in ("all", "openapi", "manifest"):
        compiler = ContractCompiler(
            title=session.name or "Generated API",
            description=f"Generated from capture {session.id}",
        )
        contract = compiler.compile(
            filtered_endpoints,
            scope=scope,
            capture_id=session.id,
            generated_at=generated_at,
        )

        contract_yaml_path = output_path / "contract.yaml"
        with open(contract_yaml_path, "w") as f:
            f.write(compiler.to_yaml(contract))
        artifacts_created.append(("Contract (YAML)", contract_yaml_path))

        contract_json_path = output_path / "contract.json"
        with open(contract_json_path, "w") as f:
            f.write(compiler.to_json(contract))
        artifacts_created.append(("Contract (JSON)", contract_json_path))

        contracts_payload = _build_contracts_payload(
            scope_name=scope.name,
            capture_id=session.id,
            generated_at=generated_at,
            endpoints=filtered_endpoints,
        )
        contracts_path = output_path / "contracts.yaml"
        with open(contracts_path, "w") as f:
            yaml.safe_dump(contracts_payload, f, sort_keys=False)
        artifacts_created.append(("Contracts", contracts_path))

        tool_gen = ToolManifestGenerator(
            name=session.name or "Generated Tools",
            description=f"Generated from capture {session.id}",
        )
        manifest = tool_gen.generate(
            filtered_endpoints,
            scope=scope,
            capture_id=session.id,
            generated_at=generated_at,
            flow_graph=flow_graph,
        )

        # Coverage report should reference the published tool/action IDs and signatures
        # (especially for GraphQL operation-scoped tools, which may derive signatures
        # from fixed bodies instead of the raw endpoint signature).
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _CoverageParam:
            name: str

        @dataclass(frozen=True)
        class _CoverageEndpoint:
            signature_id: str
            tool_id: str
            path: str
            parameters: list[_CoverageParam]

        coverage_inputs: list[_CoverageEndpoint] = []
        for action in manifest.get("actions", []):
            input_schema = action.get("input_schema") or {}
            properties = input_schema.get("properties") or {}
            params = [_CoverageParam(name=str(name)) for name in sorted(properties.keys())]
            coverage_inputs.append(
                _CoverageEndpoint(
                    signature_id=str(action.get("signature_id", "")),
                    tool_id=str(action.get("id") or action.get("name") or ""),
                    path=str(action.get("path", "")),
                    parameters=params,
                )
            )

        coverage_payload = _build_coverage_report_payload(
            scope_name=scope.name,
            capture_id=session.id,
            generated_at=generated_at,
            endpoints=coverage_inputs,
        )
        coverage_report_path = output_path / "coverage_report.json"
        with open(coverage_report_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(coverage_payload, indent=2, sort_keys=True))
        artifacts_created.append(("Coverage Report", coverage_report_path))

    if output_format in ("all", "manifest"):
        assert manifest is not None
        assert tool_gen is not None

        tools_path = output_path / "tools.json"
        with open(tools_path, "w") as f:
            f.write(tool_gen.to_json(manifest))
        artifacts_created.append(("Tool Manifest", tools_path))

        toolset_gen = ToolsetGenerator()
        toolsets = toolset_gen.generate(manifest=manifest, generated_at=generated_at)

        toolsets_path = output_path / "toolsets.yaml"
        with open(toolsets_path, "w") as f:
            f.write(toolset_gen.to_yaml(toolsets))
        artifacts_created.append(("Toolsets", toolsets_path))

    if output_format in ("all", "manifest"):
        policy_gen = PolicyGenerator(name=f"{session.name or 'Generated'} Policy")
        policy = policy_gen.generate(filtered_endpoints, scope=scope)

        policy_path = output_path / "policy.yaml"
        with open(policy_path, "w") as f:
            f.write(policy_gen.to_yaml(policy))
        artifacts_created.append(("Policy", policy_path))

        baseline_gen = BaselineGenerator()
        baseline = baseline_gen.generate(
            filtered_endpoints,
            scope=scope,
            capture_id=session.id,
            generated_at=generated_at,
        )

        baseline_path = output_path / "baseline.json"
        with open(baseline_path, "w") as f:
            f.write(baseline_gen.to_json(baseline))
        artifacts_created.append(("Baseline", baseline_path))

    # Scope inference: emit scopes.suggested.yaml
    if filtered_endpoints:
        from toolwright.core.scope.inference import ScopeInferenceEngine

        scope_engine_infer = ScopeInferenceEngine()
        scope_inputs = filtered_endpoints
        if manifest and isinstance(manifest, dict) and isinstance(manifest.get("actions"), list):
            scope_inputs = _build_scope_inference_endpoints_from_manifest(manifest)

        scope_drafts = scope_engine_infer.infer(scope_inputs)
        if scope_drafts:
            scopes_payload = {
                "version": "1.0",
                "generated_at": generated_at.isoformat(),
                "scope": scope.name,
                "drafts": [d.model_dump(mode="json") for d in scope_drafts],
            }
            scopes_path = output_path / "scopes.suggested.yaml"
            with open(scopes_path, "w") as f:
                yaml.safe_dump(scopes_payload, f, sort_keys=False)
            artifacts_created.append(("Scope Suggestions", scopes_path))
            if verbose:
                review_count = sum(1 for d in scope_drafts if d.review_required)
                click.echo(f"  Scope drafts: {len(scope_drafts)} ({review_count} need review)")

    return CompileResult(
        artifact_id=artifact_id,
        output_path=output_path,
        scope=scope,
        endpoint_count=len(filtered_endpoints),
        generated_at=generated_at,
        artifacts_created=tuple(artifacts_created),
        contracts_path=contracts_path,
        coverage_report_path=coverage_report_path,
        contract_yaml_path=contract_yaml_path,
        contract_json_path=contract_json_path,
        tools_path=tools_path,
        toolsets_path=toolsets_path,
        policy_path=policy_path,
        baseline_path=baseline_path,
    )


def _build_scope_inference_endpoints_from_manifest(manifest: dict[str, Any]) -> list[Any]:
    """Convert published manifest actions into Endpoint-like objects for scope inference.

    Scope suggestions should reference the published action `signature_id` values, not
    the raw pre-compile endpoint signatures (GraphQL op splitting can change these).
    """
    from toolwright.models.endpoint import Endpoint

    actions = manifest.get("actions") or []
    if not isinstance(actions, list):
        return []

    allowed_hosts_raw = manifest.get("allowed_hosts") or []
    allowed_hosts = set()
    if isinstance(allowed_hosts_raw, list):
        allowed_hosts = {str(host).lower() for host in allowed_hosts_raw if host}

    endpoints: list[Endpoint] = []
    for action in actions:
        if not isinstance(action, dict):
            continue

        host = str(action.get("host") or "").lower()
        path = str(action.get("path") or "")
        method = str(action.get("method") or "GET").upper()

        tags_raw = action.get("tags") or []
        tags: list[str] = []
        if isinstance(tags_raw, list):
            tags = [str(tag) for tag in tags_raw if tag is not None]

        signature_id_raw = action.get("signature_id") or action.get("tool_id")
        signature_id = str(signature_id_raw) if signature_id_raw else None

        stable_id_raw = action.get("endpoint_id")
        stable_id = str(stable_id_raw) if stable_id_raw else None

        risk_tier = str(action.get("risk_tier") or "low").lower()

        endpoints.append(
            Endpoint(
                method=method,
                path=path,
                host=host,
                signature_id=signature_id,
                stable_id=stable_id,
                tags=tags,
                is_first_party=(host in allowed_hosts) if allowed_hosts else True,
                is_auth_related=("auth" in {t.lower() for t in tags}),
                has_pii=("pii" in {t.lower() for t in tags}),
                risk_tier=risk_tier,
            )
        )

    return endpoints


def _build_contracts_payload(
    *,
    scope_name: str,
    capture_id: str,
    generated_at: datetime,
    endpoints: list[Any],
) -> dict[str, Any]:
    contracts: list[dict[str, Any]] = []
    for endpoint in endpoints:
        signature_id = str(endpoint.signature_id or endpoint.compute_signature_id())
        scope_id = f"scope:{scope_name}"
        contracts.append(
            {
                "request_fingerprint": signature_id,
                "tool_id": str(endpoint.tool_id or signature_id),
                "scope_id": scope_id,
                "method": str(endpoint.method).upper(),
                "host": str(endpoint.host).lower(),
                "path": str(endpoint.path),
                "request_schema": endpoint.request_body_schema or {"type": "object", "properties": {}},
                "response_schema": endpoint.response_body_schema or {"type": "object", "properties": {}},
                "invariants": [],
                "confidence": float(endpoint.confidence),
                "source": "observed",
            }
        )
    return {
        "version": "1.0.0",
        "schema_version": "1.0",
        "kind": "contracts",
        "capture_id": capture_id,
        "scope": scope_name,
        "generated_at": generated_at.isoformat(),
        "contracts": contracts,
    }


def _classify_capability(endpoint: Any) -> tuple[str, float]:
    path = str(endpoint.path).lower()
    params = {str(param.name).lower() for param in getattr(endpoint, "parameters", [])}
    if "search" in path or {"q", "query", "search"} & params:
        return "search_api", 0.92
    if "facet" in path or "filter" in path:
        return "facet_filter_api", 0.88
    if any(token in path for token in ("page", "offset", "cursor")) or {"page", "offset", "cursor"} & params:
        return "pagination_api", 0.84
    if any(token in path for token in ("product", "item", "detail")):
        return "product_detail_api", 0.86
    return "generic_api", 0.65


def _build_coverage_report_payload(
    *,
    scope_name: str,
    capture_id: str,
    generated_at: datetime,
    endpoints: list[Any],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    labels: list[str] = []
    confidences: list[float] = []
    for endpoint in endpoints:
        label, confidence = _classify_capability(endpoint)
        labels.append(label)
        confidences.append(confidence)
        candidates.append(
            {
                "request_fingerprint": str(endpoint.signature_id),
                "tool_id": str(endpoint.tool_id or endpoint.signature_id),
                "label": label,
                "confidence": round(confidence, 3),
                "review_required": confidence < 0.75,
            }
        )

    expected_labels = {"search_api", "facet_filter_api", "pagination_api", "product_detail_api"}
    discovered = set(labels)
    matched = len(discovered.intersection(expected_labels))
    recall = matched / len(expected_labels) if expected_labels else 1.0
    classified = [label for label in labels if label != "generic_api"]
    precision = (
        len([label for label in classified if label in expected_labels]) / len(classified)
        if classified
        else (0.0 if labels else 1.0)
    )
    avg_confidence = (sum(confidences) / len(confidences)) if confidences else 1.0
    return {
        "version": "1.0.0",
        "schema_version": "1.0",
        "kind": "coverage_report",
        "capture_id": capture_id,
        "scope": scope_name,
        "generated_at": generated_at.isoformat(),
        "totals": {
            "endpoint_count": len(endpoints),
            "candidate_count": len(candidates),
        },
        "metrics": {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "confidence_avg": round(avg_confidence, 3),
        },
        "gate_thresholds": {
            "precision_min": 0.90,
            "recall_min": 0.85,
        },
        "candidates": candidates,
    }


def _generate_artifact_id(
    session_id: str,
    scope_name: str,
    output_format: str,
    deterministic: bool,
) -> str:
    """Generate a deterministic or volatile artifact id."""
    if deterministic:
        canonical = f"{session_id}:{scope_name}:{output_format}"
        return f"art_{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"

    import uuid

    return f"art_{datetime.now(UTC).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"


def _generate_toolpack_id(
    *,
    capture_id: str,
    artifact_id: str,
    scope_name: str,
    allowed_hosts: list[str],
    deterministic: bool,
) -> str:
    """Generate a deterministic or volatile toolpack id for compile output."""
    if deterministic:
        canonical = ":".join(
            [
                capture_id,
                artifact_id,
                scope_name,
                ",".join(sorted(set(allowed_hosts))),
            ]
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        return f"tp_{digest}"

    import uuid

    return f"tp_{datetime.now(UTC).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"


def _package_toolpack(
    *,
    compile_result: CompileResult,
    session: CaptureSession,
    scope_name: str,
    root_path: str,
    deterministic: bool,
) -> Path:
    """Package compile output into a toolpack directory with toolpack.yaml."""
    root = Path(root_path)
    allowed_hosts = sorted(set(session.allowed_hosts or []))

    toolpack_id = _generate_toolpack_id(
        capture_id=session.id,
        artifact_id=compile_result.artifact_id,
        scope_name=scope_name,
        allowed_hosts=allowed_hosts,
        deterministic=deterministic,
    )

    toolpack_dir = root / "toolpacks" / toolpack_id
    artifact_dir = toolpack_dir / "artifact"
    lockfile_dir = toolpack_dir / "lockfile"
    toolpack_dir.mkdir(parents=True, exist_ok=True)
    lockfile_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(compile_result.output_path, artifact_dir, dirs_exist_ok=True)

    copied_tools = artifact_dir / "tools.json"
    copied_toolsets = artifact_dir / "toolsets.yaml"
    copied_policy = artifact_dir / "policy.yaml"
    copied_baseline = artifact_dir / "baseline.json"
    copied_contracts = artifact_dir / "contracts.yaml"
    copied_contract_yaml = artifact_dir / "contract.yaml"
    copied_contract_json = artifact_dir / "contract.json"

    pending_lockfile = lockfile_dir / "toolwright.lock.pending.yaml"
    sync_lockfile(
        tools_path=str(copied_tools),
        policy_path=str(copied_policy),
        toolsets_path=str(copied_toolsets),
        lockfile_path=str(pending_lockfile),
        capture_id=session.id,
        scope=scope_name,
        deterministic=deterministic,
    )

    lockfiles: dict[str, str] = {
        "pending": str(pending_lockfile.relative_to(toolpack_dir)),
    }

    start_url = ""
    if session.allowed_hosts:
        start_url = f"https://{session.allowed_hosts[0]}"

    toolpack = Toolpack(
        toolpack_id=toolpack_id,
        created_at=resolve_generated_at(
            deterministic=deterministic,
            candidate=session.created_at if deterministic else None,
        ),
        capture_id=session.id,
        artifact_id=compile_result.artifact_id,
        scope=scope_name,
        allowed_hosts=allowed_hosts,
        origin=ToolpackOrigin(start_url=start_url, name=session.name),
        paths=ToolpackPaths(
            tools=str(copied_tools.relative_to(toolpack_dir)),
            toolsets=str(copied_toolsets.relative_to(toolpack_dir)),
            policy=str(copied_policy.relative_to(toolpack_dir)),
            baseline=str(copied_baseline.relative_to(toolpack_dir)),
            contracts=(
                str(copied_contracts.relative_to(toolpack_dir))
                if copied_contracts.exists()
                else None
            ),
            contract_yaml=(
                str(copied_contract_yaml.relative_to(toolpack_dir))
                if copied_contract_yaml.exists()
                else None
            ),
            contract_json=(
                str(copied_contract_json.relative_to(toolpack_dir))
                if copied_contract_json.exists()
                else None
            ),
            lockfiles=lockfiles,
        ),
        runtime=ToolpackRuntime(mode="local"),
    )

    toolpack_file = toolpack_dir / "toolpack.yaml"
    write_toolpack(toolpack, toolpack_file)
    return toolpack_file


def run_compile(
    capture_id: str,
    scope_name: str,
    scope_file: str | None,
    output_format: str,
    output_dir: str,
    verbose: bool,
    deterministic: bool = True,
    root_path: str = ".toolwright",
) -> None:
    """Run the compile command."""
    storage = Storage(base_path=root_path)
    session = storage.load_capture(capture_id)

    if not session:
        click.echo(f"Error: Capture not found: {capture_id}", err=True)
        sys.exit(1)

    try:
        result = compile_capture_session(
            session=session,
            scope_name=scope_name,
            scope_file=scope_file,
            output_format=output_format,
            output_dir=output_dir,
            deterministic=deterministic,
            verbose=verbose,
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not result.endpoint_count:
        click.echo("Warning: No endpoints match the scope", err=True)

    click.echo(f"\nCompile complete: {result.artifact_id}")
    click.echo(f"  Scope: {result.scope.name}")
    click.echo(f"  Endpoints: {result.endpoint_count}")
    click.echo(f"  Output: {result.output_path}")
    click.echo("\nArtifacts:")
    for name, path in result.artifacts_created:
        click.echo(f"  - {name}: {path.name}")

    # Package into a toolpack directory if we have the required artifacts
    if result.tools_path and result.toolsets_path and result.policy_path and result.baseline_path:
        toolpack_file = _package_toolpack(
            compile_result=result,
            session=session,
            scope_name=scope_name,
            root_path=root_path,
            deterministic=deterministic,
        )
        click.echo(f"\nToolpack: {toolpack_file}")
        click.echo("  Ready for: toolwright gate sync / toolwright gate allow --all / toolwright serve --toolpack")
