import json

import pytest

from expcon.adjudication.adjudication import Adjudicator
from expcon.lifecycle.state import RunState


def test_output_threshold_cannot_override_frozen_rule(research_run):
    root, _, _, run, _ = research_run(metrics={"accuracy": 0.2, "primary_metric_value": 0.2, "threshold": 0.1})
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict == "NOT_SUPPORTED"


def test_output_verdict_cannot_override_frozen_rule(research_run):
    root, _, _, run, _ = research_run(metrics={"accuracy": 0.2, "verdict": "SUPPORTED"})
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict == "NOT_SUPPORTED"


def test_frozen_rule_evaluates_observations_without_output_criteria(research_run):
    root, _, _, run, _ = research_run(metrics={"accuracy": 0.9})
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict == "SUPPORTED"


def test_negative_aggregate_is_never_positive(research_run):
    root, _, _, run, _ = research_run(aggregate={"overall_e13": "NOT_SUPPORTED"})
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict != "SUPPORTED"


@pytest.mark.parametrize("operator,value,threshold,expected", [
    ("<", 0.1, 0.2, "SUPPORTED"), ("<=", 0.2, 0.2, "SUPPORTED"),
    (">", 0.2, 0.2, "NOT_SUPPORTED"), (">=", 0.2, 0.2, "SUPPORTED"),
    ("==", 0.2, 0.2, "SUPPORTED"),
])
def test_explicit_comparison_semantics(research_run, operator, value, threshold, expected):
    root, _, _, run, _ = research_run(metrics={"error": value}, acceptance={
        "metric": "error", "operator": operator, "threshold": threshold})
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict == expected


def test_failed_execution_cannot_support(research_run):
    root, _, _, run, _ = research_run(metrics={"accuracy": 0.9, "verdict": "SUPPORTED"}, state=RunState.FAILED_EXECUTION)
    result = Adjudicator(root).adjudicate(run.run_id)
    assert result.execution_status == "FAILED"
    assert result.scientific_verdict == "INCONCLUSIVE"


def test_failed_compliance_cannot_support(research_run):
    root, exp, _, run, _ = research_run(metrics={"accuracy": 0.9, "verdict": "SUPPORTED"})
    lock = json.loads((exp / "contract.lock.json").read_text())
    lock["contract_hash"] = "0" * 64
    (exp / "contract.lock.json").write_text(json.dumps(lock))
    result = Adjudicator(root).adjudicate(run.run_id)
    assert not result.contract_valid
    assert result.scientific_verdict == "INCONCLUSIVE"


def test_missing_contract_is_not_compliant(research_run):
    root, _, _, run, _ = research_run(metrics={"verdict": "SUPPORTED"}, contract_present=False)
    result = Adjudicator(root).adjudicate(run.run_id)
    assert not result.contract_valid
    assert result.scientific_verdict == "INCONCLUSIVE"


@pytest.mark.parametrize("metrics", [{}, {"verdict": "SUPPORTED"}, {"accuracy": None}, {"accuracy": True}, {"accuracy": float("nan")}])
def test_missing_or_invalid_measurement_is_inconclusive(research_run, metrics):
    root, _, _, run, _ = research_run(metrics=metrics)
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict == "INCONCLUSIVE"


def test_invalid_evidence_cannot_support(research_run):
    root, _, _, run, evidence = research_run(metrics={"accuracy": 0.9, "verdict": "SUPPORTED"})
    (evidence / "artifacts" / "metrics.json").write_text("tampered")
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict == "INCONCLUSIVE"


@pytest.mark.parametrize("metrics,expected", [
    ({"accuracy": 0.9, "error": 0.1}, "SUPPORTED"),
    ({"accuracy": 0.9, "error": 0.4}, "NOT_SUPPORTED"),
    ({"accuracy": 0.9}, "INCONCLUSIVE"),
])
def test_all_criteria_require_complete_measurements(research_run, metrics, expected):
    root, _, _, run, _ = research_run(metrics=metrics, acceptance={"all": [
        {"metric": "accuracy", "operator": ">=", "threshold": 0.8},
        {"metric": "error", "operator": "<=", "threshold": 0.2},
    ]})
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict == expected


def test_repeated_adjudication_preserves_original_record(research_run):
    root, _, _, run, _ = research_run()
    directory = root / ".expcon/runs" / run.run_id
    original = directory / "adjudication.json"
    original.write_text('{"historical":true}')
    first = Adjudicator(root).adjudicate(run.run_id)
    second = Adjudicator(root).adjudicate(run.run_id)
    assert first.scientific_verdict == second.scientific_verdict == "SUPPORTED"
    assert original.read_text() == '{"historical":true}'
    assert len(list((directory / "adjudications").glob("*.json"))) == 2


def test_invalid_evidence_does_not_erase_execution_completion(research_run):
    from expcon.lifecycle.experiment_state import ExperimentLifecycle
    root, _, _, run, evidence = research_run()
    directory = root / ".expcon/runs" / run.run_id
    (directory / "results.json").write_text('{"success":true}')
    (evidence / "outputs/metrics.json").write_text("tampered")
    ExperimentLifecycle(root).update_run_state(run.run_id, RunState.EVIDENCE_INVALID)
    result = Adjudicator(root).adjudicate(run.run_id)
    assert result.execution_status == "COMPLETED"
    assert result.evidence_status == "INVALID"
    assert result.scientific_verdict == "INCONCLUSIVE"
