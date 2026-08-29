"""Contract operations: validate, freeze, diff.

These are the deterministic control operations.  They never silently repair
a frozen experiment.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from expcon.contract.contract import ExperimentContract, ContractError, load_contract, validate_contract
from expcon.contract.canonical import (
    compute_contract_hash,
    compute_scientific_hash,
    compute_execution_hash,
    extract_scientific_parameters,
    contract_identity,
)
from expcon.hashing.canonical import canonical_bytes, canonical_json
from expcon.hashing.digest import sha256_bytes, file_sha256
from expcon.lifecycle.state import ExperimentState, StateError, transition
from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.hashing.manifest import compute_directory_manifest
from expcon.util.path import find_workspace_root


class ContractOperationError(Exception):
    """Raised when a contract operation fails."""


def validate_experiment(experiment_dir: Path | str) -> dict[str, Any]:
    """Validate an experiment contract structurally.

    Checks:
      - Contract file exists and is parseable
      - Contract passes JSON schema validation
      - Required output files are declared
      - Stages form a valid DAG
      - No unresolved 'latest' aliases in scientific parameters
    """
    experiment_dir = Path(experiment_dir).resolve()
    contract_path = experiment_dir / "EXPERIMENT.yaml"

    if not contract_path.exists():
        raise ContractOperationError(f"EXPERIMENT.yaml not found in {experiment_dir}")

    contract = load_contract(contract_path)
    validate_contract(contract)

    # Check for unresolved mutable aliases anywhere in scientific material.
    issues = []
    sci_params = extract_scientific_parameters(contract.data)
    aliases = {"latest", "main", "head"}
    if _contains_mutable_alias(sci_params, aliases):
        issues.append("Unresolved alias 'latest'/'main'/'HEAD' found in scientific parameters")

    # Check stage DAG
    stages = contract.get("execution", "stages", default=[])
    stage_ids = {s.get("id") for s in stages if isinstance(s, dict) and s.get("id")}
    if len(stage_ids) != len(stages):
        issues.append("Stage ids must be present and unique")
    for stage in stages:
        if isinstance(stage, dict):
            for req in stage.get("requires", []):
                if req not in stage_ids:
                    issues.append(f"Stage '{stage['id']}' requires unknown stage '{req}'")
    if _has_stage_cycle(stages):
        issues.append("Stage graph contains a cycle")

    # Check required outputs
    required = contract.get("outputs", "required", default=[])
    if not required:
        issues.append("No required outputs declared")

    acceptance = contract.get("evaluation", "acceptance", default=None)
    if acceptance is not None and not isinstance(acceptance, dict):
        issues.append("evaluation.acceptance must be an object")
    if isinstance(acceptance, dict) and acceptance and not any(
        key in acceptance for key in ("operator", "rule", "threshold", "metric")
    ):
        issues.append("evaluation.acceptance must declare a deterministic rule")

    if issues:
        raise ContractOperationError("Validation issues: " + "; ".join(issues))

    return {
        "status": "VALID",
        "experiment_id": contract.experiment_id,
        "version": contract.version,
        "contract_hash": compute_contract_hash(contract.data),
        "scientific_hash": compute_scientific_hash(contract.data),
        "execution_hash": compute_execution_hash(contract.data),
        "stages": [s["id"] for s in stages if isinstance(s, dict)],
        "required_outputs": required,
    }


def _contains_mutable_alias(value: Any, aliases: set[str]) -> bool:
    if isinstance(value, dict):
        return any(_contains_mutable_alias(item, aliases) for item in value.values())
    if isinstance(value, list):
        return any(_contains_mutable_alias(item, aliases) for item in value)
    return isinstance(value, str) and value.strip().lower() in aliases


def _has_stage_cycle(stages: list[Any]) -> bool:
    graph = {
        str(stage["id"]): [str(dep) for dep in stage.get("requires", [])]
        for stage in stages
        if isinstance(stage, dict) and stage.get("id")
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        cyclic = any(visit(dep) for dep in graph.get(node, []) if dep in graph)
        visiting.remove(node)
        visited.add(node)
        return cyclic

    return any(visit(node) for node in graph)


def freeze_experiment(experiment_dir: Path | str, workspace_root: Path | str | None = None) -> dict[str, Any]:
    """Freeze an experiment: validate, resolve references, compute identities, write lock file.

    After freeze, scientific parameters are immutable.
    """
    experiment_dir = Path(experiment_dir).resolve()

    # Step 1: Validate
    validation = validate_experiment(experiment_dir)

    # Step 2: Determine current state
    if workspace_root is None:
        workspace_root = find_workspace_root(experiment_dir.parent)

    lifecycle = ExperimentLifecycle(workspace_root)
    current_state = lifecycle.get_experiment_state(experiment_dir)

    if current_state == ExperimentState.FROZEN:
        raise ContractOperationError("Experiment is already frozen")

    if current_state == ExperimentState.DRAFT:
        # Transition DRAFT -> VALIDATED -> FROZEN
        lifecycle.set_experiment_state(experiment_dir, ExperimentState.VALIDATED, reason="Validation passed")

    # Step 3: Load contract and compute all hashes
    contract = load_contract(experiment_dir / "EXPERIMENT.yaml")
    contract_data = contract.data

    contract_hash = compute_contract_hash(contract_data)
    scientific_hash = compute_scientific_hash(contract_data)
    execution_hash = compute_execution_hash(contract_data)

    # Step 4: Compute source hash (from the experiment directory itself)
    source_root = experiment_dir
    source_manifest = compute_directory_manifest(source_root, skip_hidden=True, include=["src/", "scripts/", "configs/"])
    source_hash = sha256_bytes(canonical_bytes(source_manifest.to_dict()))

    # Step 5: Compute dependency hash
    dep_lock = contract.get("environment", "dependency_lock", default="uv.lock")
    dep_path = experiment_dir.parent / str(dep_lock)
    dependency_hash = file_sha256(dep_path) if dep_path.exists() else sha256_bytes(canonical_bytes({"missing": str(dep_lock)}))

    # Step 6: Compute dataset hashes
    dataset_hashes = {}
    datasets = contract.get("data", "datasets", default=[])
    if datasets:
        for ds in datasets:
            if isinstance(ds, dict) and "path" in ds:
                ds_path = experiment_dir / str(ds["path"])
                if ds_path.exists():
                    dataset_hashes[str(ds["path"])] = file_sha256(ds_path)

    # Step 7: Compute runner hash
    stages = contract.get("execution", "stages", default=[])
    runner_entries = []
    for stage in stages:
        if isinstance(stage, dict) and "entrypoint" in stage:
            ep_path = experiment_dir / str(stage["entrypoint"])
            if ep_path.exists():
                runner_entries.append({"entrypoint": stage["entrypoint"], "sha256": file_sha256(ep_path)})
    runner_hash = sha256_bytes(canonical_bytes(runner_entries))

    # Step 8: Compute config hash
    config_entries = []
    configs_dir = experiment_dir / "configs"
    if configs_dir.exists():
        for f in configs_dir.iterdir():
            if f.is_file():
                config_entries.append({"path": str(f.relative_to(experiment_dir)), "sha256": file_sha256(f)})
    config_hash = sha256_bytes(canonical_bytes(config_entries))

    # Step 9: Compute bundle_id
    bundle_manifest_dict = {
        "contract_hash": contract_hash,
        "scientific_hash": scientific_hash,
        "execution_hash": execution_hash,
        "source_hash": source_hash,
        "dependency_hash": dependency_hash,
        "dataset_hashes": dataset_hashes,
        "runner_hash": runner_hash,
        "config_hash": config_hash,
    }
    from expcon.bundle.bundle import bundle_id_for

    bundle_id = bundle_id_for(bundle_manifest_dict)

    # Step 10: Write contract.lock.json
    frozen_fields = _extract_frozen_fields(contract)
    lock = {
        "contract_hash": contract_hash,
        "experiment_id": contract.experiment_id,
        "version": contract.version,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "frozen_by": "expcon",
        "identity": {
            "experiment_id": contract.experiment_id,
            "version": contract.version,
            "contract_hash": contract_hash,
            "bundle_id": bundle_id,
        },
        "scientific_parameters_hash": scientific_hash,
        "locks": {
            "source": source_hash,
            "dependencies": dependency_hash,
            "datasets": dataset_hashes,
            "configs": {e["path"]: e["sha256"] for e in config_entries},
            "runner": runner_hash,
        },
        "frozen_scientific_fields": frozen_fields,
        "scientific_parameters_snapshot": extract_scientific_parameters(contract_data),
        "hashes": {
            "execution_hash": execution_hash,
        },
    }

    lock_path = experiment_dir / "contract.lock.json"
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Step 11: Write source manifest
    manifests_dir = experiment_dir / "manifests"
    manifests_dir.mkdir(exist_ok=True)
    (manifests_dir / "source_manifest.json").write_text(
        json.dumps(source_manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Step 12: Transition to FROZEN
    lifecycle.set_experiment_state(experiment_dir, ExperimentState.FROZEN, reason="Contract frozen with lock file")

    return {
        "status": "FROZEN",
        "experiment_id": contract.experiment_id,
        "version": contract.version,
        "contract_hash": contract_hash,
        "scientific_hash": scientific_hash,
        "bundle_id": bundle_id,
        "lock_file": str(lock_path),
    }


def _extract_frozen_fields(contract: ExperimentContract) -> list[str]:
    """Extract the list of scientific fields that are frozen."""
    frozen = [
        "experiment.id",
        "experiment.version",
        "hypothesis.statement",
        "hypothesis.scientific_fingerprint",
        "data",
        "evaluation",
        "outputs",
        "reproducibility",
        "scientific_parameters",
    ]
    return frozen


def diff_experiment(experiment_dir: Path | str) -> dict[str, Any]:
    """Detect scientifically meaningful divergence between frozen contract and current source.

    Returns a diff report.  If the experiment is not frozen, returns a notice.
    """
    experiment_dir = Path(experiment_dir).resolve()
    contract_path = experiment_dir / "EXPERIMENT.yaml"
    lock_path = experiment_dir / "contract.lock.json"

    if not contract_path.exists():
        raise ContractOperationError(f"EXPERIMENT.yaml not found in {experiment_dir}")

    if not lock_path.exists():
        return {
            "status": "NOT_FROZEN",
            "message": "Experiment is not frozen. No diff to compute.",
            "divergence_detected": False,
        }

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    current_contract = load_contract(contract_path)
    current_hash = compute_contract_hash(current_contract.data)
    current_sci_hash = compute_scientific_hash(current_contract.data)

    frozen_contract_hash = lock["contract_hash"]
    frozen_sci_hash = lock["scientific_parameters_hash"]

    divergences = []

    # Check scientific hash
    if current_sci_hash != frozen_sci_hash:
        # Deep diff scientific parameters
        frozen_sci = extract_scientific_parameters_from_lock(lock)
        current_sci = extract_scientific_parameters(current_contract.data)
        divergences.extend(_deep_diff("scientific_parameters", frozen_sci, current_sci))

    # Check source hash
    if lock.get("locks", {}).get("source"):
        source_root = experiment_dir
        current_source_manifest = compute_directory_manifest(source_root, skip_hidden=True, include=["src/", "scripts/", "configs/"])
        current_source_hash = sha256_bytes(canonical_bytes(current_source_manifest.to_dict()))
        # If no source files exist, the hash will be the same as frozen (empty manifest)
        if current_source_hash != lock["locks"]["source"]:
            divergences.append({
                "field": "source",
                "frozen_hash": lock["locks"]["source"],
                "current_hash": current_source_hash,
                "message": "Source tree has changed since freeze",
            })

    # Check runner hash
    if lock.get("locks", {}).get("runner"):
        stages = current_contract.get("execution", "stages", default=[])
        runner_entries = []
        for stage in stages:
            if isinstance(stage, dict) and "entrypoint" in stage:
                ep_path = experiment_dir / str(stage["entrypoint"])
                if ep_path.exists():
                    runner_entries.append({"entrypoint": stage["entrypoint"], "sha256": file_sha256(ep_path)})
        current_runner_hash = sha256_bytes(canonical_bytes(runner_entries))
        if current_runner_hash != lock["locks"]["runner"]:
            divergences.append({
                "field": "runner",
                "frozen_hash": lock["locks"]["runner"],
                "current_hash": current_runner_hash,
                "message": "Runner code has changed since freeze",
            })

    # Check config hashes
    config_lock = lock.get("locks", {}).get("configs", {})
    configs_dir = experiment_dir / "configs"
    if configs_dir.exists():
        for f in configs_dir.iterdir():
            if f.is_file():
                rel = str(f.relative_to(experiment_dir))
                current_sha = file_sha256(f)
                if rel in config_lock and current_sha != config_lock[rel]:
                    divergences.append({
                        "field": f"configs/{rel}",
                        "frozen_sha256": config_lock[rel],
                        "current_sha256": current_sha,
                        "message": "Config file has changed since freeze",
                    })

    return {
        "status": "DIVERGENCE_DETECTED" if divergences else "NO_DIVERGENCE",
        "experiment_id": current_contract.experiment_id,
        "version": current_contract.version,
        "frozen_contract_hash": frozen_contract_hash,
        "current_contract_hash": current_hash,
        "frozen_scientific_hash": frozen_sci_hash,
        "current_scientific_hash": current_sci_hash,
        "divergence_detected": len(divergences) > 0,
        "divergences": divergences,
    }


def extract_scientific_parameters_from_lock(lock: dict[str, Any]) -> dict[str, Any]:
    """Extract scientific parameters snapshot from a lock file."""
    return lock.get("scientific_parameters_snapshot", {})


def _deep_diff(path: str, frozen: Any, current: Any) -> list[dict[str, Any]]:
    """Produce a list of divergence entries between two values."""
    divergences = []

    if isinstance(frozen, dict) and isinstance(current, dict):
        all_keys = sorted(set(frozen.keys()) | set(current.keys()))
        for key in all_keys:
            sub_path = f"{path}.{key}"
            if key not in frozen:
                divergences.append({
                    "field": sub_path,
                    "frozen_value": None,
                    "current_value": current[key],
                    "message": "Field added after freeze",
                })
            elif key not in current:
                divergences.append({
                    "field": sub_path,
                    "frozen_value": frozen[key],
                    "current_value": None,
                    "message": "Field removed after freeze",
                })
            elif frozen[key] != current[key]:
                if isinstance(frozen[key], (dict, list)) and isinstance(current[key], (dict, list)):
                    divergences.extend(_deep_diff(sub_path, frozen[key], current[key]))
                else:
                    divergences.append({
                        "field": sub_path,
                        "frozen_value": frozen[key],
                        "current_value": current[key],
                        "message": "Value changed after freeze",
                    })
    elif frozen != current:
        divergences.append({
            "field": path,
            "frozen_value": frozen,
            "current_value": current,
            "message": "Value changed after freeze",
        })

    return divergences
