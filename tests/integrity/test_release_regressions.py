"""Release gates exercise real admission and verified adjudication paths."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from expcon.adjudication.adjudication import Adjudicator
from expcon.bundle.bundle import BundleVerifier
from expcon.evidence.evidence import EvidenceVerifier
from expcon.runner.environment import (
    EnvironmentError,
    _python_requirement_satisfied,
    preflight_local_environment,
)
from expcon.runner.inputs import content_identity
from expcon.runner.invocation import InvocationError, resolve_invocation


def test_oversized_integer_cannot_crash_scientific_evaluation(research_run):
    root, _, bundle, run, evidence = research_run(metrics={"accuracy": 10**400})
    assert EvidenceVerifier(evidence, bundle, expected_run=run).verify()["verified"]
    assert Adjudicator(root).adjudicate(run.run_id).scientific_verdict == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "version,rule,expected",
    [
        ("3.10.0", "==3.10", True),
        ("3.10.0", "!=3.10", False),
        ("3.10.0", "<=3.10", True),
        ("3.10.12", "<=3.10", False),
        ("3.11.0", ">=3.10,<3.12", True),
    ],
)
def test_python_constraints_pad_release_segments(version, rule, expected):
    assert _python_requirement_satisfied(version, rule) is expected


@pytest.mark.parametrize("mutation", ["add", "remove", "modify", "symlink", "missing"])
def test_declared_input_tree_mutations_fail_admission(tmp_path, mutation):
    dataset = tmp_path / "data"
    dataset.mkdir()
    values = dataset / "values.json"
    values.write_text("[1,2]")
    spec = {
        "inputs": {
            "data": {"kind": "directory", "sha256": content_identity(dataset)["sha256"]}
        },
        "argv": ["${inputs.data.root}"],
    }

    def admission():
        return resolve_invocation(
            spec,
            bundle_root=tmp_path,
            output_root=tmp_path / "out",
            input_bindings={"data": str(dataset)},
            environment_bindings={},
        )

    admission()
    reason = "CONTENT_IDENTITY_MISMATCH"
    if mutation == "add":
        (dataset / ".hidden").write_text("new input")
    elif mutation == "remove":
        values.unlink()
    elif mutation == "modify":
        values.write_text("[9]")
    elif mutation == "symlink":
        (dataset / "link").symlink_to(values)
        reason = "symlink"
    else:
        values.unlink()
        dataset.rmdir()
        reason = "Input binding does not exist"
    with pytest.raises(InvocationError, match=reason):
        admission()


@pytest.mark.parametrize(
    "field", ["run_id", "experiment_id", "contract_hash", "bundle_id"]
)
def test_evidence_requires_independent_expected_identity(research_run, field):
    _, _, bundle, run, evidence = research_run()
    assert EvidenceVerifier(evidence, bundle, expected_run=run).verify()["verified"]
    setattr(run, field, "wrong-identity")
    result = EvidenceVerifier(evidence, bundle, expected_run=run).verify()
    assert not result["verified"]
    assert any(field.upper() in error for error in result["errors"]), result


def test_missing_run_seal_cannot_verify(research_run):
    _, _, bundle, run, evidence = research_run()
    assert EvidenceVerifier(evidence, bundle, expected_run=run).verify()["verified"]
    run.metadata["evidence_seals"] = []
    result = EvidenceVerifier(evidence, bundle, expected_run=run).verify()
    assert not result["verified"]
    assert "EVIDENCE_SEAL_MISMATCH" in result["errors"]


def test_malformed_manifest_returns_failure_after_valid_baseline(research_run):
    _, _, bundle, run, evidence = research_run()
    assert EvidenceVerifier(evidence, bundle, expected_run=run).verify()["verified"]
    (evidence / "evidence_manifest.json").write_text("[]")
    result = EvidenceVerifier(evidence, bundle, expected_run=run).verify()
    assert not result["verified"]
    assert any("INVALID_EVIDENCE" in error for error in result["errors"])


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("lock", "SHA256 mismatch"),
        ("escape", "escapes workspace"),
        ("missing_lock", "lock is missing"),
        ("interpreter", "No verified local"),
        ("stages", "no execution stages"),
        ("entrypoint", "entrypoint is missing"),
        ("imports", "not importable"),
        ("python", "does not satisfy"),
        ("direct_versions", "direct dependency versions"),
        ("inventory", "distribution inventory"),
        ("accelerator", "attestation is not implemented"),
    ],
)
def test_local_environment_rejection_paths_after_valid_probe(
    tmp_path, monkeypatch, mutation, reason
):
    from expcon.hashing.digest import file_sha256

    bundle = tmp_path / "bundle"
    (bundle / "runner").mkdir(parents=True)
    entrypoint = bundle / "runner/model.py"
    entrypoint.write_text("# Trusted fixture; no code is executed\n")
    (tmp_path / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    lock = tmp_path / "lock.toml"
    lock.write_text(
        'requires-python=">=3.10,<3.13"\n[[package]]\nname="fixture"\nversion="1"\nsource={virtual="."}\ndependencies=[{name="example"}]\n[[package]]\nname="example"\nversion="1.0"\n'
    )
    contract = {
        "environment": {
            "dependency_lock": {"path": "lock.toml", "sha256": file_sha256(lock)},
            "distribution_versions": {"example": "1.0"},
        },
        "execution": {"stages": [{"entrypoint": "model.py"}]},
    }
    runtime = {
        "executable": sys.executable,
        "python_version": "3.10.12",
        "imports": [],
        "distributions": {"example": "1.0"},
        "installed_distributions": {"example": "1.0"},
    }
    probe = SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(runtime))
    monkeypatch.setattr(
        "expcon.runner.environment.subprocess.run", lambda *a, **kw: probe
    )
    manifest = bundle / "resolved_contract.json"
    manifest.write_text(json.dumps(contract))
    assert preflight_local_environment(bundle, tmp_path)["status"] == "PASS"
    if mutation == "lock":
        lock.write_text("# changed")
    elif mutation == "escape":
        contract["environment"]["dependency_lock"]["path"] = "../outside"
    elif mutation == "missing_lock":
        lock.unlink()
    elif mutation == "interpreter":
        (tmp_path / ".venv").unlink()
    elif mutation == "stages":
        contract["execution"]["stages"] = []
    elif mutation == "entrypoint":
        entrypoint.unlink()
    elif mutation == "imports":
        probe.returncode, probe.stderr = 1, "mock missing module"
    elif mutation == "python":
        runtime["python_version"] = "3.9.1"
    elif mutation == "direct_versions":
        runtime["distributions"] = {"example": "2.0"}
    elif mutation == "inventory":
        runtime["installed_distributions"] = {"example": "2.0"}
    else:
        contract["execution"]["accelerator"] = {"type": "gpu"}
    probe.stdout = json.dumps(runtime)
    manifest.write_text(json.dumps(contract))
    with pytest.raises(EnvironmentError, match=reason):
        preflight_local_environment(bundle, tmp_path)


@pytest.mark.parametrize(
    "mutation", ["payload", "checksum", "missing", "unexpected", "manifest"]
)
def test_v3_bundle_rejects_mutation_with_expected_root(research_run, mutation):
    from expcon.hashing.digest import file_sha256

    _, _, bundle, run, _ = research_run(bundle_algorithm="expcon-bundle-v3")

    def check():
        return BundleVerifier(bundle, expected_bundle_id=run.bundle_id).verify()

    assert check()["status"] == "PASS"
    path = bundle / "runner/runner.py"
    manifest_path = bundle / "bundle_manifest.json"
    if mutation in {"payload", "checksum"}:
        path.write_text("# Modified executable bytes, never executed\n")
        if mutation == "checksum":
            manifest = json.loads(manifest_path.read_text())
            for item in manifest["files"]:
                if item["relative_path"] == "runner/runner.py":
                    item.update(
                        sha256=file_sha256(path), size_bytes=path.stat().st_size
                    )
            manifest_path.write_text(json.dumps(manifest))
        reason = "EXECUTABLE_PAYLOAD_MISMATCH"
    elif mutation == "missing":
        path.unlink()
        reason = "MISSING:"
    elif mutation == "unexpected":
        (bundle / "runner/undeclared.py").write_text("# Never executed\n")
        reason = "EXTRA_FILE"
    else:
        manifest_path.write_text("[]")
        reason = "INVALID_BUNDLE"
    result = check()
    assert result["status"] == "FAIL"
    assert any(reason in error for error in result["errors"]), result


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("lock", "must be frozen"),
        ("source", "diverged"),
        ("backend", "not allowed"),
        ("bundle", "Bundle verification failed"),
        ("environment", "Local environment preflight failed"),
    ],
)
def test_cli_refuses_invalid_admission_before_creating_run(
    research_run, monkeypatch, mutation, reason
):
    from click.testing import CliRunner
    from expcon.cli import main

    root, experiment, bundle, run, evidence = research_run(
        bundle_algorithm="expcon-bundle-v3"
    )
    assert EvidenceVerifier(evidence, bundle, expected_run=run).verify()["verified"]
    runner = CliRunner()
    assert runner.invoke(main, ["validate", str(experiment), "--json"]).exit_code == 0
    original_runs = set((root / ".expcon/runs").iterdir())

    def forbidden_backend(*args, **kwargs):
        pytest.fail("Backend construction must follow successful admission")

    monkeypatch.setattr("expcon.cli.commands.LocalBackend", forbidden_backend)
    monkeypatch.setattr("expcon.cli.commands.KaggleBackend", forbidden_backend)
    backend = "local"
    if mutation == "lock":
        (experiment / "contract.lock.json").unlink()
    elif mutation == "source":
        (root / "runner.py").write_text("# Drift in frozen source\n")
    elif mutation == "backend":
        backend = "kaggle"
    elif mutation == "bundle":
        (bundle / "runner/runner.py").write_text("# Never executed\n")
    # The baseline fixture deliberately has no dependency lock: environment
    # admission must refuse it rather than launching the unexecuted fixture.
    result = runner.invoke(
        main, ["run", str(experiment), "--backend", backend, "--json"]
    )
    assert result.exit_code != 0
    assert reason in json.loads(result.output)["error"], result.output
    assert set((root / ".expcon/runs").iterdir()) == original_runs
