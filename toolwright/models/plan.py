"""Plan report models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanToolpackInfo(BaseModel):
    id: str
    schema_version: str
    runtime_mode: str


class PlanBaselineInfo(BaseModel):
    resolved: bool
    snapshot_dir: str
    snapshot_digest: str


class PlanArtifactInfo(BaseModel):
    current_digest: str
    baseline_digest: str


class PlanSummary(BaseModel):
    tools_added: int
    tools_removed: int
    tools_modified: int
    schemas_changed: int
    policy_changed: int
    toolsets_changed: int
    evidence_changed: bool
    has_changes: bool


class PlanToolChange(BaseModel):
    tool_id: str
    name: str
    change_type: str
    endpoint_signature: str
    schema_before_digest: str | None = None
    schema_after_digest: str | None = None
    tool_before_digest: str | None = None
    tool_after_digest: str | None = None


class PlanSchemaChange(BaseModel):
    tool_id: str
    change_type: str
    before_digest: str | None = None
    after_digest: str | None = None


class PlanPolicyChange(BaseModel):
    rule_id: str
    change_type: str
    before_digest: str | None = None
    after_digest: str | None = None


class PlanToolsetChange(BaseModel):
    toolset: str
    added_actions: list[str] = Field(default_factory=list)
    removed_actions: list[str] = Field(default_factory=list)


class PlanChanges(BaseModel):
    tools: list[PlanToolChange] = Field(default_factory=list)
    schemas: list[PlanSchemaChange] = Field(default_factory=list)
    policy: list[PlanPolicyChange] = Field(default_factory=list)
    toolsets: list[PlanToolsetChange] = Field(default_factory=list)


class PlanEvidence(BaseModel):
    expected_hash: str | None = None
    actual_hash: str | None = None
    changed: bool
    missing: dict[str, bool]


class PlanReport(BaseModel):
    plan_version: str = "1"
    toolpack: PlanToolpackInfo
    baseline: PlanBaselineInfo
    artifacts: PlanArtifactInfo
    summary: PlanSummary
    changes: PlanChanges
    evidence: PlanEvidence
    warnings: list[str] = Field(default_factory=list)
