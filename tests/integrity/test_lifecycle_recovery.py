import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.lifecycle.state import RunState
from expcon.runner.backends import LocalBackend, RunContext


def test_atomic_snapshot_recovers_from_authoritative_journal(tmp_path):
    lifecycle = ExperimentLifecycle(tmp_path)
    run = lifecycle.create_run("RECOVERY", "v001", "local")
    lifecycle.update_run_state(run.run_id, RunState.CONTRACT_VERIFIED)
    (lifecycle.run_dir(run.run_id) / "run.json").write_text("{interrupted")
    restored = ExperimentLifecycle(tmp_path).load_run(run.run_id)
    assert restored.state == RunState.CONTRACT_VERIFIED


def test_duplicate_transition_is_idempotent(tmp_path):
    lifecycle = ExperimentLifecycle(tmp_path)
    run = lifecycle.create_run("RECOVERY", "v001", "local")
    lifecycle.update_run_state(run.run_id, RunState.CONTRACT_VERIFIED)
    before = lifecycle.get_run_events(run.run_id)
    lifecycle.update_run_state(run.run_id, RunState.CONTRACT_VERIFIED)
    assert lifecycle.get_run_events(run.run_id) == before


def test_concurrent_same_transition_has_one_event(tmp_path):
    lifecycle = ExperimentLifecycle(tmp_path)
    run = lifecycle.create_run("RECOVERY", "v001", "local")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: lifecycle.update_run_state(run.run_id, RunState.CONTRACT_VERIFIED), range(8)))
    events = lifecycle.get_run_events(run.run_id)
    assert sum(item["event"] == "CONTRACT_VERIFIED" for item in events) == 1


def test_stage_dependencies_determine_order(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "resolved_contract.json").write_text(json.dumps({"execution": {"stages": [
        {"id": "evaluate", "entrypoint": "evaluate.py", "requires": ["train"]},
        {"id": "train", "entrypoint": "train.py", "requires": []}]}}))
    stages = LocalBackend(tmp_path)._extract_stages_from_contract(bundle)
    assert [stage["id"] for stage in stages] == ["train", "evaluate"]


@pytest.mark.parametrize("stage_id", ["../escape", "/tmp/expcon-recovery-unsafe-stage-fixture"])
def test_unsafe_stage_identifier_rejected_without_execution(tmp_path, stage_id):
    backend = LocalBackend(tmp_path)
    with pytest.raises(ValueError, match="UNSAFE"):
        backend._execute_stage({"id": stage_id, "entrypoint": "absent.py"}, tmp_path, tmp_path,
                               RunContext("E", "v001", "b", "c", run_id="safe"))


def test_context_does_not_persist_environment_binding_secret(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle_manifest.json").write_text("{}")
    (bundle / "resolved_contract.json").write_text('{"execution":{"stages":[]}}')
    context = RunContext("E", "v001", "b", "c", run_id="safe", environment_bindings={"API_KEY": "sentinel-private-value"})
    LocalBackend(tmp_path).submit(bundle, context)
    assert "sentinel-private-value" not in (tmp_path / ".expcon/runs/safe/context.json").read_text()


def test_duplicate_local_submission_does_not_rerun_or_overwrite(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle_manifest.json").write_text("{}")
    (bundle / "resolved_contract.json").write_text('{"execution":{"stages":[]}}')
    context = RunContext("E", "v001", "b", "c", run_id="safe")
    backend = LocalBackend(tmp_path)
    backend.submit(bundle, context)
    result = tmp_path / ".expcon/runs/safe/results.json"
    before = result.stat().st_mtime_ns
    assert backend.submit(bundle, context) == "safe"
    assert result.stat().st_mtime_ns == before


def test_local_cancel_does_not_claim_to_stop_unknown_process(tmp_path):
    assert LocalBackend(tmp_path).cancel("unknown") is False


def test_controlled_async_backend_transitions_without_false_failure(tmp_path):
    from expcon.runner.observation import observe
    lifecycle = ExperimentLifecycle(tmp_path)
    run = lifecycle.create_run("ASYNC", "v001", "fake")
    for state in (RunState.CONTRACT_VERIFIED, RunState.BACKEND_SELECTED,
                  RunState.DATA_VERIFIED, RunState.STAGE_STARTED):
        lifecycle.update_run_state(run.run_id, state)
    for status, expected in [("SUBMITTED", RunState.PENDING), ("PENDING", RunState.PENDING),
                             ("RUNNING", RunState.RUNNING), ("temporarily-unavailable", RunState.RUNNING),
                             ("COMPLETE", RunState.RESULTS_AVAILABLE)]:
        observe(lifecycle, run.run_id, status)
        assert lifecycle.load_run(run.run_id).state == expected
    assert not any(item["event"] == "FAILED_EXECUTION" for item in lifecycle.get_run_events(run.run_id))


def test_journal_commit_survives_snapshot_write_failure(tmp_path, monkeypatch):
    import expcon.lifecycle.experiment_state as state_module
    lifecycle = ExperimentLifecycle(tmp_path)
    run = lifecycle.create_run("RECOVERY", "v001", "local")
    real_write = state_module.atomic_json
    def interrupted(path, data):
        if path.name == "run.json":
            raise OSError("injected snapshot failure after journal commit")
        real_write(path, data)
    monkeypatch.setattr(state_module, "atomic_json", interrupted)
    with pytest.raises(OSError, match="injected"):
        lifecycle.update_run_state(run.run_id, RunState.CONTRACT_VERIFIED)
    assert lifecycle.load_run(run.run_id).state == RunState.CONTRACT_VERIFIED
    assert lifecycle.get_run_events(run.run_id)[-1]["event"] == "CONTRACT_VERIFIED"


def test_uncertain_submission_is_not_automatically_retried(tmp_path):
    directory = tmp_path / ".expcon/runs/safe"
    directory.mkdir(parents=True)
    (directory / "submission.json").write_text(json.dumps({"bundle_id": "b", "contract_hash": "c"}))
    from expcon.runner.backends import BackendError
    with pytest.raises(BackendError, match="SUBMISSION_OUTCOME_UNKNOWN"):
        LocalBackend(tmp_path).submit(tmp_path / "absent", RunContext("E", "v001", "b", "c", run_id="safe"))


def test_stale_metadata_writer_cannot_erase_newer_state(tmp_path):
    lifecycle = ExperimentLifecycle(tmp_path)
    original = lifecycle.create_run("RECOVERY", "v001", "local")
    lifecycle.update_run_state(original.run_id, RunState.CONTRACT_VERIFIED)
    with pytest.raises(RuntimeError, match="STALE_RUN_UPDATE"):
        lifecycle._save_run(original)


def test_experiment_and_run_state_namespaces_cannot_be_mixed():
    from expcon.lifecycle.state import ExperimentState, StateError, transition
    with pytest.raises(StateError):
        transition(ExperimentState.RUNNING, RunState.RUNNING)


def test_timeout_logs_redact_bound_secret_without_running_code(tmp_path, monkeypatch):
    import subprocess
    bundle = tmp_path / "bundle"
    (bundle / "runner").mkdir(parents=True)
    (bundle / "runner/driver.py").write_text("# trusted fixture; never executed\n")
    secret = "sentinel-timeout-private"
    class TimedOutProcess:
        pid = 123
        returncode = -9
        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("fixture", timeout)
            return secret, secret
        def kill(self):
            pass
    monkeypatch.setattr("expcon.runner.backends.subprocess.Popen", lambda *_, **__: TimedOutProcess())
    context = RunContext("E", "v001", "b", "c", run_id="safe", environment_bindings={"SECRET": secret})
    run_directory = tmp_path / "run"
    result = LocalBackend(tmp_path)._execute_stage({"id": "main", "entrypoint": "driver.py"}, bundle, run_directory, context)
    assert not result.success
    assert secret not in (run_directory / "stages/main/stdout.log").read_text()
    assert secret not in (run_directory / "stages/main/stderr.log").read_text()
