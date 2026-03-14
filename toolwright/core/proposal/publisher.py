"""Proposal publisher.

Converts `tools.proposed.yaml` artifacts into runtime-ready bundle artifacts:
- tools.json
- toolsets.yaml
- policy.yaml
- publish_report.json
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from toolwright.core.compile.toolsets import ToolsetGenerator
from toolwright.core.risk_keywords import RISK_ORDER
from toolwright.models.proposal import (
    ProposalParamSource,
    ToolProposalParameter,
    ToolProposalSet,
    ToolProposalSpec,
)
from toolwright.utils.naming import resolve_collision
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION, resolve_generated_at

CONFIRMATION_MAP = {
    "safe": "never",
    "low": "never",
    "medium": "on_risk",
    "high": "always",
    "critical": "always",
}
RATE_LIMIT_MAP = {
    "safe": 120,
    "low": 60,
    "medium": 30,
    "high": 10,
    "critical": 5,
}
STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class ExcludedProposal:
    """Proposed tool excluded from publish output."""

    proposal_id: str
    name: str
    confidence: float
    risk_tier: str
    requires_review: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PublishResult:
    """Result metadata for a publish run."""

    capture_id: str
    scope: str
    bundle_id: str
    bundle_path: Path
    tools_path: Path
    toolsets_path: Path
    policy_path: Path
    report_path: Path
    selected_count: int
    excluded: tuple[ExcludedProposal, ...]


class ProposalPublisher:
    """Publish tool proposals into runtime-ready artifacts."""

    def publish(
        self,
        *,
        proposals_path: Path,
        output_root: Path,
        min_confidence: float,
        max_risk: str,
        include_review_required: bool,
        proposal_ids: tuple[str, ...],
        deterministic: bool,
    ) -> PublishResult:
        """Load proposal set, apply selection gates, and emit artifacts."""
        if max_risk not in RISK_ORDER:
            raise ValueError(f"Unknown max risk tier: {max_risk}")

        payload = yaml.safe_load(proposals_path.read_text(encoding="utf-8")) or {}
        proposal_set = ToolProposalSet(**payload)

        selected, excluded = self._select_proposals(
            proposal_set=proposal_set,
            min_confidence=min_confidence,
            max_risk=max_risk,
            include_review_required=include_review_required,
            proposal_ids=proposal_ids,
        )
        if not selected:
            raise ValueError("No proposals passed publish filters.")

        generated_at = resolve_generated_at(
            deterministic=deterministic,
            candidate=self._parse_generated_at(proposal_set.generated_at) if deterministic else None,
        )
        bundle_id = self._bundle_id(
            capture_id=proposal_set.capture_id,
            scope=proposal_set.scope,
            selected=selected,
            min_confidence=min_confidence,
            max_risk=max_risk,
            include_review_required=include_review_required,
            deterministic=deterministic,
        )
        bundle_path = output_root / bundle_id
        bundle_path.mkdir(parents=True, exist_ok=True)

        manifest = self._build_manifest(
            proposal_set=proposal_set,
            selected=selected,
            generated_at=generated_at,
        )
        toolsets = ToolsetGenerator().generate(manifest=manifest, generated_at=generated_at)
        policy = self._build_policy(
            actions=manifest["actions"],
            scope=proposal_set.scope,
            generated_at=generated_at,
        )
        report = self._build_report(
            proposal_set=proposal_set,
            proposals_path=proposals_path,
            selected=selected,
            excluded=excluded,
            min_confidence=min_confidence,
            max_risk=max_risk,
            include_review_required=include_review_required,
            deterministic=deterministic,
            generated_at=generated_at,
        )

        tools_path = bundle_path / "tools.json"
        tools_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        toolsets_path = bundle_path / "toolsets.yaml"
        toolsets_path.write_text(yaml.safe_dump(toolsets, sort_keys=False), encoding="utf-8")

        policy_path = bundle_path / "policy.yaml"
        policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

        report_path = bundle_path / "publish_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        return PublishResult(
            capture_id=proposal_set.capture_id,
            scope=proposal_set.scope,
            bundle_id=bundle_id,
            bundle_path=bundle_path,
            tools_path=tools_path,
            toolsets_path=toolsets_path,
            policy_path=policy_path,
            report_path=report_path,
            selected_count=len(selected),
            excluded=tuple(excluded),
        )

    def _select_proposals(
        self,
        *,
        proposal_set: ToolProposalSet,
        min_confidence: float,
        max_risk: str,
        include_review_required: bool,
        proposal_ids: tuple[str, ...],
    ) -> tuple[list[ToolProposalSpec], list[ExcludedProposal]]:
        allowed_ids = set(proposal_ids)
        known_ids = {proposal.proposal_id for proposal in proposal_set.proposals}
        unknown_ids = sorted(allowed_ids - known_ids)
        if unknown_ids:
            raise ValueError(f"Unknown proposal_id values: {', '.join(unknown_ids)}")

        selected: list[ToolProposalSpec] = []
        excluded: list[ExcludedProposal] = []
        max_risk_rank = RISK_ORDER[max_risk]

        for proposal in sorted(proposal_set.proposals, key=lambda item: (item.name, item.proposal_id)):
            reasons: list[str] = []
            if allowed_ids and proposal.proposal_id not in allowed_ids:
                reasons.append("not-selected")

            if proposal.confidence < min_confidence:
                reasons.append(f"confidence<{min_confidence}")

            risk_rank = RISK_ORDER.get(proposal.risk_tier, RISK_ORDER["medium"])
            if risk_rank > max_risk_rank:
                reasons.append(f"risk>{max_risk}")

            if proposal.requires_review and not include_review_required:
                reasons.append("requires-review")

            if reasons:
                excluded.append(
                    ExcludedProposal(
                        proposal_id=proposal.proposal_id,
                        name=proposal.name,
                        confidence=proposal.confidence,
                        risk_tier=proposal.risk_tier,
                        requires_review=proposal.requires_review,
                        reasons=tuple(reasons),
                    )
                )
                continue
            selected.append(proposal)

        return selected, excluded

    def _build_manifest(
        self,
        *,
        proposal_set: ToolProposalSet,
        selected: list[ToolProposalSpec],
        generated_at: datetime,
    ) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        used_names: set[str] = set()

        for proposal in sorted(
            selected,
            key=lambda item: (
                item.host,
                item.method.upper(),
                item.path_template,
                item.name,
                item.proposal_id,
            ),
        ):
            action_name = resolve_collision(proposal.name, used_names, proposal.host)
            used_names.add(action_name)

            signature_id = self._signature_id(proposal)
            endpoint_id = self._endpoint_id(proposal)
            operation_type = self._resolve_operation_type(proposal)
            fixed_body = self._effective_fixed_body(proposal)
            action = {
                "id": action_name,
                "tool_id": signature_id,
                "name": action_name,
                "description": self._description(proposal, operation_type),
                "endpoint_id": endpoint_id,
                "signature_id": signature_id,
                "method": proposal.method.upper(),
                "path": proposal.path_template,
                "host": proposal.host,
                "input_schema": self._build_input_schema(proposal.parameters, fixed_body),
                "risk_tier": proposal.risk_tier,
                "confirmation_required": CONFIRMATION_MAP.get(proposal.risk_tier, "on_risk"),
                "rate_limit_per_minute": RATE_LIMIT_MAP.get(proposal.risk_tier, 30),
                "tags": self._tags_for_proposal(proposal, operation_type),
                "proposal_id": proposal.proposal_id,
                "proposal_confidence": proposal.confidence,
                "proposal_requires_review": proposal.requires_review,
                "proposal_rationale": proposal.rationale,
            }
            if fixed_body:
                action["fixed_body"] = fixed_body
            if proposal.operation_name:
                action["graphql_operation_name"] = proposal.operation_name
            if operation_type:
                action["graphql_operation_type"] = operation_type
            actions.append(action)

        return {
            "version": "1.0.0",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "name": "Published Proposal Tools",
            "generated_at": generated_at.isoformat(),
            "capture_id": proposal_set.capture_id,
            "scope": proposal_set.scope,
            "allowed_hosts": sorted({action["host"] for action in actions}),
            "actions": actions,
        }

    def _build_policy(
        self,
        *,
        actions: list[dict[str, Any]],
        scope: str,
        generated_at: datetime,
    ) -> dict[str, Any]:
        hosts = sorted({action["host"] for action in actions})
        state_changing_actions = [
            action
            for action in actions
            if self._is_state_changing_action(action)
        ]

        rules: list[dict[str, Any]] = [
            {
                "id": "allow_first_party_get",
                "name": "Allow first-party read operations",
                "type": "allow",
                "priority": 100,
                "match": {
                    "hosts": hosts,
                    "methods": ["GET", "HEAD", "OPTIONS"],
                },
            },
        ]

        if state_changing_actions:
            rules.append(
                {
                    "id": "confirm_state_changes",
                    "name": "Require confirmation for mutations",
                    "type": "confirm",
                    "priority": 90,
                    "match": {"methods": ["POST", "PUT", "PATCH", "DELETE"]},
                    "settings": {"message": "This action will modify data. Proceed?"},
                }
            )

        rules.append(
            {
                "id": "budget_writes",
                "name": "Rate limit write operations",
                "type": "budget",
                "priority": 80,
                "match": {"methods": ["POST", "PUT", "PATCH"]},
                "settings": {"per_minute": 10, "per_hour": 100},
            }
        )
        rules.append(
            {
                "id": "budget_deletes",
                "name": "Strict rate limit for deletes",
                "type": "budget",
                "priority": 70,
                "match": {"methods": ["DELETE"]},
                "settings": {"per_minute": 5, "per_hour": 20},
            }
        )

        overrides = self._state_changing_overrides(actions=actions)

        return {
            "version": "1.0.0",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "name": "Published Proposal Policy",
            "description": f"Auto-generated policy for {len(actions)} published proposal action(s)",
            "generated_at": generated_at.isoformat(),
            "default_action": "deny",
            "global_rate_limit": 100,
            "audit_all": True,
            "scope": scope,
            "redact_headers": [
                "authorization",
                "cookie",
                "set-cookie",
                "x-api-key",
                "x-auth-token",
                "proxy-authorization",
            ],
            "redact_patterns": [
                r"bearer\s+[a-zA-Z0-9\-_.]+",
                r"api[_-]?key[\"']?\s*[=:]\s*[\"']?[a-zA-Z0-9]+",
            ],
            "redact_pattern_justifications": {
                r"bearer\s+[a-zA-Z0-9\-_.]+": "Redact bearer tokens from logs and evidence.",
                r"api[_-]?key[\"']?\s*[=:]\s*[\"']?[a-zA-Z0-9]+": (
                    "Redact API keys from query strings, payloads, and headers."
                ),
            },
            "state_changing_overrides": overrides,
            "rules": rules,
        }

    def _state_changing_overrides(
        self,
        *,
        actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        overrides: list[dict[str, Any]] = []

        for action in actions:
            operation_type = str(action.get("graphql_operation_type", "")).lower()
            if operation_type != "query":
                continue
            method = str(action.get("method", "")).upper()
            if method not in STATE_CHANGING_METHODS:
                continue
            overrides.append(
                {
                    "tool_id": action["tool_id"],
                    "method": method,
                    "path": action["path"],
                    "host": action["host"],
                    "state_changing": False,
                    "justification": "GraphQL query operation observed as read-only.",
                }
            )

        return sorted(overrides, key=lambda item: (item["host"], item["path"], item["tool_id"]))

    def _build_report(
        self,
        *,
        proposal_set: ToolProposalSet,
        proposals_path: Path,
        selected: list[ToolProposalSpec],
        excluded: list[ExcludedProposal],
        min_confidence: float,
        max_risk: str,
        include_review_required: bool,
        deterministic: bool,
        generated_at: datetime,
    ) -> dict[str, Any]:
        selected_sorted = sorted(selected, key=lambda item: (item.name, item.proposal_id))
        excluded_sorted = sorted(excluded, key=lambda item: (item.name, item.proposal_id))
        return {
            "version": "1.0.0",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "generated_at": generated_at.isoformat(),
            "deterministic": deterministic,
            "source": {
                "capture_id": proposal_set.capture_id,
                "scope": proposal_set.scope,
                "proposals_path": str(proposals_path),
            },
            "filters": {
                "min_confidence": min_confidence,
                "max_risk": max_risk,
                "include_review_required": include_review_required,
            },
            "selected_count": len(selected_sorted),
            "excluded_count": len(excluded_sorted),
            "selected": [
                {
                    "proposal_id": proposal.proposal_id,
                    "name": proposal.name,
                    "confidence": proposal.confidence,
                    "risk_tier": proposal.risk_tier,
                    "requires_review": proposal.requires_review,
                }
                for proposal in selected_sorted
            ],
            "excluded": [
                {
                    "proposal_id": proposal.proposal_id,
                    "name": proposal.name,
                    "confidence": proposal.confidence,
                    "risk_tier": proposal.risk_tier,
                    "requires_review": proposal.requires_review,
                    "reasons": list(proposal.reasons),
                }
                for proposal in excluded_sorted
            ],
        }

    def _build_input_schema(
        self,
        parameters: list[ToolProposalParameter],
        fixed_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        fixed_keys = set((fixed_body or {}).keys())

        for parameter in sorted(parameters, key=lambda item: (item.source.value, item.name)):
            properties[parameter.name] = self._parameter_schema(parameter)
            if (
                parameter.required
                and parameter.source != ProposalParamSource.DERIVED
                and parameter.name not in fixed_keys
            ):
                required.append(parameter.name)

        for fixed_key, fixed_value in sorted((fixed_body or {}).items()):
            property_schema = properties.get(fixed_key, {"type": self._json_type_name(fixed_value)})
            property_schema.setdefault(
                "description",
                "Operation-bound fixed value populated automatically at runtime.",
            )
            property_schema["default"] = fixed_value
            property_schema["enum"] = [fixed_value]
            properties[fixed_key] = property_schema

        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = sorted(set(required))
        return schema

    def _parameter_schema(self, parameter: ToolProposalParameter) -> dict[str, Any]:
        if parameter.name == "variables":
            schema: dict[str, Any] = {
                "type": "object",
                "additionalProperties": True,
            }
        else:
            schema = {"type": self._json_type_name(parameter.default)}

        if parameter.description:
            schema["description"] = parameter.description
        else:
            schema["description"] = f"{parameter.source.value} parameter `{parameter.name}`."

        if parameter.default is not None:
            schema["default"] = parameter.default

        schema["x-toolwright-source"] = parameter.source.value

        if parameter.resolver:
            schema["x-toolwright-resolver"] = {
                "name": parameter.resolver.name,
                "source": parameter.resolver.source,
                "description": parameter.resolver.description,
            }
            schema["description"] = (
                f"{schema['description']} Auto-resolved via `{parameter.resolver.name}`."
            )

        return schema

    def _description(self, proposal: ToolProposalSpec, operation_type: str) -> str:
        if proposal.rationale:
            return proposal.rationale[0]
        if proposal.kind.value == "graphql" and proposal.operation_name:
            return f"Run GraphQL {operation_type or 'operation'} {proposal.operation_name}."
        return f"Execute {proposal.method.upper()} {proposal.path_template} on {proposal.host}."

    def _tags_for_proposal(self, proposal: ToolProposalSpec, operation_type: str) -> list[str]:
        tags = {"proposal_compiled", f"risk:{proposal.risk_tier}"}
        if proposal.kind.value == "graphql":
            tags.add("graphql")
            if operation_type:
                tags.add(f"graphql:{operation_type}")
        else:
            tags.add("rest")
        return sorted(tags)

    def _is_state_changing_action(self, action: dict[str, Any]) -> bool:
        method = str(action.get("method", "")).upper()
        if method not in STATE_CHANGING_METHODS:
            return False
        operation_type = str(action.get("graphql_operation_type", "")).lower()
        return operation_type != "query"

    def _resolve_operation_type(self, proposal: ToolProposalSpec) -> str:
        operation_type = (proposal.operation_type or "").lower()
        if operation_type in {"query", "mutation", "subscription"}:
            return operation_type

        name = proposal.name.lower()
        if name.startswith("query_"):
            return "query"
        if name.startswith("mutate_"):
            return "mutation"
        if name.startswith("subscribe_"):
            return "subscription"

        operation_name = proposal.operation_name or ""
        if not operation_name:
            return "unknown"

        normalized = self._to_snake_case(operation_name)
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

    def _effective_fixed_body(self, proposal: ToolProposalSpec) -> dict[str, Any] | None:
        fixed_body: dict[str, Any] = dict(proposal.fixed_body or {})
        if proposal.kind.value != "graphql":
            return fixed_body or None

        for parameter in proposal.parameters:
            if parameter.source != ProposalParamSource.BODY:
                continue
            if parameter.name not in {"query", "extensions"}:
                continue
            default = parameter.default
            if default is None:
                continue
            if isinstance(default, str) and default in {"<dict>", "<list>"}:
                continue
            fixed_body.setdefault(parameter.name, default)

        return fixed_body or None

    @staticmethod
    def _signature_id(proposal: ToolProposalSpec) -> str:
        canonical = (
            f"{proposal.method.upper()}:{proposal.host}:{proposal.path_template}:"
            f"{proposal.operation_name or ''}"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _endpoint_id(proposal: ToolProposalSpec) -> str:
        canonical = f"{proposal.method.upper()}:{proposal.host}:{proposal.path_template}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _bundle_id(
        *,
        capture_id: str,
        scope: str,
        selected: list[ToolProposalSpec],
        min_confidence: float,
        max_risk: str,
        include_review_required: bool,
        deterministic: bool,
    ) -> str:
        if deterministic:
            key = ",".join(sorted(proposal.proposal_id for proposal in selected))
            canonical = (
                f"{capture_id}:{scope}:{key}:{min_confidence:.3f}:{max_risk}:"
                f"{include_review_required}"
            )
            return f"pub_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}"
        return f"pub_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

    @staticmethod
    def _parse_generated_at(raw: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _json_type_name(value: Any) -> str:
        if value is None:
            return "string"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int) and not isinstance(value, bool):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        return "string"

    @staticmethod
    def _to_snake_case(value: str) -> str:
        value = value.replace("-", "_")
        value = value.replace(" ", "_")
        out: list[str] = []
        prev_lower_or_digit = False
        for char in value:
            if char.isupper() and prev_lower_or_digit:
                out.append("_")
            out.append(char)
            prev_lower_or_digit = char.islower() or char.isdigit()
        snake = "".join(out).lower()
        while "__" in snake:
            snake = snake.replace("__", "_")
        return snake.strip("_")
