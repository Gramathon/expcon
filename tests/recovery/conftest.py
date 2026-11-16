"""Complete local fixtures; no provider access and no historical mutations."""
import json
from pathlib import Path

import pytest
import yaml

from expcon.bundle.bundle import BundleBuilder
from expcon.contract.operations import freeze_experiment
from expcon.evidence.evidence import EvidenceVerifier
from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.lifecycle.state import RunState


@pytest.fixture
def research_run(tmp_path):
    def create(metrics=None, acceptance=None, state=RunState.EVIDENCE_VERIFIED,
               aggregate=None, contract_present=True, bundle_algorithm=None):
        root = tmp_path / str(len(list(tmp_path.iterdir())))
        exp = root / "experiments" / "recovery"
        exp.mkdir(parents=True)
        (root / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.0.0"\n')
        (root / "runner.py").write_text("# Trusted, unexecuted fixture entrypoint.\n")
        contract = {
            "schema_version": 1,
            "experiment": {"id": "RECOVERY", "version": "v001", "title": "Fixture"},
            "hypothesis": {"statement": "Accuracy meets frozen bound"},
            "source": {"repository": str(root)},
            "execution": {"allowed_backends": ["local"], "stages": [
                {"id": "main", "entrypoint": "runner.py", "requires": []}]},
            "evaluation": {"primary_metric": "accuracy", "acceptance": acceptance or {
                "metric": "accuracy", "operator": ">=", "threshold": 0.8}},
            "outputs": {"required": ["metrics.json"]},
            "reproducibility": {"level": "seeded", "seed": 42},
        }
        if bundle_algorithm is not None:
            contract["bundle_identity_algorithm"] = bundle_algorithm
        (exp / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
        lock = freeze_experiment(exp, root)
        bundle, bundle_id = BundleBuilder(exp).build()
        lifecycle = ExperimentLifecycle(root)
        run = lifecycle.create_run("RECOVERY", "v001", "local", lock["contract_hash"], bundle_id,
                                   metadata={"experiment_dir": str(exp)})
        for target in [RunState.CONTRACT_VERIFIED, RunState.BACKEND_SELECTED,
                       RunState.DATA_VERIFIED, RunState.STAGE_STARTED]:
            lifecycle.update_run_state(run.run_id, target)
        if state == RunState.FAILED_EXECUTION:
            lifecycle.update_run_state(run.run_id, RunState.STAGE_FAILED)
            lifecycle.update_run_state(run.run_id, state)
        else:
            for target in [RunState.STAGE_COMPLETED, RunState.RESULTS_AVAILABLE,
                           RunState.EVIDENCE_FETCHED, RunState.EVIDENCE_VERIFIED]:
                lifecycle.update_run_state(run.run_id, target)
        run = lifecycle.load_run(run.run_id)
        source = root / "output"
        (source / "outputs").mkdir(parents=True)
        (source / "metrics").mkdir()
        payload = aggregate if aggregate is not None else (metrics if metrics is not None else {"accuracy": 0.9})
        (source / "outputs" / "metrics.json").write_text(json.dumps(payload))
        if aggregate is None:
            (source / "metrics" / "metrics.json").write_text(json.dumps(payload))
        else:
            (source / "metrics" / "X_AGGREGATE_RESULT.json").write_text(json.dumps(aggregate))
        (source / "resolved_contract.json").write_text(json.dumps(contract))
        (source / "environment.json").write_text(json.dumps({"python": "fixture", "platform": "fixture"}))
        evidence = lifecycle.run_dir(run.run_id) / "evidence"
        EvidenceVerifier(evidence).package_evidence(run.run_id, run.experiment_id,
            run.contract_hash, run.bundle_id, source, ["metrics.json"])
        if not contract_present:
            (exp / "EXPERIMENT.yaml").rename(exp / "unavailable.yaml")
        run = lifecycle.load_run(run.run_id)
        return root, exp, bundle, run, evidence
    return create
