"""Catalog-driven proposal compiler.

Transforms normalized endpoint observations into:
1) Endpoint catalog IR
2) Parameterized tool proposals
3) Follow-up capture questions
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any
from urllib.parse import parse_qs, urlparse

from toolwright.core.normalize.path_normalizer import PathNormalizer
from toolwright.models.capture import CaptureSession, HttpExchange
from toolwright.models.endpoint import Endpoint, ParameterLocation
from toolwright.models.proposal import (
    CatalogParameter,
    DerivedParamResolver,
    EndpointCatalog,
    EndpointFamily,
    GraphQLOperationObservation,
    ProposalKind,
    ProposalParamSource,
    ProposalParamVariability,
    ProposalQuestion,
    ProposalQuestionSet,
    ToolProposalParameter,
    ToolProposalSet,
    ToolProposalSpec,
)
from toolwright.utils.naming import generate_tool_name


class ProposalCompiler:
    """Compile endpoint observations into catalog and proposed tools."""

    def __init__(self) -> None:
        self._path_normalizer = PathNormalizer()

    def build_endpoint_catalog(
        self,
        *,
        capture_id: str,
        scope_name: str,
        endpoints: list[Endpoint],
        session: CaptureSession,
    ) -> EndpointCatalog:
        """Build endpoint-catalog IR from normalized endpoints."""
        by_exchange_id = {exchange.id: exchange for exchange in session.exchanges}
        families: list[EndpointFamily] = []

        for endpoint in sorted(
            endpoints,
            key=lambda ep: (ep.host, ep.method.upper(), ep.path, ep.signature_id),
        ):
            samples = [
                by_exchange_id[exchange_id]
                for exchange_id in endpoint.exchange_ids
                if exchange_id in by_exchange_id
            ]
            families.append(self._build_family(endpoint, samples))

        return EndpointCatalog(
            capture_id=capture_id,
            scope=scope_name,
            families=families,
        )

    def build_tool_proposals(self, catalog: EndpointCatalog) -> ToolProposalSet:
        """Compile proposed tools from endpoint catalog families."""
        proposals: list[ToolProposalSpec] = []
        for family in sorted(
            catalog.families,
            key=lambda item: (item.host, item.method.upper(), item.path_template, item.family_id),
        ):
            if family.kind == ProposalKind.GRAPHQL and family.graphql_operations:
                proposals.extend(self._graphql_proposals_for_family(family))
                continue
            proposals.append(self._rest_proposal_for_family(family))

        return ToolProposalSet(
            capture_id=catalog.capture_id,
            scope=catalog.scope,
            proposals=proposals,
        )

    def build_questions(
        self,
        catalog: EndpointCatalog,
        proposals: ToolProposalSet,
    ) -> ProposalQuestionSet:
        """Generate follow-up capture questions for low-confidence abstractions."""
        del proposals  # Questions currently depend on family-level diagnostics.

        questions: list[ProposalQuestion] = []
        seen: set[tuple[str, str]] = set()

        for family in catalog.families:
            capture_hint = family.sample_paths[0] if family.sample_paths else None
            for note in family.needs_more_examples:
                key = (family.family_id, note)
                if key in seen:
                    continue
                seen.add(key)
                questions.append(
                    ProposalQuestion(
                        family_id=family.family_id,
                        priority=1 if family.risk_tier in {"high", "critical"} else 2,
                        prompt=note,
                        capture_hint=capture_hint,
                    )
                )
            for param in family.parameters:
                if param.source != ProposalParamSource.DERIVED or not param.resolver:
                    continue
                resolver_note = (
                    f"Capture validation: verify resolver `{param.resolver.name}` for `{param.name}` on "
                    f"{family.method} {family.path_template}."
                )
                key = (family.family_id, resolver_note)
                if key in seen:
                    continue
                seen.add(key)
                questions.append(
                    ProposalQuestion(
                        family_id=family.family_id,
                        priority=1 if family.risk_tier in {"high", "critical"} else 2,
                        prompt=resolver_note,
                        capture_hint=capture_hint,
                    )
                )

        return ProposalQuestionSet(
            capture_id=catalog.capture_id,
            scope=catalog.scope,
            questions=questions,
        )

    def _build_family(
        self,
        endpoint: Endpoint,
        samples: list[HttpExchange],
    ) -> EndpointFamily:
        method = endpoint.method.upper()
        path_template = endpoint.path
        kind = (
            ProposalKind.GRAPHQL
            if method == "POST" and "/graphql" in path_template.lower()
            else ProposalKind.REST
        )

        family_id = self._family_id(endpoint)
        sample_paths = sorted({sample.path for sample in samples if sample.path})[:5]
        parameters = self._build_parameters(endpoint, samples, kind)
        graphql_operations = (
            self._extract_graphql_operations(endpoint.request_examples)
            if kind == ProposalKind.GRAPHQL
            else []
        )
        confidence = self._family_confidence(endpoint, parameters, graphql_operations)
        needs_more_examples = self._needs_more_examples(
            endpoint=endpoint,
            parameters=parameters,
            kind=kind,
            graphql_operations=graphql_operations,
        )

        response_key_hints = []
        response_schema = endpoint.response_body_schema or {}
        if isinstance(response_schema, dict):
            response_props = response_schema.get("properties")
            if isinstance(response_props, dict):
                response_key_hints = sorted(response_props.keys())[:8]

        return EndpointFamily(
            family_id=family_id,
            host=endpoint.host,
            method=method,
            path_template=path_template,
            kind=kind,
            observation_count=endpoint.observation_count,
            risk_tier=endpoint.risk_tier,
            confidence=confidence,
            tags=sorted(set(endpoint.tags)),
            response_key_hints=response_key_hints,
            sample_paths=sample_paths,
            parameters=parameters,
            graphql_operations=graphql_operations,
            needs_more_examples=needs_more_examples,
        )

    def _build_parameters(
        self,
        endpoint: Endpoint,
        samples: list[HttpExchange],
        kind: ProposalKind,
    ) -> list[CatalogParameter]:
        parameters: list[CatalogParameter] = []

        # Path + query parameters from structured endpoint metadata.
        for param in sorted(
            endpoint.parameters,
            key=lambda item: (item.location.value, item.name),
        ):
            observed_values = self._observed_values_for_param(endpoint, param.name, param.location, samples)
            variability = self._classify_variability(observed_values)
            resolver = self._resolve_derived_param(endpoint, param.name)
            source = (
                ProposalParamSource.DERIVED
                if resolver
                else self._source_from_parameter_location(param.location)
            )
            default = observed_values[0] if len(observed_values) == 1 else None

            parameters.append(
                CatalogParameter(
                    name=param.name,
                    source=source,
                    required=param.required if source != ProposalParamSource.DERIVED else False,
                    variability=variability,
                    observed_values=observed_values,
                    default=default,
                    resolver=resolver,
                )
            )

        # Body fields inferred from schema + examples.
        body_schema = endpoint.request_body_schema or {}
        body_props = body_schema.get("properties", {}) if isinstance(body_schema, dict) else {}
        body_required_raw = body_schema.get("required", []) if isinstance(body_schema, dict) else []
        body_required = {str(item) for item in body_required_raw if isinstance(item, str)}

        for body_name in sorted(body_props.keys()):
            if kind == ProposalKind.GRAPHQL and body_name == "operationName":
                # GraphQL operationName is represented as fixed_body in per-op proposals.
                continue

            observed_values = self._observed_body_values(endpoint.request_examples, body_name)
            variability = self._classify_variability(observed_values)
            default = observed_values[0] if len(observed_values) == 1 else None
            parameters.append(
                CatalogParameter(
                    name=body_name,
                    source=ProposalParamSource.BODY,
                    required=body_name in body_required,
                    variability=variability,
                    observed_values=observed_values,
                    default=default,
                )
            )

        # GraphQL variables should always be explicit in proposals.
        if kind == ProposalKind.GRAPHQL and not any(p.name == "variables" for p in parameters):
            parameters.append(
                CatalogParameter(
                    name="variables",
                    source=ProposalParamSource.BODY,
                    required=False,
                    variability=ProposalParamVariability.UNKNOWN,
                )
            )

        return parameters

    def _observed_values_for_param(
        self,
        endpoint: Endpoint,
        param_name: str,
        location: ParameterLocation,
        samples: list[HttpExchange],
    ) -> list[str]:
        values: set[str] = set()
        if location == ParameterLocation.PATH:
            for sample in samples:
                extracted = self._path_normalizer.extract_parameters(endpoint.path, sample.path)
                if extracted and param_name in extracted and extracted[param_name]:
                    values.add(str(extracted[param_name]))
        elif location == ParameterLocation.QUERY:
            for sample in samples:
                parsed = urlparse(sample.url)
                query = parse_qs(parsed.query)
                for query_value in query.get(param_name, []):
                    if query_value:
                        values.add(str(query_value))
        return sorted(values)[:8]

    @staticmethod
    def _source_from_parameter_location(location: ParameterLocation) -> ProposalParamSource:
        if location == ParameterLocation.PATH:
            return ProposalParamSource.PATH
        if location == ParameterLocation.QUERY:
            return ProposalParamSource.QUERY
        return ProposalParamSource.BODY

    @staticmethod
    def _observed_body_values(request_examples: list[dict[str, Any]], key: str) -> list[str]:
        values: set[str] = set()
        for sample in request_examples:
            if not isinstance(sample, dict):
                continue
            if key not in sample:
                continue
            raw = sample.get(key)
            if raw is None:
                continue
            if isinstance(raw, dict | list):
                values.add(f"<{type(raw).__name__}>")
            else:
                values.add(str(raw))
        return sorted(values)[:8]

    @staticmethod
    def _classify_variability(observed_values: list[str]) -> ProposalParamVariability:
        if len(observed_values) > 1:
            return ProposalParamVariability.VARIABLE
        if len(observed_values) == 1:
            return ProposalParamVariability.STABLE
        return ProposalParamVariability.UNKNOWN

    @staticmethod
    def _resolve_derived_param(endpoint: Endpoint, param_name: str) -> DerivedParamResolver | None:
        name = param_name.lower()
        path = endpoint.path.lower()

        if "/_next/data/" in path and name in {"token", "build_id", "buildid"}:
            return DerivedParamResolver(
                name="nextjs_build_id",
                description="Resolve build ID from __NEXT_DATA__ before request execution.",
            )
        if name in {"csrf", "csrf_token", "xsrf", "xsrf_token"}:
            return DerivedParamResolver(
                name="csrf_token",
                description="Resolve CSRF token from authenticated browser/session context.",
            )
        return None

    def _extract_graphql_operations(
        self,
        request_examples: list[dict[str, Any]],
    ) -> list[GraphQLOperationObservation]:
        counts: Counter[str] = Counter()
        types: dict[str, str] = {}

        for sample in request_examples:
            if not isinstance(sample, dict):
                continue
            raw_name = sample.get("operationName")
            if not isinstance(raw_name, str):
                continue
            operation_name = raw_name.strip()
            if not operation_name:
                continue

            counts[operation_name] += 1
            operation_type = self._graphql_operation_type_from_sample(sample)
            if operation_type and operation_type != "unknown":
                types[operation_name] = operation_type

        operations = []
        for operation_name in sorted(counts.keys()):
            operations.append(
                GraphQLOperationObservation(
                    operation_name=operation_name,
                    operation_type=types.get(operation_name, self._graphql_operation_type_from_name(operation_name)),
                    count=counts[operation_name],
                )
            )
        return operations

    @staticmethod
    def _graphql_operation_type_from_sample(sample: dict[str, Any]) -> str:
        query_raw = sample.get("query")
        if not isinstance(query_raw, str):
            return "unknown"
        query = query_raw.strip()
        if not query:
            return "unknown"
        if query.startswith("{"):
            return "query"

        candidate_lines = []
        for line in query.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            candidate_lines.append(stripped)
        candidate = " ".join(part for part in candidate_lines if part).lower()
        for operation_type in ("mutation", "subscription", "query"):
            if candidate.startswith(operation_type):
                return operation_type
        return "unknown"

    @staticmethod
    def _graphql_operation_type_from_name(operation_name: str) -> str:
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", operation_name)
        normalized = normalized.replace("-", "_").replace(" ", "_").lower()
        tokens = [token for token in normalized.split("_") if token]
        write_tokens = {"create", "update", "delete", "set", "submit", "apply", "place", "mutate", "bid"}
        read_tokens = {
            "get",
            "list",
            "search",
            "query",
            "find",
            "fetch",
            "view",
            "viewed",
            "recent",
            "recently",
            "history",
            "lookup",
        }
        if any(token in write_tokens for token in tokens):
            return "mutation"
        if any(token in read_tokens for token in tokens):
            return "query"
        return "unknown"

    def _family_confidence(
        self,
        endpoint: Endpoint,
        parameters: list[CatalogParameter],
        graphql_operations: list[GraphQLOperationObservation],
    ) -> float:
        score = 0.45
        score += min(0.25, endpoint.observation_count * 0.07)

        if any(param.variability == ProposalParamVariability.VARIABLE for param in parameters):
            score += 0.15
        if any(param.source == ProposalParamSource.DERIVED for param in parameters):
            score += 0.05
        if graphql_operations:
            score += 0.05
        if any(param.variability == ProposalParamVariability.UNKNOWN for param in parameters):
            score -= 0.1

        return round(max(0.1, min(0.95, score)), 3)

    def _needs_more_examples(
        self,
        *,
        endpoint: Endpoint,
        parameters: list[CatalogParameter],
        kind: ProposalKind,
        graphql_operations: list[GraphQLOperationObservation],
    ) -> list[str]:
        reasons: list[str] = []
        if endpoint.observation_count < 2:
            reasons.append(
                f"Capture more examples for {endpoint.method.upper()} {endpoint.path} to increase abstraction confidence."
            )

        for param in parameters:
            if param.source == ProposalParamSource.DERIVED:
                continue
            if param.name.lower() in {"slug", "id", "product_id", "item_id"} and param.variability != ProposalParamVariability.VARIABLE:
                reasons.append(
                    f"Capture another flow with a different `{param.name}` value for {endpoint.path}."
                )
                break

        if kind == ProposalKind.GRAPHQL and len(graphql_operations) <= 1:
            reasons.append(
                f"Exercise additional GraphQL operations on {endpoint.path} to broaden operation coverage."
            )

        deduped: list[str] = []
        seen = set()
        for reason in reasons:
            if reason in seen:
                continue
            seen.add(reason)
            deduped.append(reason)
        return deduped

    def _graphql_proposals_for_family(self, family: EndpointFamily) -> list[ToolProposalSpec]:
        proposals: list[ToolProposalSpec] = []
        for operation in sorted(family.graphql_operations, key=lambda item: item.operation_name):
            prefix = self._graphql_name_prefix(operation.operation_type)
            operation_slug = self._to_snake_case(operation.operation_name)
            proposal_name = f"{prefix}_{operation_slug}" if operation_slug else prefix
            risk_tier = self._graphql_risk_tier(family.risk_tier, operation.operation_type)
            confidence = round(min(0.98, family.confidence + (0.05 if operation.count > 1 else 0.0)), 3)
            requires_review = confidence < 0.75 or risk_tier in {"high", "critical"}

            parameters = [
                ToolProposalParameter(
                    name=param.name,
                    source=param.source,
                    required=param.required,
                    default=param.default,
                    resolver=param.resolver,
                )
                for param in family.parameters
            ]
            if not any(param.name == "variables" for param in parameters):
                parameters.append(
                    ToolProposalParameter(
                        name="variables",
                        source=ProposalParamSource.BODY,
                        required=False,
                        description="GraphQL variables payload",
                    )
                )

            canonical = f"{family.host}:{family.method}:{family.path_template}:{proposal_name}:{operation.operation_name}"
            proposal_id = f"tp_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:10]}"
            rationale = [
                f"Observed GraphQL operation `{operation.operation_name}` ({operation.operation_type}).",
                f"Operation observed {operation.count} time(s).",
            ]
            if family.needs_more_examples:
                rationale.append("Additional captures recommended for broader operation coverage.")

            proposals.append(
                ToolProposalSpec(
                    proposal_id=proposal_id,
                    name=proposal_name,
                    kind=ProposalKind.GRAPHQL,
                    host=family.host,
                    method=family.method,
                    path_template=family.path_template,
                    risk_tier=risk_tier,
                    confidence=confidence,
                    requires_review=requires_review,
                    parameters=parameters,
                    fixed_body={"operationName": operation.operation_name},
                    operation_name=operation.operation_name,
                    operation_type=operation.operation_type,
                    rationale=rationale,
                )
            )
        return proposals

    def _rest_proposal_for_family(self, family: EndpointFamily) -> ToolProposalSpec:
        canonical = f"{family.host}:{family.method}:{family.path_template}"
        proposal_id = f"tp_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:10]}"
        proposal_name = generate_tool_name(family.method, family.path_template)
        requires_review = family.confidence < 0.75 or family.risk_tier in {"high", "critical"}

        rationale = [
            f"Compiled from endpoint family with {family.observation_count} observation(s).",
        ]
        if any(param.source == ProposalParamSource.DERIVED for param in family.parameters):
            rationale.append("Includes derived runtime parameters for ephemeral values.")
        if family.needs_more_examples:
            rationale.append("Additional captures recommended before autopublish.")

        return ToolProposalSpec(
            proposal_id=proposal_id,
            name=proposal_name,
            kind=ProposalKind.REST,
            host=family.host,
            method=family.method,
            path_template=family.path_template,
            risk_tier=family.risk_tier,
            confidence=family.confidence,
            requires_review=requires_review,
            parameters=[
                ToolProposalParameter(
                    name=param.name,
                    source=param.source,
                    required=param.required,
                    default=param.default,
                    resolver=param.resolver,
                )
                for param in family.parameters
            ],
            rationale=rationale,
        )

    @staticmethod
    def _family_id(endpoint: Endpoint) -> str:
        canonical = f"{endpoint.host}:{endpoint.method.upper()}:{endpoint.path}"
        return f"fam_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}"

    @staticmethod
    def _graphql_name_prefix(operation_type: str) -> str:
        op_type = operation_type.lower()
        if op_type == "mutation":
            return "mutate"
        if op_type == "subscription":
            return "subscribe"
        return "query"

    @staticmethod
    def _graphql_risk_tier(base_risk: str, operation_type: str) -> str:
        order = ["safe", "low", "medium", "high", "critical"]
        by_type = {"query": "low", "mutation": "high", "subscription": "medium"}
        candidate = by_type.get(operation_type.lower(), "medium")
        base = base_risk if base_risk in order else "medium"
        return max((base, candidate), key=lambda item: order.index(item))

    @staticmethod
    def _to_snake_case(value: str) -> str:
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
        value = value.replace("-", "_")
        value = value.replace(" ", "_")
        value = re.sub(r"[^A-Za-z0-9_]+", "_", value)
        value = re.sub(r"_+", "_", value)
        return value.strip("_").lower()
