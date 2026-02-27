"""Agent draft proposal models — safe capability growth mechanism."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProposalStatus(StrEnum):
    """Status of a draft proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MissingCapability(BaseModel):
    """Emitted when runtime denies a tool call — describes what the agent needs."""

    reason_code: str
    attempted_action: str
    suggested_tool: str | None = None
    suggested_host: str | None = None
    risk_guess: str = "medium"
    required_human_review: bool = True
    proposed_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    agent_context: str | None = None


class DraftProposal(BaseModel):
    """A structured proposal for a new capability, created from MissingCapability."""

    proposal_id: str = Field(
        default_factory=lambda: f"prop_{uuid.uuid4().hex[:8]}"
    )
    status: ProposalStatus = ProposalStatus.PENDING
    capability: MissingCapability
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None


class ProposalParamSource(StrEnum):
    """Where a proposal parameter value comes from."""

    PATH = "path"
    QUERY = "query"
    BODY = "body"
    DERIVED = "derived"


class ProposalParamVariability(StrEnum):
    """Variability classification for observed parameter values."""

    VARIABLE = "variable"
    STABLE = "stable"
    UNKNOWN = "unknown"


class ProposalKind(StrEnum):
    """Capability kind for a catalog family or tool proposal."""

    REST = "rest"
    GRAPHQL = "graphql"


class DerivedParamResolver(BaseModel):
    """Metadata describing how a derived parameter is obtained at runtime."""

    name: str
    description: str
    source: str = "runtime"


class CatalogParameter(BaseModel):
    """Observed parameter profile in endpoint catalog families."""

    name: str
    source: ProposalParamSource
    required: bool = True
    variability: ProposalParamVariability = ProposalParamVariability.UNKNOWN
    observed_values: list[str] = Field(default_factory=list)
    default: Any | None = None
    resolver: DerivedParamResolver | None = None


class GraphQLOperationObservation(BaseModel):
    """Observed GraphQL operation metadata for an endpoint family."""

    operation_name: str
    operation_type: str = "unknown"
    count: int = 1


class EndpointFamily(BaseModel):
    """Templated endpoint family built from observed exchanges."""

    family_id: str
    host: str
    method: str
    path_template: str
    kind: ProposalKind = ProposalKind.REST
    observation_count: int = 0
    risk_tier: str = "low"
    confidence: float = 0.5
    tags: list[str] = Field(default_factory=list)
    response_key_hints: list[str] = Field(default_factory=list)
    sample_paths: list[str] = Field(default_factory=list)
    parameters: list[CatalogParameter] = Field(default_factory=list)
    graphql_operations: list[GraphQLOperationObservation] = Field(default_factory=list)
    needs_more_examples: list[str] = Field(default_factory=list)


class EndpointCatalog(BaseModel):
    """Catalog IR generated from traces before tool curation."""

    version: str = "1.0.0"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    capture_id: str
    scope: str
    families: list[EndpointFamily] = Field(default_factory=list)


class ToolProposalParameter(BaseModel):
    """Parameter for a proposed tool capability."""

    name: str
    source: ProposalParamSource
    required: bool = True
    description: str | None = None
    default: Any | None = None
    resolver: DerivedParamResolver | None = None


class ToolProposalSpec(BaseModel):
    """A proposed tool generated from the endpoint catalog."""

    proposal_id: str = Field(default_factory=lambda: f"tp_{uuid.uuid4().hex[:10]}")
    name: str
    kind: ProposalKind = ProposalKind.REST
    host: str
    method: str
    path_template: str
    risk_tier: str = "medium"
    confidence: float = 0.5
    requires_review: bool = True
    parameters: list[ToolProposalParameter] = Field(default_factory=list)
    fixed_body: dict[str, Any] | None = None
    operation_name: str | None = None
    operation_type: str | None = None
    rationale: list[str] = Field(default_factory=list)


class ToolProposalSet(BaseModel):
    """Collection of proposed tools derived from endpoint catalog IR."""

    version: str = "1.0.0"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    capture_id: str
    scope: str
    proposals: list[ToolProposalSpec] = Field(default_factory=list)


class ProposalQuestion(BaseModel):
    """Prompt for additional capture evidence needed for safe abstraction."""

    question_id: str = Field(default_factory=lambda: f"q_{uuid.uuid4().hex[:8]}")
    family_id: str
    priority: int = 2
    prompt: str
    capture_hint: str | None = None


class ProposalQuestionSet(BaseModel):
    """Set of follow-up capture questions for improving abstraction quality."""

    version: str = "1.0.0"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    capture_id: str
    scope: str
    questions: list[ProposalQuestion] = Field(default_factory=list)
