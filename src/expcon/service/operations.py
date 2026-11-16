"""Shared lifecycle orchestration; CLI presentation stays in the CLI."""

from __future__ import annotations
import json
import shutil
from pathlib import Path
import click
from expcon.contract.contract import load_contract
from expcon.contract.operations import validate_experiment, diff_experiment
from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.bundle.bundle import BundleVerifier, verify_frozen_bundle_compatibility
from expcon.runner.runner import StageRunner, RunContext
from expcon.runner.observation import observe
from expcon.runner.invocation import resolve_invocation
from expcon.runner.environment import EnvironmentError, preflight_local_environment
from expcon.runner.backends import ExecutionBackend, LocalBackend, KaggleBackend
from expcon.backends.colab import ColabBackend
from expcon.backends.tinker import TinkerBackend
from expcon.evidence.evidence import EvidenceVerifier, bind_evidence
from expcon.evidence.collection import collect_outputs, locate_evidence
from expcon.util.json_io import atomic_json
from expcon.adjudication.adjudication import Adjudicator
from expcon.artifacts.artifact import ArtifactRegistry


def _resolve_experiment(value):
    return Path(value).resolve()


def run(
    workspace_root,
    experiment,
    backend,
    kernel,
    accelerator,
    input_bindings,
    environment_bindings,
    as_json,
    reserved_run_id=None,
):
    """Run an experiment on a specified backend."""
    exp_path = _resolve_experiment(experiment)
    lifecycle = ExperimentLifecycle(workspace_root)
    lock_path = exp_path / "contract.lock.json"
    if not lock_path.exists():
        return {"status": "ERROR", "error": "Experiment must be frozen before running"}
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    try:
        validate_experiment(exp_path)
        divergence = diff_experiment(exp_path)
        if divergence.get("divergence_detected"):
            raise RuntimeError("Frozen experiment diverged; execution is refused")
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}
    contract = load_contract(exp_path / "EXPERIMENT.yaml")
    allowed_backends = contract.get("execution", "allowed_backends", default=[])
    if backend not in allowed_backends:
        return {
            "status": "ERROR",
            "error": f"Backend '{backend}' not allowed. Allowed: {allowed_backends}",
        }
    bundle_dir = exp_path / "bundle"
    if not bundle_dir.exists():
        return {
            "status": "ERROR",
            "error": "Bundle not found. Run 'expcon bundle' first.",
        }
    bundle_check = BundleVerifier(
        bundle_dir, expected_bundle_id=lock["identity"]["bundle_id"]
    ).verify()
    if bundle_check["status"] != "PASS":
        return {
            "status": "ERROR",
            "error": "Bundle verification failed",
            "details": bundle_check["errors"],
        }
    bundle_compatibility = verify_frozen_bundle_compatibility(exp_path, contract, lock)
    if bundle_compatibility["status"] != "PASS":
        return {
            "status": "ERROR",
            "error": "Frozen bundle compatibility verification failed",
            "details": bundle_compatibility,
        }
    materialized_bundle_id = bundle_check["bundle_id"]
    if materialized_bundle_id != bundle_compatibility["materialized_bundle_id"]:
        return {
            "status": "ERROR",
            "error": "Materialized bundle does not match the verified canonical bundle content identity",
            "details": bundle_compatibility,
        }
    environment_attestation = {}
    interpreter = None
    if backend == "local":
        try:
            environment_attestation = preflight_local_environment(
                bundle_dir, workspace_root
            )
            interpreter = environment_attestation["python_executable"]
        except EnvironmentError as exc:
            return {
                "status": "ERROR",
                "error": f"Local environment preflight failed: {exc}",
            }
    if backend == "kaggle":
        try:
            KaggleBackend(workspace_root).preflight(bundle_dir)
        except Exception as exc:
            return {
                "status": "BLOCKED",
                "reason": "BACKEND_CAPABILITY_MISMATCH",
                "error": str(exc),
            }
    if backend == "colab":
        return {
            "status": "BLOCKED",
            "reason": "PROVISIONING_ONLY",
            "error": "Colab has no approved workload channel; no runtime allocated",
        }
    named_inputs = _parse_named_bindings(input_bindings, "input")
    named_environment = _parse_named_bindings(environment_bindings, "environment")
    input_admission = []
    for stage in contract.get("execution", "stages", default=[]):
        if backend == "kaggle" and contract.get("execution", "kaggle") is not None:
            spec = (
                stage.get(
                    "invocation", contract.get("execution", "invocation", default={})
                )
                or {}
            )
            if any(not d.get("sha256") for d in spec.get("inputs", {}).values()):
                raise ValueError("SCIENTIFIC_INPUT_IDENTITY_REQUIRED")
            continue
        resolved = resolve_invocation(
            stage.get(
                "invocation", contract.get("execution", "invocation", default=None)
            ),
            bundle_root=bundle_dir,
            output_root=bundle_dir / "candidate-output" / stage["id"],
            input_bindings=named_inputs,
            environment_bindings=named_environment,
        )

        if any(
            not item["verified"]
            for item in resolved.attestation.get("input_identities", {}).values()
        ):
            raise ValueError("SCIENTIFIC_INPUT_IDENTITY_REQUIRED")
        input_admission.append(resolved.attestation)
    run = lifecycle.create_run(
        run_id=reserved_run_id,
        experiment_id=contract.experiment_id,
        version=contract.version,
        backend=backend,
        contract_hash=lock["contract_hash"],
        bundle_id=materialized_bundle_id,
        kernel=kernel,
        accelerator=accelerator,
        metadata={
            "bundle_compatibility": bundle_compatibility,
            "environment": environment_attestation,
            "frozen_contract": contract.data,
            "frozen_lock": lock,
            "input_admission": input_admission,
        },
    )
    snapshot = lifecycle.run_dir(run.run_id) / "bundle"
    shutil.copytree(bundle_dir, snapshot)
    if (
        BundleVerifier(snapshot, expected_bundle_id=materialized_bundle_id).verify()[
            "status"
        ]
        != "PASS"
    ):
        raise click.ClickException("Run snapshot failed verification")
    bundle_dir = snapshot
    if backend == "local":
        retained_inputs = {}
        for name, value in named_inputs.items():
            original = Path(value.removeprefix("bundle:"))
            if value.startswith("bundle:"):
                original = bundle_dir / original
            destination = lifecycle.run_dir(run.run_id) / "inputs" / name
            destination.parent.mkdir(exist_ok=True)
            if original.is_dir():
                shutil.copytree(original, destination)
            else:
                shutil.copy2(original, destination)
            retained_inputs[name] = str(destination)
        named_inputs = retained_inputs
    if backend == "local":
        backend_impl: ExecutionBackend = LocalBackend(workspace_root)
    elif backend == "kaggle":
        backend_impl = KaggleBackend(workspace_root)
    elif backend == "colab":
        backend_impl = ColabBackend(workspace_root)
    elif backend == "tinker":
        backend_impl = TinkerBackend(workspace_root)
    else:
        return {"status": "ERROR", "error": f"Unknown backend: {backend}"}
    runner = StageRunner(backend_impl)
    context = RunContext(
        experiment_id=contract.experiment_id,
        version=contract.version,
        bundle_id=materialized_bundle_id,
        contract_hash=lock["contract_hash"],
        kernel=kernel,
        accelerator=accelerator,
        environment={
            "requirements": contract.get("execution", "requirements", default={})
        },
        input_bindings=named_inputs,
        environment_bindings=named_environment,
        interpreter=interpreter,
        environment_attestation=environment_attestation,
    )
    for name in (
        "CONTRACT_VERIFIED",
        "BACKEND_SELECTED",
        "DATA_VERIFIED",
        "STAGE_STARTED",
    ):
        lifecycle.update_run_state(
            run.run_id, lifecycle_run_state_from_run(run.run_id, name), name
        )
    context.run_id = run.run_id
    try:
        runner.run(bundle_dir, context)
        backend_status = backend_impl.status(run.run_id)
        observed = observe(lifecycle, run.run_id, backend_status.state)
        if observed == "failed":
            return {
                "status": "ERROR",
                "error": backend_status.message,
                "run_id": run.run_id,
                "backend_status": backend_status.details,
            }
        result = {
            "status": "COMPLETED" if observed == "completed" else "SUBMITTED",
            "run_id": run.run_id,
            "experiment_id": contract.experiment_id,
            "version": contract.version,
            "backend": backend,
            "bundle_id": materialized_bundle_id,
            "frozen_bundle_id": lock["identity"]["bundle_id"],
            "kernel": kernel,
            "accelerator": accelerator,
        }
        return result
    except Exception as exc:
        failure_state = (
            "BLOCKED" if str(exc).startswith("BLOCKED:") else "FAILED_EXECUTION"
        )
        if failure_state == "FAILED_EXECUTION":
            current = lifecycle.load_run(run.run_id).state
            if current.value == "STAGE_STARTED":
                lifecycle.update_run_state(
                    run.run_id,
                    lifecycle_run_state_from_run(run.run_id, "STAGE_FAILED"),
                    str(exc),
                )
        if (
            failure_state == "BLOCKED"
            and lifecycle.load_run(run.run_id).state.value == "STAGE_STARTED"
        ):
            lifecycle.update_run_state(
                run.run_id,
                lifecycle_run_state_from_run(run.run_id, "STAGE_CANCELLED"),
                str(exc),
            )
        lifecycle.update_run_state(
            run.run_id,
            lifecycle_run_state_from_run(run.run_id, failure_state),
            str(exc),
        )
        return {"status": "ERROR", "error": str(exc), "run_id": run.run_id}


def lifecycle_run_state_from_run(run_id: str, state_name: str):
    from expcon.lifecycle.state import RunState

    return RunState(state_name)


def _parse_named_bindings(values, label: str) -> dict[str, str]:
    """Parse deterministic NAME=VALUE runtime bindings without shell expansion."""
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise click.BadParameter(f"{label} binding must use NAME=VALUE")
        (name, value) = item.split("=", 1)
        if not name or not value or name in result:
            raise click.BadParameter(f"invalid or duplicate {label} binding name")
        result[name] = value
    return result


def status(workspace_root, run_id, as_json):
    """Get status of a run."""
    lifecycle = ExperimentLifecycle(workspace_root)
    try:
        run = lifecycle.load_run(run_id)
    except KeyError:
        return {"status": "ERROR", "error": f"Run not found: {run_id}"}
    if run.backend == "local":
        backend: ExecutionBackend | None = LocalBackend(workspace_root)
    elif run.backend == "kaggle":
        backend = KaggleBackend(workspace_root)
    elif run.backend == "tinker":
        backend = TinkerBackend(workspace_root)
    else:
        backend = None
    backend_status = backend.status(run_id) if backend else None
    if backend_status:
        observe(lifecycle, run_id, backend_status.state)
        run = lifecycle.load_run(run_id)
    result = {
        "run_id": run.run_id,
        "experiment_id": run.experiment_id,
        "version": run.version,
        "state": run.state.value,
        "backend": run.backend,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "contract_hash": run.contract_hash,
        "bundle_id": run.bundle_id,
        "kernel": run.kernel,
        "accelerator": run.accelerator,
        "backend_status": backend_status.details if backend_status else None,
    }
    return result


def fetch(workspace_root, run_id, output_dir, as_json):
    """Fetch evidence from a completed run."""
    lifecycle = ExperimentLifecycle(workspace_root)
    try:
        run = lifecycle.load_run(run_id)
    except KeyError:
        return {"status": "ERROR", "error": f"Run not found: {run_id}"}
    if output_dir is None:
        output_dir = workspace_root / ".expcon" / "fetched" / run_id
    if run.backend == "local":
        backend: ExecutionBackend = LocalBackend(workspace_root)
    elif run.backend == "kaggle":
        backend = KaggleBackend(workspace_root)
    elif run.backend == "tinker":
        backend = TinkerBackend(workspace_root)
    else:
        return {"status": "ERROR", "error": f"Unknown backend: {run.backend}"}
    import uuid

    if run.state.value not in {
        "RESULTS_AVAILABLE",
        "EVIDENCE_FETCHED",
        "EVIDENCE_VERIFIED",
        "ADJUDICATED",
    }:
        raise click.ClickException(
            "Fetch requires observed successful execution completion"
        )
    attempt = uuid.uuid4().hex
    run_dir = lifecycle.run_dir(run_id)
    raw = run_dir / "fetches" / attempt
    report = {"attempt": attempt, "run_id": run_id, "status": "STARTED"}
    report_path = run_dir / "fetch_reports" / f"{attempt}.json"
    atomic_json(report_path, report)
    try:
        raw_path = backend.fetch(run_id, raw)
        bundle_dir = run_dir / "bundle"
        if not bundle_dir.is_dir():
            exp_dir = _find_experiment_dir(
                workspace_root, run.experiment_id, run.version
            )
            if exp_dir is None:
                raise RuntimeError("Frozen bundle unavailable")
            bundle_dir = exp_dir / "bundle"
        if (
            BundleVerifier(bundle_dir, expected_bundle_id=run.bundle_id).verify()[
                "status"
            ]
            != "PASS"
        ):
            raise RuntimeError("Frozen bundle verification failed before collection")
        source = collect_outputs(lifecycle, run, bundle_dir, raw_path)
        evidence_path = run_dir / "evidence_versions" / attempt
        contract = json.loads((bundle_dir / "resolved_contract.json").read_text())
        EvidenceVerifier(evidence_path).package_evidence(
            run_id,
            run.experiment_id,
            run.contract_hash,
            run.bundle_id,
            source,
            contract["outputs"]["required"],
        )
        bind_evidence(lifecycle, run_id, evidence_path)
        registry = ArtifactRegistry(run_dir)
        for path in sorted((evidence_path / "outputs").rglob("*")):
            if path.is_file():
                relative = path.relative_to(evidence_path / "outputs").as_posix()
                registry.register(
                    path,
                    "output",
                    run.experiment_id,
                    run_id,
                    producer_stage=relative.split("/")[1]
                    if relative.startswith("stages/")
                    else "declared_output",
                    metadata={
                        "bundle_id": run.bundle_id,
                        "contract_hash": run.contract_hash,
                        "evidence_path": relative,
                    },
                )
        run = lifecycle.load_run(run_id)
        run.metadata["evidence_path"] = str(evidence_path)
        lifecycle._save_run(run)
        if run.state.value == "RESULTS_AVAILABLE":
            lifecycle.update_run_state(
                run_id,
                lifecycle_run_state_from_run(run_id, "EVIDENCE_FETCHED"),
                "Evidence packaged and sealed",
            )
        report.update(status="COMPLETED", evidence_path=str(evidence_path))
        atomic_json(report_path, report)
    except Exception as exc:
        report.update(status="FAILED", error=str(exc))
        atomic_json(report_path, report)
        raise click.ClickException(
            f"Evidence fetch/collection failed; partial bytes preserved: {exc}"
        ) from exc
    return {"status": "FETCHED", "run_id": run_id, "evidence_path": str(evidence_path)}


def verify(workspace_root, run_id, bundle, as_json):
    """Verify evidence for a run."""
    lifecycle = ExperimentLifecycle(workspace_root)
    try:
        lifecycle.load_run(run_id)
    except KeyError:
        return {"status": "ERROR", "error": f"Run not found: {run_id}"}
    run_record = lifecycle.load_run(run_id)
    evidence_dir = locate_evidence(workspace_root, run_record)
    bundle_path = Path(bundle) if bundle else None
    if bundle_path is None and (lifecycle.run_dir(run_id) / "bundle").is_dir():
        bundle_path = lifecycle.run_dir(run_id) / "bundle"
    if bundle_path is None:
        try:
            run_record = lifecycle.load_run(run_id)
            exp_dir = _find_experiment_dir(
                workspace_root, run_record.experiment_id, run_record.version
            )
            if exp_dir and (exp_dir / "bundle").exists():
                bundle_path = exp_dir / "bundle"
        except Exception:
            pass
    verifier = EvidenceVerifier(evidence_dir, bundle_path, expected_run=run_record)
    result = verifier.verify()
    import uuid

    report = (
        lifecycle.run_dir(run_id) / "verification_reports" / f"{uuid.uuid4().hex}.json"
    )
    atomic_json(report, result)
    record = lifecycle.load_run(run_id)
    record.metadata["verification_path"] = str(report.relative_to(workspace_root))
    lifecycle._save_run(record)
    current = lifecycle.load_run(run_id).state.value
    if result["verified"] and current == "EVIDENCE_FETCHED":
        lifecycle.update_run_state(
            run_id,
            lifecycle_run_state_from_run(run_id, "EVIDENCE_VERIFIED"),
            "Evidence verified",
        )
    elif not result["verified"] and current in {
        "EVIDENCE_FETCHED",
        "EVIDENCE_VERIFIED",
        "ADJUDICATED",
    }:
        lifecycle.update_run_state(
            run_id,
            lifecycle_run_state_from_run(run_id, "EVIDENCE_INVALID"),
            "; ".join(result["errors"]),
        )
    return result


def adjudicate(workspace_root, run_id, as_json):
    """Adjudicate a run: determine execution, contract, and scientific status."""
    adjudicator = Adjudicator(workspace_root)
    result = adjudicator.adjudicate(run_id)
    return result.to_dict()


def _find_experiment_dir(
    workspace_root: Path, experiment_id: str, version: str
) -> Path | None:
    """Find the experiment directory by searching for matching EXPERIMENT.yaml."""
    search_dirs = [workspace_root / "experiments", workspace_root / "examples"]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for exp_dir in search_dir.iterdir():
            if exp_dir.is_dir() and (exp_dir / "EXPERIMENT.yaml").exists():
                try:
                    contract = load_contract(exp_dir / "EXPERIMENT.yaml")
                    if (
                        contract.experiment_id == experiment_id
                        and contract.version == version
                    ):
                        return exp_dir
                except Exception:
                    pass
    return None
