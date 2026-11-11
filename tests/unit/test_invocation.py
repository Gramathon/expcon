"""Tests for frozen symbolic invocation resolution."""
from __future__ import annotations

import json
import pytest

from expcon.runner.backends import LocalBackend, RunContext
from expcon.runner.invocation import InvocationError, resolve_invocation, validate_invocation_spec
from expcon.contract.canonical import compute_execution_hash


def _spec() -> dict:
    return {
        "inputs": {"file": {"kind": "file"}, "tree": {"kind": "directory"}},
        "argv": ["--file", "${inputs.file.path}", "--tree", "${inputs.tree.root}", "--out", "${outputs.root}", "--bundle", "${bundle.root}"],
    }


def test_standard_protocol_has_no_extra_argv(tmp_path):
    result = resolve_invocation(None, bundle_root=tmp_path / "bundle", output_root=tmp_path / "out", input_bindings={}, environment_bindings={})
    assert result.argv == ["--bundle-root", str(tmp_path / "bundle"), "--output-root", str(tmp_path / "out")]


def test_ordered_inputs_output_and_bundle_are_deterministic(tmp_path):
    bundle, out = tmp_path / "bundle", tmp_path / "out"
    source, tree = tmp_path / "a b.txt", tmp_path / "tree dir"
    bundle.mkdir()
    source.write_text("x", encoding="utf-8")
    tree.mkdir()
    first = resolve_invocation(_spec(), bundle_root=bundle, output_root=out, input_bindings={"file": str(source), "tree": str(tree)}, environment_bindings={})
    second = resolve_invocation(_spec(), bundle_root=bundle, output_root=out, input_bindings={"tree": str(tree), "file": str(source)}, environment_bindings={})
    assert first.argv == second.argv
    assert first.argv[1] == str(source.resolve())
    assert first.argv[3] == str(tree.resolve())


def test_missing_undeclared_and_traversal_bindings_fail_closed(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with pytest.raises(InvocationError, match="Missing required"):
        resolve_invocation(_spec(), bundle_root=bundle, output_root=tmp_path / "out", input_bindings={}, environment_bindings={})
    with pytest.raises(InvocationError, match="Undeclared"):
        resolve_invocation(_spec(), bundle_root=bundle, output_root=tmp_path / "out", input_bindings={"other": str(bundle)}, environment_bindings={})
    with pytest.raises(InvocationError, match="traversal"):
        resolve_invocation({"inputs": {"file": {"kind": "file"}}, "argv": ["${inputs.file.path}"]}, bundle_root=bundle, output_root=tmp_path / "out", input_bindings={"file": "../escape"}, environment_bindings={})


def test_environment_symbol_is_declared_and_attested_without_value(tmp_path):
    spec = {"argv": ["--out", "${outputs.root}"], "environment": {"MODE": "${environment.CACHE_MODE}"}}
    result = resolve_invocation(spec, bundle_root=tmp_path, output_root=tmp_path / "out", input_bindings={}, environment_bindings={"CACHE_MODE": "read only"})
    assert result.environment == {"MODE": "read only"}
    assert result.attestation["environment_keys"] == ["MODE"]


def test_transport_paths_do_not_change_frozen_execution_identity(tmp_path):
    spec = {"inputs": {"file": {"kind": "file"}}, "argv": ["${inputs.file.path}"]}
    first, second = tmp_path / "one", tmp_path / "two"
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")
    contract = {"execution": {"allowed_backends": ["local"], "invocation": spec}}
    assert compute_execution_hash(contract) == compute_execution_hash(contract)
    assert resolve_invocation(spec, bundle_root=tmp_path, output_root=tmp_path / "out", input_bindings={"file": str(first)}, environment_bindings={}).argv != resolve_invocation(spec, bundle_root=tmp_path, output_root=tmp_path / "out", input_bindings={"file": str(second)}, environment_bindings={}).argv


def test_bundle_relative_input_binding_is_path_safe(tmp_path):
    payload = tmp_path / "bundle" / "inputs" / "payload.txt"
    payload.parent.mkdir(parents=True)
    payload.write_text("payload", encoding="utf-8")
    spec = {"inputs": {"file": {"kind": "file"}}, "argv": ["${inputs.file.path}"]}
    result = resolve_invocation(spec, bundle_root=tmp_path / "bundle", output_root=tmp_path / "out", input_bindings={"file": "bundle:inputs/payload.txt"}, environment_bindings={})
    assert result.argv == [str(payload.resolve())]
    with pytest.raises(InvocationError, match="traversal"):
        resolve_invocation(spec, bundle_root=tmp_path / "bundle", output_root=tmp_path / "out", input_bindings={"file": "bundle:../payload.txt"}, environment_bindings={})


def test_undeclared_symbol_is_rejected():
    with pytest.raises(InvocationError, match="undeclared"):
        validate_invocation_spec({"argv": ["${inputs.missing.path}"], "inputs": {}})


def test_local_backend_writes_resolved_argv_attestation(tmp_path):
    bundle = tmp_path / "bundle"
    runner = bundle / "runner"
    runner.mkdir(parents=True)
    (runner / "driver.py").write_text("import sys\n", encoding="utf-8")
    (bundle / "bundle_manifest.json").write_text("{}", encoding="utf-8")
    (bundle / "resolved_contract.json").write_text(json.dumps({"execution": {"stages": [{"id": "main", "entrypoint": "driver.py", "invocation": {"argv": ["--output", "${outputs.root}"]}}]}}), encoding="utf-8")
    context = RunContext("E01", "v001", "bundle", "contract", run_id="invocation-attestation")
    LocalBackend(tmp_path).submit(bundle, context)
    attestation = json.loads((tmp_path / ".expcon/runs/invocation-attestation/stages/main/invocation.json").read_text())
    assert attestation["protocol"] == "declared_v1"
    assert attestation["argv"][0] == "--output"


def _local_bundle(tmp_path, source: str) -> tuple[object, object]:
    bundle = tmp_path / "bundle"
    runner = bundle / "runner"
    runner.mkdir(parents=True)
    (runner / "driver.py").write_text(source, encoding="utf-8")
    (bundle / "bundle_manifest.json").write_text("{}", encoding="utf-8")
    (bundle / "resolved_contract.json").write_text(
        json.dumps({"execution": {"stages": [{"id": "main", "entrypoint": "driver.py"}]}}),
        encoding="utf-8",
    )
    return bundle, RunContext("E01", "v001", "bundle", "contract", run_id="local-result")


def test_local_backend_persists_stdout_stderr_and_child_exit(tmp_path):
    bundle, context = _local_bundle(tmp_path, "import sys; print('out'); print('err', file=sys.stderr); raise SystemExit(7)\n")
    LocalBackend(tmp_path).submit(bundle, context)
    stage = tmp_path / ".expcon/runs/local-result/stages/main"
    process = json.loads((stage / "process.json").read_text())
    assert process["child_pid"] is not None and process["returncode"] == 7
    assert (stage / "stdout.log").read_text() == "out\n"
    assert (stage / "stderr.log").read_text() == "err\n"


def test_local_backend_persists_spawn_failure(tmp_path):
    bundle, context = _local_bundle(tmp_path, "print('never reached')\n")
    context.interpreter = str(tmp_path / "missing-python")
    LocalBackend(tmp_path).submit(bundle, context)
    stage = tmp_path / ".expcon/runs/local-result/stages/main"
    process = json.loads((stage / "process.json").read_text())
    assert process["spawn_attempted"] and process["child_pid"] is None
    assert "FileNotFoundError" in process["exception"]


def test_local_backend_persists_successful_child_completion(tmp_path):
    bundle, context = _local_bundle(tmp_path, "print('ok')\n")
    LocalBackend(tmp_path).submit(bundle, context)
    stage = tmp_path / ".expcon/runs/local-result/stages/main"
    process = json.loads((stage / "process.json").read_text())
    assert process["returncode"] == 0
    assert (stage / "stdout.log").read_text() == "ok\n"


def test_kaggle_launcher_uses_nested_entrypoint_and_declared_argv(tmp_path):
    from expcon.runner.backends import KaggleBackend

    bundle = tmp_path / "bundle"
    (bundle / "runner/scripts").mkdir(parents=True)
    (bundle / "runner/scripts/driver.py").write_text("", encoding="utf-8")
    (bundle / "resolved_contract.json").write_text(json.dumps({"execution": {"invocation": {"argv": ["--out", "${outputs.root}"]}, "stages": [{"id": "nested", "entrypoint": "scripts/driver.py"}]} }), encoding="utf-8")
    context = RunContext("E01", "v001", "bundle", "contract", run_id="kaggle-plan")
    backend = KaggleBackend(tmp_path)
    plan = backend._execution_plan(bundle, context)
    assert plan[0]["entrypoint"] == "runner/scripts/driver.py"
    assert plan[0]["argv"][0] == "--out"
    script = backend._generate_kernel_script(context, plan)
    compile(script, "kaggle-launcher", "exec")
    assert 'runner.glob("*.py")' not in script
