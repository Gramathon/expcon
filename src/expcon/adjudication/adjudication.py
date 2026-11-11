"""Adjudication logic.

Keeps three independent statuses:
  - execution_status: whether the code ran successfully
  - contract_status: whether the experiment was compliant
  - scientific_verdict: whether the hypothesis is supported

A negative result is not an execution failure.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from expcon.lifecycle.state import RunState
from expcon.contract.canonical import compute_contract_hash
from expcon.adjudication.acceptance import evaluate_acceptance
from expcon.evidence.collection import locate_evidence


class ScientificVerdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class ExecutionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class ContractStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"
    UNKNOWN = "UNKNOWN"


class EvidenceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass
class AdjudicationResult:
    """The result of adjudicating a run."""

    run_id: str
    experiment_id: str
    version: str
    execution_status: str
    contract_status: str
    evidence_status: str
    scientific_verdict: str
    evidence_valid: bool
    contract_valid: bool
    details: dict[str, Any] = field(default_factory=dict)
    adjudicated_at: str = ""
    adjudicator: str = "expcon"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "version": self.version,
            "execution_status": self.execution_status,
            "contract_status": self.contract_status,
            "evidence_status": self.evidence_status,
            "scientific_verdict": self.scientific_verdict,
            "evidence_valid": self.evidence_valid,
            "contract_valid": self.contract_valid,
            "details": self.details,
            "adjudicated_at": self.adjudicated_at,
            "adjudicator": self.adjudicator,
        }


class Adjudicator:
    """Adjudicates a run by evaluating execution, contract, and evidence status."""

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()

    def adjudicate(self, run_id: str, *, evidence_dir: Path | None = None) -> AdjudicationResult:
        """Adjudicate a run based on its evidence and execution status."""
        from expcon.lifecycle.experiment_state import ExperimentLifecycle

        lifecycle = ExperimentLifecycle(self.workspace_root)
        run = lifecycle.load_run(run_id)

        # Determine execution status from run state
        if run.state in (RunState.RESULTS_AVAILABLE, RunState.EVIDENCE_FETCHED,
                         RunState.EVIDENCE_VERIFIED, RunState.ADJUDICATED):
            exec_status = ExecutionStatus.COMPLETED
        elif run.state in (RunState.FAILED_EXECUTION, RunState.INVALID_RUN):
            exec_status = ExecutionStatus.FAILED
        elif run.state == RunState.BLOCKED:
            exec_status = ExecutionStatus.BLOCKED
        else:
            exec_status = ExecutionStatus.UNKNOWN
        # Evidence invalidation is independent of whether the process completed.
        results_file = lifecycle.run_dir(run_id) / "results.json"
        if exec_status == ExecutionStatus.UNKNOWN and results_file.is_file():
            try:
                success = json.loads(results_file.read_text()).get("success")
                if success is True:
                    exec_status = ExecutionStatus.COMPLETED
                elif success is False:
                    exec_status = ExecutionStatus.FAILED
            except (OSError, ValueError, AttributeError):
                pass  # Missing/invalid operational facts remain UNKNOWN.

        # Verify evidence - check both runs/ and fetched/ directories
        evidence_dir = evidence_dir or locate_evidence(self.workspace_root, run)
        evidence_valid = False
        evidence_status = EvidenceStatus.UNKNOWN

        if evidence_dir.exists():
            from expcon.evidence.evidence import EvidenceVerifier

            # Find bundle path
            bundle_path: Path | None = lifecycle.run_dir(run_id) / "bundle"
            if bundle_path is not None and not bundle_path.is_dir():
                bundle_path = None
            exp_dir = self._find_experiment_dir(run.experiment_id, run.version)
            if exp_dir and bundle_path is None:
                bundle_dir = exp_dir / "bundle"
                if bundle_dir.exists():
                    bundle_path = bundle_dir

            verification = EvidenceVerifier(evidence_dir, bundle_path, expected_run=run).verify()
            evidence_valid = verification["verified"]
            evidence_status = EvidenceStatus.VERIFIED if evidence_valid else EvidenceStatus.INVALID
        else:
            evidence_status = EvidenceStatus.UNKNOWN

        # Check contract compliance
        contract_valid = self._check_contract_compliance(run)
        contract_status = ContractStatus.COMPLIANT if contract_valid else ContractStatus.VIOLATION

        # Determine scientific verdict
        scientific_verdict = self._determine_scientific_verdict(
            run, evidence_dir,
            evidence_valid and contract_valid and exec_status == ExecutionStatus.COMPLETED,
        )

        result = AdjudicationResult(
            run_id=run_id,
            experiment_id=run.experiment_id,
            version=run.version,
            execution_status=exec_status.value,
            contract_status=contract_status.value,
            evidence_status=evidence_status.value,
            scientific_verdict=scientific_verdict.value,
            evidence_valid=evidence_valid,
            contract_valid=contract_valid,
            details={
                "run_state": run.state.value,
                "backend": run.backend,
                "kernel": run.kernel,
                "accelerator": run.accelerator,
                "contract_hash": run.contract_hash,
                "bundle_id": run.bundle_id,
                "candidate_evidence": str(evidence_dir),
            },
            adjudicated_at=datetime.now(timezone.utc).isoformat(),
        )

        # Persist adjudication
        adj_file = (self.workspace_root / ".expcon" / "runs" / run_id /
                    "adjudications" / f"{uuid.uuid4().hex}.json")
        adj_file.parent.mkdir(parents=True, exist_ok=True)
        adj_file.write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Update run state
        if evidence_valid and contract_valid and exec_status == ExecutionStatus.COMPLETED and run.state == RunState.EVIDENCE_VERIFIED:
            lifecycle.update_run_state(run_id, RunState.ADJUDICATED, reason="Adjudication complete")

        return result

    def _check_contract_compliance(self, run) -> bool:
        """Check whether the run used the correct contract."""
        return self._trusted_contract(run) is not None

    def _trusted_contract(self, run) -> dict[str, Any] | None:
        """Retained lock and immutable snapshot must agree with expected run identity."""
        retained = run.metadata.get("frozen_contract")
        retained_lock = run.metadata.get("frozen_lock", {})
        if retained is not None:
            identity = retained.get("experiment", {})
            if (compute_contract_hash(retained) == run.contract_hash
                    and retained_lock.get("contract_hash") == run.contract_hash
                    and identity.get("id") == run.experiment_id and identity.get("version") == run.version):
                return retained
            return None
        experiment_dir = self._find_experiment_dir(run.experiment_id, run.version)
        if experiment_dir is None or not run.contract_hash:
            return None
        try:
            lock = json.loads((experiment_dir / "contract.lock.json").read_text())
            contract = json.loads((experiment_dir / "bundle" / "resolved_contract.json").read_text())
            if lock.get("contract_hash") != run.contract_hash or compute_contract_hash(contract) != run.contract_hash:
                return None
            identity = contract.get("experiment", {})
            if identity.get("id") != run.experiment_id or identity.get("version") != run.version:
                return None
            return contract
        except (OSError, ValueError, TypeError):
            return None

    def _determine_scientific_verdict(
        self,
        run,
        evidence_dir: Path,
        evidence_valid: bool,
    ) -> ScientificVerdict:
        """Determine the scientific verdict from evidence metrics."""
        if not evidence_valid:
            return ScientificVerdict.INCONCLUSIVE

        # Only the frozen declared observation source is scientific authority.
        # Directory scanning must not choose a convenient aggregate/verdict file.
        from expcon.util.path import contained_path
        contract = self._trusted_contract(run)
        if contract is None:
            return ScientificVerdict.INCONCLUSIVE
        try:
            relative = contract.get("evaluation", {}).get("metrics_file", "metrics.json")
            path = contained_path(evidence_dir / "outputs", relative)
            if not path.is_file():
                return ScientificVerdict.INCONCLUSIVE
            observations = json.loads(path.read_text())
            if not isinstance(observations, dict):
                return ScientificVerdict.INCONCLUSIVE
            return self._evaluate_metrics(observations, run)
        except (OSError, ValueError, TypeError):
            return ScientificVerdict.INCONCLUSIVE

    def _evaluate_metrics(self, metrics: dict[str, Any], run) -> ScientificVerdict:
        contract = self._trusted_contract(run)
        if contract is None:
            return ScientificVerdict.INCONCLUSIVE
        rule = contract.get("evaluation", {}).get("acceptance")
        return ScientificVerdict(evaluate_acceptance(rule, metrics))

    def _evaluate_aggregate(self, results: dict[str, Any], run) -> ScientificVerdict:
        # Aggregate verdict strings are observations, never independent authority.
        return self._evaluate_metrics(results, run)

    def _find_experiment_dir(self, experiment_id: str, version: str) -> Optional[Path]:
        """Find the experiment directory for a given ID and version."""
        # Search common locations
        search_dirs = [
            self.workspace_root / "experiments",
            self.workspace_root / "examples",
            self.workspace_root.parent / "experiments" if self.workspace_root.name != "experiments" else None,
        ]

        for search_dir in search_dirs:
            if search_dir and search_dir.exists():
                for exp_dir in search_dir.iterdir():
                    if exp_dir.is_dir():
                        contract_path = exp_dir / "EXPERIMENT.yaml"
                        if contract_path.exists():
                            try:
                                from expcon.contract.contract import load_contract

                                contract = load_contract(contract_path)
                                if contract.experiment_id == experiment_id and contract.version == version:
                                    return exp_dir
                            except Exception:
                                pass
        return None


def adjudicate(workspace_root: Path | str, run_id: str) -> AdjudicationResult:
    """Convenience function to adjudicate a run."""
    adjudicator = Adjudicator(workspace_root)
    return adjudicator.adjudicate(run_id)
