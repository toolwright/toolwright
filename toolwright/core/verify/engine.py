"""VerifyEngine — orchestrator for all verification modes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from toolwright.core.verify.contracts import load_contracts, validate_contract_file
from toolwright.core.verify.evidence import (
    create_evidence_bundle,
    create_evidence_entry,
    save_evidence_bundle,
)
from toolwright.core.verify.outcomes import run_outcomes
from toolwright.core.verify.provenance import run_provenance
from toolwright.core.verify.replay import run_replay
from toolwright.models.verify import (
    ContractResult,
    EvidenceBundle,
    OutcomesResult,
    ReplayResult,
    VerifyMode,
    VerifyReport,
    VerifyStatus,
)


class VerifyEngine:
    """Orchestrates verification across all modes.

    Usage:
        engine = VerifyEngine(toolpack_id="tp_demo")
        report = engine.run(
            mode="all",
            tools_manifest=manifest,
            contract_path=Path("contracts.yaml"),
            baseline_path=Path("baseline.json"),
        )
    """

    def __init__(self, *, toolpack_id: str) -> None:
        self.toolpack_id = toolpack_id

    def run(
        self,
        *,
        mode: str,
        tools_manifest: dict[str, Any],
        contract_path: Path | None = None,
        baseline_path: Path | None = None,
        playbook_path: Path | None = None,
        ui_assertions_path: Path | None = None,
        assertions: list[dict[str, Any]] | None = None,
        playbook_version: str = "1.0",
        assertions_version: str = "1.0",
        top_k: int = 3,
        min_confidence: float = 0.6,
        strict: bool = False,
        unknown_budget: float = 0.3,
        governance_mode: str = "pre-approval",
        evidence_dir: Path | None = None,
    ) -> VerifyReport:
        """Run verification and return a structured report."""
        active_modes = self._expand_modes(mode)
        actions = tools_manifest.get("actions", [])
        tool_ids = [
            str(a.get("tool_id") or a.get("signature_id") or a.get("name"))
            for a in actions
        ]

        contracts_result: ContractResult | None = None
        replay_result: ReplayResult | None = None
        outcomes_result: OutcomesResult | None = None
        provenance_result: dict[str, Any] | None = None

        if "contracts" in active_modes:
            contracts_result = self._run_contracts(contract_path, strict=strict)

        if "replay" in active_modes:
            replay_result = self._run_replay(baseline_path, tools_manifest)

        if "outcomes" in active_modes:
            outcomes_result = self._run_outcomes(contract_path, baseline_path)

        if "provenance" in active_modes:
            provenance_result = self._run_provenance(
                actions=actions,
                assertions=assertions or [],
                top_k=top_k,
                min_confidence=min_confidence,
                playbook_version=playbook_version,
                assertions_version=assertions_version,
                playbook_path=str(playbook_path) if playbook_path else None,
                ui_assertions_path=str(ui_assertions_path) if ui_assertions_path else None,
            )

        # Collect evidence
        evidence_bundle_id: str | None = None
        if evidence_dir:
            bundle = self._collect_evidence(
                contracts_result=contracts_result,
                replay_result=replay_result,
                outcomes_result=outcomes_result,
                provenance_result=provenance_result,
            )
            save_evidence_bundle(bundle, evidence_dir)
            evidence_bundle_id = bundle.bundle_id

        # Determine overall status
        exit_code, overall_status = self._evaluate(
            contracts_result=contracts_result,
            replay_result=replay_result,
            outcomes_result=outcomes_result,
            provenance_result=provenance_result,
            strict=strict,
            unknown_budget=unknown_budget,
        )

        return VerifyReport(
            toolpack_id=self.toolpack_id,
            mode=mode,
            governance_mode=governance_mode,
            config={
                "strict": strict,
                "top_k": top_k,
                "min_confidence": min_confidence,
                "unknown_budget": unknown_budget,
            },
            contracts=contracts_result,
            replay=replay_result,
            outcomes=outcomes_result,
            provenance=provenance_result,
            evidence_bundle_id=evidence_bundle_id,
            tool_ids=tool_ids,
            exit_code=exit_code,
            overall_status=overall_status,
        )

    def _expand_modes(self, mode: str) -> set[str]:
        if mode == VerifyMode.ALL or mode == "all":
            return {"contracts", "replay", "outcomes", "provenance"}
        return {mode}

    def _run_contracts(
        self,
        contract_path: Path | None,
        *,
        strict: bool,
    ) -> ContractResult:
        if not contract_path:
            return ContractResult(
                contract_id="file_check",
                status=VerifyStatus.FAIL if strict else VerifyStatus.UNKNOWN,
                fail_count=1 if strict else 0,
                unknown_count=0 if strict else 1,
            )
        return validate_contract_file(contract_path)

    def _run_replay(
        self,
        baseline_path: Path | None,
        tools_manifest: dict[str, Any],
    ) -> ReplayResult:
        if not baseline_path:
            return ReplayResult(status=VerifyStatus.UNKNOWN, unknown_count=1)
        return run_replay(baseline_path=baseline_path, tools_manifest=tools_manifest)

    def _run_outcomes(
        self,
        contract_path: Path | None,
        baseline_path: Path | None,
    ) -> OutcomesResult:
        if not contract_path or not contract_path.exists():
            return OutcomesResult(status=VerifyStatus.UNKNOWN, unknown_count=1)

        try:
            contracts = load_contracts(contract_path)
        except (FileNotFoundError, ValueError):
            return OutcomesResult(status=VerifyStatus.UNKNOWN, unknown_count=1)

        baseline_data: dict[str, Any] = {}
        if baseline_path and baseline_path.exists():
            try:
                raw = baseline_path.read_text(encoding="utf-8")
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    baseline_data = loaded
            except (json.JSONDecodeError, OSError):
                pass

        return run_outcomes(contracts=contracts, baseline_data=baseline_data)

    def _run_provenance(
        self,
        *,
        actions: list[dict[str, Any]],
        assertions: list[dict[str, Any]],
        top_k: int,
        min_confidence: float,
        playbook_version: str,
        assertions_version: str,
        playbook_path: str | None,
        ui_assertions_path: str | None,
    ) -> dict[str, Any]:
        return run_provenance(
            actions=actions,
            assertions=assertions,
            top_k=top_k,
            min_confidence=min_confidence,
            playbook_version=playbook_version,
            assertions_version=assertions_version,
            playbook_path=playbook_path,
            ui_assertions_path=ui_assertions_path,
        )

    def _collect_evidence(
        self,
        *,
        contracts_result: ContractResult | None,
        replay_result: ReplayResult | None,
        outcomes_result: OutcomesResult | None,
        provenance_result: dict[str, Any] | None,
    ) -> EvidenceBundle:
        entries = []
        if contracts_result:
            entries.append(create_evidence_entry(
                event_type="verify_contracts",
                source="verify_engine",
                data=contracts_result.model_dump(mode="json"),
            ))
        if replay_result:
            entries.append(create_evidence_entry(
                event_type="verify_replay",
                source="verify_engine",
                data=replay_result.model_dump(mode="json"),
            ))
        if outcomes_result:
            entries.append(create_evidence_entry(
                event_type="verify_outcomes",
                source="verify_engine",
                data=outcomes_result.model_dump(mode="json"),
            ))
        if provenance_result:
            entries.append(create_evidence_entry(
                event_type="verify_provenance",
                source="verify_engine",
                data=provenance_result,
            ))
        return create_evidence_bundle(
            toolpack_id=self.toolpack_id,
            context="verify",
            entries=entries,
        )

    def _evaluate(
        self,
        *,
        contracts_result: ContractResult | None,
        replay_result: ReplayResult | None,
        outcomes_result: OutcomesResult | None,
        provenance_result: dict[str, Any] | None,
        strict: bool,
        unknown_budget: float,
    ) -> tuple[int, VerifyStatus]:
        """Evaluate all results into exit code + overall status."""
        statuses: list[str] = []

        if contracts_result:
            statuses.append(contracts_result.status)
        if replay_result:
            statuses.append(replay_result.status)
        if outcomes_result:
            statuses.append(outcomes_result.status)
        if provenance_result and isinstance(provenance_result, dict):
            prov_status = provenance_result.get("status")
            if isinstance(prov_status, str) and prov_status != "skipped":
                statuses.append(prov_status)

        if not statuses:
            return 0, VerifyStatus.UNKNOWN

        if "fail" in statuses:
            return 2, VerifyStatus.FAIL

        # Check unknown budget for provenance
        unknown_ratio = 0.0
        if provenance_result and isinstance(provenance_result, dict):
            results = provenance_result.get("results", [])
            if isinstance(results, list) and results:
                unknown_count = sum(
                    1 for item in results
                    if isinstance(item, dict) and item.get("status") == "unknown"
                )
                unknown_ratio = unknown_count / len(results)

        if unknown_ratio > unknown_budget:
            return 1, VerifyStatus.UNKNOWN

        if strict and "unknown" in statuses:
            return 1, VerifyStatus.UNKNOWN

        return 0, VerifyStatus.PASS
