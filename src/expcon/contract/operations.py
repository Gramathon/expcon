"""Contract operations: validate, freeze, diff.

These are the deterministic control operations.  They never silently repair
a frozen experiment.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from expcon.contract.contract import ExperimentContract, load_contract, validate_contract
from expcon.contract.canonical import (
    compute_contract_hash,
    compute_scientific_hash,
    compute_execution_hash,
    extract_scientific_parameters,
)
from expcon.hashing.canonical import canonical_bytes
from expcon.hashing.digest import sha256_bytes, file_sha256
from expcon.lifecycle.state import ExperimentState
from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.hashing.manifest import compute_directory_manifest
from expcon.util.path import find_workspace_root
from expcon.bundle.source import (
    SourceResolutionError,
    legacy_source_manifest,
    resolve_entrypoints,
    resolve_source_closure,
    source_manifest,
)
from expcon.runner.invocation import InvocationError, validate_invocation_spec
from expcon.util.json_io import atomic_json


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
    from expcon.util.path import safe_identifier, contained_path
    for stage in stages:
        try:
            safe_identifier(stage.get("id", ""))
        except ValueError as exc:
            issues.append(str(exc))
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
    try:
        validate_invocation_spec(contract.get("execution", "invocation", default=None))
    except InvocationError as exc:
        issues.append(str(exc))
    try:
        resolve_source_closure(experiment_dir, contract)
    except SourceResolutionError as exc:
        issues.append(str(exc))

    # Check required outputs
    required = contract.get("outputs", "required", default=[])
    if not required:
        issues.append("No required outputs declared")
    for relative in required:
        try:
            contained_path(experiment_dir, relative)
        except ValueError as exc:
            issues.append(str(exc))

    acceptance = contract.get("evaluation", "acceptance", default=None)
    if acceptance is not None:
        from expcon.adjudication.acceptance import validate_acceptance
        try:
            validate_acceptance(acceptance)
        except (ValueError, TypeError) as exc:
            issues.append(str(exc))

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


def _config_hashes(experiment_dir: Path, contract: ExperimentContract) -> dict[str, str]:
    """Return deterministic hashes for declared execution configuration files."""
    configs = contract.get("execution", "configs", default=[])
    if not configs:
        configs_dir = experiment_dir / "configs"
        if configs_dir.exists():
            configs = [str(path.relative_to(experiment_dir)) for path in configs_dir.iterdir() if path.is_file()]
    return {
        str(config): file_sha256(experiment_dir / str(config))
        for config in sorted(configs)
        if (experiment_dir / str(config)).is_file()
    }


def freeze_experiment(experiment_dir: Path | str, workspace_root: Path | str | None = None) -> dict[str, Any]:
    """Freeze an experiment: validate, resolve references, compute identities, write lock file.

    After freeze, scientific parameters are immutable.
    """
    experiment_dir = Path(experiment_dir).resolve()

    if (experiment_dir / "contract.lock.json").exists():
        raise ContractOperationError("Experiment is already frozen: retained lock cannot be replaced; create a successor")

    # Step 1: Validate
    validate_experiment(experiment_dir)

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

    # Step 4: Compute the versioned, transport-independent executable bundle
    # identity using the exact same implementation as preflight/materialize.
    from expcon.bundle.bundle import BUNDLE_IDENTITY_ALGORITHM_V2, compute_bundle_identity

    bundle_identity = compute_bundle_identity(
        experiment_dir, contract, algorithm=contract.data.get("bundle_identity_algorithm", BUNDLE_IDENTITY_ALGORITHM_V2)
    )
    discovered_source_manifest = source_manifest(experiment_dir, contract)
    source_hash = bundle_identity.source_hash
    dependency_hash = bundle_identity.dependency_hash
    dataset_hashes = bundle_identity.dataset_hashes
    runner_hash = bundle_identity.runner_hash
    bundle_id = bundle_identity.bundle_id
    config_entries = [
        {"path": path, "sha256": sha}
        for path, sha in sorted(_config_hashes(experiment_dir, contract).items())
    ]

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
            "bundle_identity_algorithm": bundle_identity.algorithm,
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
            "execution_source_hash": bundle_identity.content["execution_source_closure_sha256"],
        },
    }

    lock_path = experiment_dir / "contract.lock.json"
    try:
        atomic_json(lock_path, lock, replace=False)
    except FileExistsError as exc:
        raise ContractOperationError("Experiment is already frozen: concurrent freeze retained its lock") from exc

    # Step 11: Write source manifest
    manifests_dir = experiment_dir / "manifests"
    manifests_dir.mkdir(exist_ok=True)
    (manifests_dir / "source_manifest.json").write_text(
        json.dumps(discovered_source_manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
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

    # Invocation declarations are frozen execution identity even when they do
    # not alter the scientific hash.
    current_execution_hash = compute_execution_hash(current_contract.data)
    frozen_execution_hash = lock.get("hashes", {}).get("execution_hash")
    if frozen_execution_hash and current_execution_hash != frozen_execution_hash:
        divergences.append({
            "field": "execution",
            "frozen_hash": frozen_execution_hash,
            "current_hash": current_execution_hash,
            "message": "Execution invocation or environment has changed since freeze",
        })

    # Check the bundle-content identity with the algorithm declared in the
    # lock.  Historical locks retain their v1 source-only semantics; modern
    # locks use the full v2 executable closure.
    bundle_algorithm = lock.get("identity", {}).get("bundle_identity_algorithm")
    if bundle_algorithm:
        from expcon.bundle.bundle import compute_bundle_identity

        try:
            current_bundle = compute_bundle_identity(
                experiment_dir, current_contract, algorithm=bundle_algorithm
            )
            if current_bundle.bundle_id != lock.get("identity", {}).get("bundle_id"):
                divergences.append({
                    "field": "bundle_content",
                    "algorithm": bundle_algorithm,
                    "frozen_bundle_id": lock.get("identity", {}).get("bundle_id"),
                    "current_bundle_id": current_bundle.bundle_id,
                    "message": "Executable bundle content has changed since freeze",
                })
        except Exception as exc:
            divergences.append({
                "field": "bundle_content",
                "algorithm": bundle_algorithm,
                "message": f"Unable to recompute frozen bundle identity: {exc}",
            })
    elif lock.get("locks", {}).get("source"):
        # v1 compatibility: reproduce the historical source-only comparison.
        current_source_manifest = legacy_source_manifest(experiment_dir, current_contract)
        current_source_hash = sha256_bytes(canonical_bytes(current_source_manifest.to_dict()))
        experiment_scoped_legacy_manifest = compute_directory_manifest(
            experiment_dir, skip_hidden=True, include=["src/", "scripts/", "configs/"]
        )
        legacy_source_hash = sha256_bytes(canonical_bytes(experiment_scoped_legacy_manifest.to_dict()))
        # Pre-0.1.0 freezes scoped source discovery to experiment_dir. Preserve
        # their frozen identity while allowing the repaired bundler to package a
        # declared repository-level entrypoint.
        if current_source_hash != lock["locks"]["source"] and legacy_source_hash != lock["locks"]["source"]:
            divergences.append({
                "field": "source",
                "frozen_hash": lock["locks"]["source"],
                "current_hash": current_source_hash,
                "message": "Source tree has changed since freeze",
            })

    # Check runner hash
    if lock.get("locks", {}).get("runner"):
        runner_entries = [
            {"entrypoint": entry.declared_path, "sha256": entry.sha256}
            for entry in resolve_entrypoints(experiment_dir, current_contract)
        ]
        current_runner_hash = sha256_bytes(canonical_bytes(runner_entries))
        legacy_runner_hash = sha256_bytes(canonical_bytes([]))
        if current_runner_hash != lock["locks"]["runner"] and lock["locks"]["runner"] != legacy_runner_hash:
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
