"""Reproducible local ML control study. Refuses to overwrite existing evidence."""

import argparse
import json
import math
import os
import shutil
import statistics
import resource
import subprocess
import sys
import time
import uuid
import tempfile
from pathlib import Path

import yaml

from expcon.adjudication.adjudication import Adjudicator
from expcon.evidence.evidence import EvidenceVerifier
from expcon.hashing.digest import file_sha256
from expcon.lifecycle.experiment_state import ExperimentLifecycle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Parent for a new unique workspace; existing evidence is never reused",
    )
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    directory = Path(__file__).resolve().parent
    workspace = (
        args.output_root or Path(tempfile.gettempdir()) / "expcon-studies"
    ).resolve() / uuid.uuid4().hex
    workspace.mkdir(parents=True)
    protocol_source = directory / "workload/protocol.json"
    shutil.copy2(protocol_source, workspace / "protocol.json")
    protocol = json.loads((workspace / "protocol.json").read_text())
    (workspace / "scripts").mkdir()
    for name in ["generate.py", "model.py"]:
        shutil.copy2(directory / "workload" / name, workspace / "scripts" / name)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname="expcon-recovery-study"\nversion="0.1.0"\n'
    )
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Run this study from an installed virtual environment")
    (workspace / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    major, minor = sys.version_info[:2]
    (workspace / "installed.lock.toml").write_text(
        f'version = 1\nrequires-python = ">={major}.{minor},<{major}.{minor + 1}"\n'
        '[[package]]\nname="expcon-recovery-study"\nversion="0.1.0"\nsource={virtual="."}\ndependencies=[]\n'
    )
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    observed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions()}))",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    distributions = json.loads(observed.stdout)
    subprocess.run(
        [
            sys.executable,
            "-B",
            str(workspace / "scripts/generate.py"),
            str(workspace / "data/dataset.json"),
        ],
        check=True,
        env=environment,
    )
    dataset_hash = file_sha256(workspace / "data/dataset.json")
    commands = []
    summaries = []
    report = {
        "protocol_sha256": file_sha256(workspace / "protocol.json"),
        "workspace": str(workspace),
        "dataset_sha256": dataset_hash,
        "protocol": protocol,
        "commands": commands,
        "runs": summaries,
        "runtime": {"python": sys.version, "distributions": distributions},
        "status": "STARTED",
    }
    report["controller_source_manifest"] = {
        str(path.relative_to(repository)): file_sha256(path)
        for path in sorted((repository / "src/expcon").rglob("*.py"))
    }
    report["validation_harness_sha256"] = file_sha256(Path(__file__))
    report_path = workspace / "validation.json"

    def preserve():
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    preserve()

    def invoke(args, experiment=None):
        if experiment is not None and args[0] not in {"inspect", "validate"}:
            invoke(["validate", str(experiment), "--json"])
        start = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-B", "-c", "from expcon.cli import main; main()", *args],
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
        )
        elapsed = time.perf_counter() - start
        entry = {
            "argv": args,
            "wall_seconds": elapsed,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        commands.append(entry)
        preserve()
        if result.returncode:
            raise RuntimeError(
                f"Failed command {args}: {result.stdout} {result.stderr}"
            )
        return json.loads(result.stdout), elapsed

    try:
        contracts = {}
        for label, epochs in [
            ("positive", protocol["positive_epochs"]),
            ("negative", protocol["negative_epochs"]),
        ]:
            experiment = workspace / "experiments" / label
            experiment.mkdir(parents=True)
            contract = {
                "schema_version": 1,
                "bundle_identity_algorithm": "expcon-bundle-v3",
                "experiment": {
                    "id": "RECOVERY_" + label.upper(),
                    "version": "v001",
                    "title": "Local logistic regression validation",
                },
                "hypothesis": {
                    "statement": "Held-out accuracy >= 0.8 and log loss <= 0.55"
                },
                "source": {"repository": "."},
                "execution": {
                    "allowed_backends": ["local"],
                    "accelerator": {"type": "none"},
                    "source": {
                        "entrypoint": "scripts/model.py",
                        "include": ["scripts/model.py", "scripts/generate.py"],
                    },
                    "stages": [
                        {
                            "id": "train_evaluate",
                            "entrypoint": "scripts/model.py",
                            "requires": [],
                        }
                    ],
                    "invocation": {
                        "inputs": {"dataset": {"kind": "file", "sha256": dataset_hash}},
                        "argv": [
                            "--dataset",
                            "${inputs.dataset.path}",
                            "--contract",
                            "${contract.path}",
                            "--output-root",
                            "${outputs.root}",
                        ],
                    },
                },
                "environment": {
                    "dependency_lock": {
                        "path": "installed.lock.toml",
                        "sha256": file_sha256(workspace / "installed.lock.toml"),
                    },
                    "distribution_versions": distributions,
                },
                "data": {
                    "generator_seed": 1729,
                    "train": 640,
                    "test": 256,
                    "split": "fixed disjoint IDs",
                },
                "evaluation": {
                    "primary_metric": "accuracy",
                    "acceptance": protocol["acceptance"],
                },
                "outputs": {
                    "required": ["metrics.json", "model.json", "predictions.json"]
                },
                "reproducibility": {"level": "seeded", "seed": 1729},
                "scientific_parameters": {
                    "epochs": epochs,
                    "learning_rate": protocol["learning_rate"],
                    "deviation": "trained model"
                    if label == "positive"
                    else protocol["negative_scientific_deviation"],
                },
            }
            (experiment / "EXPERIMENT.yaml").write_text(
                yaml.safe_dump(contract, sort_keys=True)
            )
            invoke(["inspect", str(experiment), "--json"])
            invoke(["validate", str(experiment), "--json"])
            frozen, _ = invoke(["freeze", str(experiment), "--json"], experiment)
            invoke(["diff", str(experiment), "--json"], experiment)
            invoke(["bundle", str(experiment), "--json"], experiment)
            invoke(["verify-bundle", str(experiment / "bundle"), "--json"], experiment)
            contracts[label] = (experiment, frozen)
        lifecycle = ExperimentLifecycle(workspace)

        def run(label, trial):
            experiment, frozen = contracts[label]
            if label == "positive":
                direct = workspace / "direct" / str(trial)
                start = time.perf_counter()
                subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(experiment / "bundle/runner/scripts/model.py"),
                        "--dataset",
                        str(workspace / "data/dataset.json"),
                        "--contract",
                        str(experiment / "bundle/resolved_contract.json"),
                        "--output-root",
                        str(direct),
                    ],
                    check=True,
                    capture_output=True,
                    env=environment,
                    cwd=workspace,
                )
                direct_seconds = time.perf_counter() - start
            else:
                direct_seconds = None
            submitted, execution_seconds = invoke(
                [
                    "run",
                    str(experiment),
                    "--backend",
                    "local",
                    "--input",
                    f"dataset={workspace / 'data/dataset.json'}",
                    "--json",
                ],
                experiment,
            )
            run_id = submitted["run_id"]
            fetched, packaging_seconds = invoke(["fetch", run_id, "--json"], experiment)
            verified, verification_seconds = invoke(
                ["verify", run_id, "--json"], experiment
            )
            adjudication, _ = invoke(["adjudicate", run_id, "--json"], experiment)
            run_dir = lifecycle.run_dir(run_id)
            stage = run_dir / "stages/train_evaluate"
            observations = json.loads((stage / "metrics.json").read_text())
            entry = {
                "label": label,
                "trial": trial,
                "run_id": run_id,
                "contract_hash": frozen["contract_hash"],
                "bundle_id": submitted["bundle_id"],
                "metrics": observations,
                "adjudication": adjudication,
                "verification": verified,
                "evidence_path": fetched["evidence_path"],
                "direct_seconds": direct_seconds,
                "controlled_execution_seconds": execution_seconds,
                "packaging_seconds": packaging_seconds,
                "verification_seconds": verification_seconds,
                "stage_seconds": json.loads((run_dir / "results.json").read_text())[
                    "stages"
                ][0]["duration_seconds"],
                "process_dispatch_seconds": json.loads(
                    (stage / "process.json").read_text()
                )["dispatch_seconds"],
                "environment_identity": lifecycle.load_run(run_id).metadata[
                    "environment"
                ]["runtime_environment_identity"],
                "artifact_hashes": {
                    name: file_sha256(stage / name)
                    for name in ["metrics.json", "model.json", "predictions.json"]
                },
            }
            summaries.append(entry)
            preserve()
            expected = "SUPPORTED" if label == "positive" else "NOT_SUPPORTED"
            assert adjudication["scientific_verdict"] == expected, entry
            assert (
                adjudication["execution_status"] == "COMPLETED"
                and adjudication["evidence_status"] == "VERIFIED"
            )
            return entry

        for trial in range(protocol["performance_repetitions"]):
            run("positive", trial)
        negative = run("negative", 0)
        positive = [entry for entry in summaries if entry["label"] == "positive"]
        first = positive[0]
        comparisons = []
        for candidate in positive[1:]:
            reference_model = json.loads(
                (Path(first["evidence_path"]) / "outputs/model.json").read_text()
            )
            candidate_model = json.loads(
                (Path(candidate["evidence_path"]) / "outputs/model.json").read_text()
            )
            assert len(reference_model["weights"]) == len(candidate_model["weights"])
            deltas = [
                abs(a - b)
                for a, b in zip(reference_model["weights"], candidate_model["weights"])
            ]
            deltas.append(abs(reference_model["bias"] - candidate_model["bias"]))
            assert all(math.isfinite(value) for value in deltas)
            comparisons.append(
                {
                    "run_id": candidate["run_id"],
                    "same_contract": first["contract_hash"]
                    == candidate["contract_hash"],
                    "same_bundle": first["bundle_id"] == candidate["bundle_id"],
                    "same_environment": first["environment_identity"]
                    == candidate["environment_identity"],
                    "accuracy_delta": abs(
                        first["metrics"]["accuracy"] - candidate["metrics"]["accuracy"]
                    ),
                    "log_loss_delta": abs(
                        first["metrics"]["log_loss"] - candidate["metrics"]["log_loss"]
                    ),
                    "model_max_absolute_delta": max(deltas),
                    "artifact_bytes_equal": first["artifact_hashes"]
                    == candidate["artifact_hashes"],
                }
            )
        assert all(
            item["same_contract"]
            and item["same_bundle"]
            and item["same_environment"]
            and item["accuracy_delta"]
            <= protocol["replay_tolerances"]["accuracy_absolute"]
            and item["log_loss_delta"]
            <= protocol["replay_tolerances"]["log_loss_absolute"]
            and item["model_max_absolute_delta"]
            <= protocol["replay_tolerances"]["weight_absolute"]
            for item in comparisons
        )
        report["replay_comparisons"] = comparisons
        trusted_run = lifecycle.load_run(first["run_id"])
        tampered = workspace / "controlled_tamper_copy"
        shutil.copytree(first["evidence_path"], tampered)
        (tampered / "outputs/model.json").write_text('{"weights":[999]}')
        failure = EvidenceVerifier(
            tampered,
            lifecycle.run_dir(first["run_id"]) / "bundle",
            expected_run=trusted_run,
        ).verify()
        tamper_adjudication = (
            Adjudicator(workspace)
            .adjudicate(first["run_id"], evidence_dir=tampered)
            .to_dict()
        )
        assert (
            not failure["verified"]
            and tamper_adjudication["scientific_verdict"] == "INCONCLUSIVE"
        )
        report["integrity_failure"] = {
            "verification": failure,
            "adjudication": tamper_adjudication,
            "original_evidence_preserved": True,
        }
        report["timing_summary"] = {}
        for name in [
            "direct_seconds",
            "controlled_execution_seconds",
            "stage_seconds",
            "process_dispatch_seconds",
            "packaging_seconds",
            "verification_seconds",
        ]:
            values = [entry[name] for entry in positive]
            report["timing_summary"][name] = {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
        for command in ["validate", "bundle"]:
            experiment = contracts["positive"][0]
            values = [
                invoke([command, str(experiment), "--json"], experiment)[1]
                for _ in range(5)
            ]
            report["timing_summary"][command + "_seconds"] = {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
        differences = [
            entry["controlled_execution_seconds"] - entry["direct_seconds"]
            for entry in positive
        ]
        report["timing_summary"]["paired_execution_control_overhead_seconds"] = {
            "median": statistics.median(differences),
            "min": min(differences),
            "max": max(differences),
        }
        report["resource_observations"] = {
            "controller_peak_rss_kib": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss,
            "largest_child_peak_rss_kib": resource.getrusage(
                resource.RUSAGE_CHILDREN
            ).ru_maxrss,
            "logical_workspace_file_bytes": sum(
                path.stat().st_size for path in workspace.rglob("*") if path.is_file()
            ),
            "scope": "Linux ru_maxrss; aggregate child maximum, not per-stage GPU memory; logical bytes exclude symlinked environment",
        }
        report["status"] = "PASSED"
        preserve()
        print(
            json.dumps(
                {
                    "workspace": str(workspace),
                    "positive_metrics": first["metrics"],
                    "negative_metrics": negative["metrics"],
                    "timing_summary": report["timing_summary"],
                },
                indent=2,
            )
        )
    except BaseException as exc:
        report["status"] = "FAILED"
        report["failure"] = f"{type(exc).__name__}: {exc}"
        preserve()
        print(f"Failure retained at {report_path}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
