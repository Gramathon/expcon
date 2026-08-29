"""Adjudication logic.

Keeps three independent statuses:
  - execution_status: whether the code ran successfully
  - contract_status: whether the experiment was compliant
  - scientific_verdict: whether the hypothesis is supported

A negative result is not an execution failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from expcon.lifecycle.state import ExperimentState, RunState


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

    def adjudicate(self, run_id: str) -> AdjudicationResult:
        """Adjudicate a run based on its evidence and execution status."""
        from expcon.lifecycle.experiment_state import ExperimentLifecycle

        lifecycle = ExperimentLifecycle(self.workspace_root)
        run = lifecycle.load_run(run_id)

        # Determine execution status from run state
        if run.state in (RunState.COMPLETED, RunState.EVIDENCE_VERIFIED):
            exec_status = ExecutionStatus.COMPLETED
        elif run.state in (RunState.FAILED_EXECUTION, RunState.INVALID_RUN):
            exec_status = ExecutionStatus.FAILED
        elif run.state == RunState.BLOCKED:
            exec_status = ExecutionStatus.BLOCKED
        else:
            exec_status = ExecutionStatus.UNKNOWN

        # Verify evidence - check both runs/ and fetched/ directories
        evidence_dir = self.workspace_root / ".expcon" / "runs" / run_id / "evidence"
        if not evidence_dir.exists():
            fetched_dir = self.workspace_root / ".expcon" / "fetched" / run_id
            evidence_dir = fetched_dir / "evidence"
            if not evidence_dir.exists():
                evidence_dir = fetched_dir
        evidence_valid = False
        evidence_status = EvidenceStatus.UNKNOWN

        if evidence_dir.exists():
            from expcon.evidence.evidence import EvidenceVerifier

            # Find bundle path
            bundle_path = None
            exp_dir = self._find_experiment_dir(run.experiment_id, run.version)
            if exp_dir:
                bundle_dir = exp_dir / "bundle"
                if bundle_dir.exists():
                    bundle_path = bundle_dir

            verification = EvidenceVerifier(evidence_dir, bundle_path).verify()
            evidence_valid = verification["verified"]
            evidence_status = EvidenceStatus.VERIFIED if evidence_valid else EvidenceStatus.INVALID
        else:
            evidence_status = EvidenceStatus.UNKNOWN

        # Check contract compliance
        contract_valid = self._check_contract_compliance(run)
        contract_status = ContractStatus.COMPLIANT if contract_valid else ContractStatus.VIOLATION

        # Determine scientific verdict
        scientific_verdict = self._determine_scientific_verdict(run, evidence_dir, evidence_valid)

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
            },
            adjudicated_at=datetime.now(timezone.utc).isoformat(),
        )

        # Persist adjudication
        adj_file = self.workspace_root / ".expcon" / "runs" / run_id / "adjudication.json"
        adj_file.parent.mkdir(parents=True, exist_ok=True)
        adj_file.write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Update run state
        if evidence_valid and exec_status == ExecutionStatus.COMPLETED.value:
            lifecycle.update_run_state(run_id, RunState.ADJUDICATED, reason="Adjudication complete")

        return result

    def _check_contract_compliance(self, run) -> bool:
        """Check whether the run used the correct contract."""
        # Verify contract hash matches
        if not run.contract_hash:
            return False

        # Check if contract was tampered with
        experiment_dir = self._find_experiment_dir(run.experiment_id, run.version)
        if experiment_dir:
            lock_path = experiment_dir / "contract.lock.json"
            if lock_path.exists():
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                return lock.get("contract_hash") == run.contract_hash
        return True

    def _determine_scientific_verdict(
        self,
        run,
        evidence_dir: Path,
        evidence_valid: bool,
    ) -> ScientificVerdict:
        """Determine the scientific verdict from evidence metrics."""
        if not evidence_valid:
            return ScientificVerdict.INCONCLUSIVE

        # Look for metrics
        metrics_file = evidence_dir / "metrics" / "metrics.json"
        if metrics_file.exists():
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            return self._evaluate_metrics(metrics, run)

        # Look for aggregate results
        for results_file in evidence_dir.rglob("*_AGGREGATE_RESULT.json"):
            results = json.loads(results_file.read_text(encoding="utf-8"))
            return self._evaluate_aggregate(results, run)

        return ScientificVerdict.INCONCLUSIVE

    def _evaluate_metrics(self, metrics: dict[str, Any], run) -> ScientificVerdict:
        """Evaluate metrics against acceptance criteria."""
        # Check for acceptance criteria in the contract
        threshold = metrics.get("threshold")
        primary_metric = metrics.get("primary_metric_value")

        if threshold is not None and primary_metric is not None:
            if primary_metric >= threshold:
                return ScientificVerdict.SUPPORTED
            else:
                return ScientificVerdict.NOT_SUPPORTED

        # Check for verdict field
        verdict = metrics.get("verdict")
        if verdict == "SUPPORTED":
            return ScientificVerdict.SUPPORTED
        if verdict == "NOT_SUPPORTED":
            return ScientificVerdict.NOT_SUPPORTED

        return ScientificVerdict.INCONCLUSIVE

    def _evaluate_aggregate(self, results: dict[str, Any], run) -> ScientificVerdict:
        """Evaluate aggregate results for E13-style experiments."""
        # E13-style: look for overall verdict
        overall = results.get("overall_e13", "")
        if "SUPPORTED" in str(overall):
            return ScientificVerdict.SUPPORTED
        if "NOT_SUPPORTED" in str(overall):
            return ScientificVerdict.NOT_SUPPORTED
        if "WAITING" in str(overall):
            return ScientificVerdict.INCONCLUSIVE

        # Check by_space verdicts
        by_space = results.get("by_space", {})
        for space_name, space_data in by_space.items():
            verdict = space_data.get("verdict", "")
            if "NOT_SUPPORTED" in str(verdict):
                return ScientificVerdict.NOT_SUPPORTED

        # If all spaces are SUPPORTED
        all_supported = all(
            "SUPPORTED" in str(v.get("verdict", "")) for v in by_space.values()
        )
        if all_supported and by_space:
            return ScientificVerdict.SUPPORTED

        return ScientificVerdict.INCONCLUSIVE

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
