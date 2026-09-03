"""Integration tests for lifecycle transitions."""


import pytest
import yaml

from expcon.contract.operations import freeze_experiment
from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.lifecycle.state import ExperimentState, RunState, StateError


@pytest.fixture
def exp_with_lifecycle(tmp_path):
    contract = {
        "schema_version": 1,
        "experiment": {"id": "E00", "version": "v001", "title": "Test"},
        "hypothesis": {"statement": "Test hypothesis"},
        "source": {"repository": ".", "dirty_tree_allowed": False},
        "execution": {
            "allowed_backends": ["local"],
            "accelerator": {"type": "none"},
            "stages": [{"id": "main", "entrypoint": "run.py", "requires": []}],
        },
        "environment": {"python": "3.10", "dependency_lock": "uv.lock"},
        "evaluation": {"primary_metric": "accuracy", "threshold": 0.5},
        "outputs": {"required": ["metrics.json"]},
        "reproducibility": {"level": "seeded", "seed": 42},
        "scientific_parameters": {"seed": 42, "metric": "accuracy"},
    }
    exp_dir = tmp_path / "experiments" / "e00_v001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
    (exp_dir / "run.py").write_text("print('lifecycle runner')\n", encoding="utf-8")
    return exp_dir, ExperimentLifecycle(tmp_path)


class TestExperimentLifecycle:
    def test_draft_to_frozen(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        freeze_experiment(exp_dir, lifecycle.workspace_root)
        state = lifecycle.get_experiment_state(exp_dir)
        assert state == ExperimentState.FROZEN

    def test_invalid_draft_to_running(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        with pytest.raises(StateError):
            lifecycle.set_experiment_state(exp_dir, ExperimentState.RUNNING)

    def test_invalid_running_to_adjudicated(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        freeze_experiment(exp_dir, lifecycle.workspace_root)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.READY)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.SUBMITTED)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.RUNNING)
        with pytest.raises(StateError):
            lifecycle.set_experiment_state(exp_dir, ExperimentState.ADJUDICATED)

    def test_full_lifecycle(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        freeze_experiment(exp_dir, lifecycle.workspace_root)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.READY)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.SUBMITTED)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.RUNNING)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.RESULTS_AVAILABLE)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.EVIDENCE_VERIFIED)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.ADJUDICATED)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.CLOSED)
        assert lifecycle.get_experiment_state(exp_dir) == ExperimentState.CLOSED

    def test_state_survives_restart(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        freeze_experiment(exp_dir, lifecycle.workspace_root)
        lifecycle.set_experiment_state(exp_dir, ExperimentState.READY)

        # Simulate restart
        new_lifecycle = ExperimentLifecycle(lifecycle.workspace_root)
        state = new_lifecycle.get_experiment_state(exp_dir)
        assert state == ExperimentState.READY


class TestRunLifecycle:
    def test_run_created(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        run = lifecycle.create_run("E00", "v001", "local")
        assert run.state == RunState.CREATED
        assert run.experiment_id == "E00"

    def test_run_state_survives_restart(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        run = lifecycle.create_run("E00", "v001", "local")
        lifecycle.update_run_state(run.run_id, RunState.CONTRACT_VERIFIED, "test")
        lifecycle.update_run_state(run.run_id, RunState.BACKEND_SELECTED, "test")

        # Simulate restart
        new_lifecycle = ExperimentLifecycle(lifecycle.workspace_root)
        loaded_run = new_lifecycle.load_run(run.run_id)
        assert loaded_run.state == RunState.BACKEND_SELECTED

    def test_run_events_persisted(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        run = lifecycle.create_run("E00", "v001", "local")
        events = lifecycle.get_run_events(run.run_id)
        assert len(events) >= 1
        assert events[0]["event"] == "RUN_CREATED"

    def test_invalid_run_transition(self, exp_with_lifecycle):
        exp_dir, lifecycle = exp_with_lifecycle
        run = lifecycle.create_run("E00", "v001", "local")
        with pytest.raises(StateError):
            lifecycle.update_run_state(run.run_id, RunState.RUNNING, "invalid")
