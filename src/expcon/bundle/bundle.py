"""Bundle creation, manifest, and verification.

A bundle is a content-addressed package.  Its identity (bundle_id) is
derived from a canonical manifest of:
  - contract hash
  - source hash
  - dependency hash
  - dataset hashes
  - runner hash

Any protected modification of bundle contents fails verification.
"""

from __future__ import annotations

import json
import ast
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from expcon.contract.contract import ExperimentContract, load_contract
from expcon.contract.canonical import (
    compute_contract_hash,
    compute_scientific_hash,
    compute_execution_hash,
    compute_execution_identity_hash_v2,
)
from expcon.hashing.canonical import canonical_bytes
from expcon.hashing.digest import sha256_bytes, file_sha256
from expcon.bundle.source import (
    canonical_source_manifest,
    legacy_source_manifest,
    repository_root,
    resolve_entrypoints,
    resolve_source_closure,
    source_manifest,
)
from expcon.runner.invocation import resolve_invocation
from expcon.util.path import contained_path


class BundleError(Exception):
    """Raised when bundle creation or verification fails."""


BUNDLE_IDENTITY_ALGORITHM_V1 = "expcon-bundle-v1"
BUNDLE_IDENTITY_ALGORITHM_V2 = "expcon-bundle-v2"
BUNDLE_IDENTITY_ALGORITHM_V3 = "expcon-bundle-v3"


@dataclass(frozen=True)
class BundleIdentity:
    """A transport-independent identity for executable bundle content."""

    algorithm: str
    bundle_id: str
    source_hash: str
    dependency_hash: str
    dataset_hashes: dict[str, str]
    runner_hash: str
    config_hash: str
    content: dict[str, Any]


def _legacy_bundle_content(*, contract_hash: str, scientific_hash: str,
                           execution_hash: str, source_hash: str,
                           dependency_hash: str, dataset_hashes: dict[str, str],
                           runner_hash: str, config_hash: str) -> dict[str, Any]:
    """The frozen v1 bundle identity representation (kept for inspection)."""
    return {
        "contract_hash": contract_hash,
        "scientific_hash": scientific_hash,
        "execution_hash": execution_hash,
        "source_hash": source_hash,
        "dependency_hash": dependency_hash,
        "dataset_hashes": dataset_hashes,
        "runner_hash": runner_hash,
        "config_hash": config_hash,
    }


def bundle_id_for(manifest: dict[str, Any]) -> str:
    """Compute a bundle identity using the manifest's declared algorithm.

    v1 is deliberately retained byte-for-byte for historical locks.  v2 is a
    complete, transport-independent executable-content representation.
    """
    algorithm = manifest.get("bundle_identity_algorithm", BUNDLE_IDENTITY_ALGORITHM_V1)
    if algorithm == BUNDLE_IDENTITY_ALGORITHM_V1:
        protected = _legacy_bundle_content(
            contract_hash=manifest["contract_hash"],
            scientific_hash=manifest["scientific_hash"],
            execution_hash=manifest["execution_hash"],
            source_hash=manifest["source_hash"],
            dependency_hash=manifest["dependency_hash"],
            dataset_hashes=manifest["dataset_hashes"],
            runner_hash=manifest["runner_hash"],
            config_hash=manifest["config_hash"],
        )
        return sha256_bytes(canonical_bytes(protected))
    if algorithm in {BUNDLE_IDENTITY_ALGORITHM_V2, BUNDLE_IDENTITY_ALGORITHM_V3}:
        content = manifest.get("bundle_content")
        if not isinstance(content, dict):
            raise BundleError("expcon-bundle-v2 manifest requires bundle_content")
        return sha256_bytes(canonical_bytes({"algorithm": algorithm, "content": content}))
    raise BundleError(f"Unsupported bundle identity algorithm: {algorithm}")


@dataclass
class BundleManifest:
    """The canonical manifest for a bundle."""

    bundle_id: str
    contract_hash: str
    scientific_hash: str
    execution_hash: str
    source_hash: str
    dependency_hash: str
    dataset_hashes: dict[str, str]
    runner_hash: str
    config_hash: str
    files: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "contract_hash": self.contract_hash,
            "scientific_hash": self.scientific_hash,
            "execution_hash": self.execution_hash,
            "source_hash": self.source_hash,
            "dependency_hash": self.dependency_hash,
            "dataset_hashes": self.dataset_hashes,
            "runner_hash": self.runner_hash,
            "config_hash": self.config_hash,
            "files": self.files,
            "created_at": self.created_at,
        }


def _dependency_hash(experiment_dir: Path, contract: ExperimentContract) -> str:
    if contract.data.get("bundle_identity_algorithm") == BUNDLE_IDENTITY_ALGORITHM_V3 and contract.get("environment", "dependency_lock") is not None:
        return file_sha256(_declared_dependency_path(experiment_dir, contract))
    lock_file = contract.get("environment", "dependency_lock", default="uv.lock")
    lock_path = experiment_dir / str(lock_file)
    if not lock_path.exists():
        lock_path = experiment_dir.parent / str(lock_file)
    if lock_path.exists():
        return file_sha256(lock_path)
    return sha256_bytes(canonical_bytes({"missing": str(lock_file)}))


def _declared_dependency_path(experiment_dir: Path, contract: ExperimentContract) -> Path:
    spec = contract.get("environment", "dependency_lock")
    relative = spec.get("path") if isinstance(spec, dict) else spec
    if not isinstance(relative, str):
        raise BundleError("Dependency lock requires a relative path")
    path = contained_path(repository_root(experiment_dir, contract), relative)
    if not path.is_file():
        raise BundleError("Declared dependency lock is missing")
    return path


def _dataset_hashes(experiment_dir: Path, contract: ExperimentContract) -> dict[str, str]:
    result: dict[str, str] = {}
    for dataset in contract.get("data", "datasets", default=[]):
        if isinstance(dataset, dict) and "path" in dataset:
            path = experiment_dir / str(dataset["path"])
            result[str(dataset["path"])] = (
                file_sha256(path) if path.exists()
                else sha256_bytes(canonical_bytes({"missing": str(dataset["path"])}))
            )
    return result


def _runner_hash(experiment_dir: Path, contract: ExperimentContract) -> tuple[str, list[dict[str, str]]]:
    entries = [
        {"entrypoint": entry.declared_path, "sha256": entry.sha256}
        for entry in resolve_entrypoints(experiment_dir, contract)
    ]
    if not entries:
        return sha256_bytes(canonical_bytes({"no_stages": True})), entries
    return sha256_bytes(canonical_bytes(entries)), entries


def _config_hash(experiment_dir: Path, contract: ExperimentContract) -> str:
    configs = contract.get("execution", "configs", default=[])
    if not configs:
        configs_dir = experiment_dir / "configs"
        if configs_dir.exists():
            configs = [str(path.relative_to(experiment_dir)) for path in configs_dir.iterdir() if path.is_file()]
    entries = []
    for config in configs:
        path = experiment_dir / str(config)
        if path.exists():
            entries.append({"path": str(config), "sha256": file_sha256(path)})
    return sha256_bytes(canonical_bytes(sorted(entries, key=lambda entry: entry["path"])))


def _config_entries(experiment_dir: Path, contract: ExperimentContract) -> dict[str, str]:
    declared = contract.get("execution", "configs", default=[])
    if not declared and (experiment_dir / "configs").exists():
        declared = [str(p.relative_to(experiment_dir)) for p in sorted((experiment_dir / "configs").rglob("*")) if p.is_file()]
    return {relative: file_sha256(contained_path(experiment_dir, relative)) for relative in sorted(declared)}


def compute_bundle_identity(
    experiment_dir: Path | str,
    contract: ExperimentContract,
    *,
    algorithm: str | None = None,
) -> BundleIdentity:
    """Compute one canonical identity for a candidate executable bundle.

    The v2 representation contains only frozen executable semantics and byte
    identities.  Absolute checkout roots, temporary bundle directories,
    provider mounts, output roots, and timestamps are intentionally absent.
    """
    experiment_dir = Path(experiment_dir).resolve()
    contract_data = contract.data
    algorithm = algorithm or contract_data.get("bundle_identity_algorithm", BUNDLE_IDENTITY_ALGORITHM_V2)
    repository_manifest = source_manifest(experiment_dir, contract)
    closure = resolve_source_closure(experiment_dir, contract)
    source_provenance = canonical_source_manifest(repository_manifest)
    source_hash = sha256_bytes(canonical_bytes(source_provenance))
    dependency_hash = _dependency_hash(experiment_dir, contract)
    dataset_hashes = _dataset_hashes(experiment_dir, contract)
    runner_hash, entrypoints = _runner_hash(experiment_dir, contract)
    config_hash = _config_hash(experiment_dir, contract)
    contract_hash = compute_contract_hash(contract_data)
    scientific_hash = compute_scientific_hash(contract_data)
    execution_hash = compute_execution_hash(contract_data)

    if algorithm == BUNDLE_IDENTITY_ALGORITHM_V1:
        # v1 used the absolute-root diagnostic manifest as its source field.
        legacy_manifest = legacy_source_manifest(experiment_dir, contract)
        legacy_source_hash = sha256_bytes(canonical_bytes(legacy_manifest.to_dict()))
        content = _legacy_bundle_content(
            contract_hash=contract_hash, scientific_hash=scientific_hash,
            execution_hash=execution_hash, source_hash=legacy_source_hash,
            dependency_hash=dependency_hash, dataset_hashes=dataset_hashes,
            runner_hash=runner_hash, config_hash=config_hash,
        )
        return BundleIdentity(
            algorithm=algorithm, bundle_id=sha256_bytes(canonical_bytes(content)),
            source_hash=legacy_source_hash, dependency_hash=dependency_hash,
            dataset_hashes=dataset_hashes, runner_hash=runner_hash,
            config_hash=config_hash, content=content,
        )
    if algorithm not in {BUNDLE_IDENTITY_ALGORITHM_V2, BUNDLE_IDENTITY_ALGORITHM_V3}:
        raise BundleError(f"Unsupported bundle identity algorithm: {algorithm}")

    content = {
        "contract_hash": contract_hash,
        "scientific_hash": scientific_hash,
        "execution_hash": execution_hash,
        "repository_source_manifest": source_provenance,
        "repository_source_manifest_sha256": source_hash,
        "execution_source_closure": closure.to_dict(),
        "execution_source_closure_sha256": closure.sha256,
        "entrypoints": entrypoints,
        "runner_hash": runner_hash,
        "invocation": contract_data.get("execution", {}).get("invocation"),
        "dependency_hash": dependency_hash,
        "dataset_hashes": dataset_hashes,
        "config_hash": config_hash,
    }
    if algorithm == BUNDLE_IDENTITY_ALGORITHM_V3:
        payload = {}
        for entry in resolve_entrypoints(experiment_dir, contract):
            payload[entry.bundle_relative_path.as_posix()] = entry.sha256
            if entry.source_path.suffix == ".ipynb":
                metadata = entry.source_path.parent / "kernel-metadata.json"
                payload[(entry.bundle_relative_path.parent / metadata.name).as_posix()] = file_sha256(metadata)
        for source_entry in closure.entries:
            payload[source_entry.bundle_relative_path.as_posix()] = source_entry.sha256
        for relative, digest in _config_entries(experiment_dir, contract).items():
            payload[(Path("configs") / relative).as_posix()] = digest
        content["payload_files"] = payload
        if contract.get("environment", "dependency_lock") is not None:
            payload["dependency.lock"] = file_sha256(_declared_dependency_path(experiment_dir, contract))
    return BundleIdentity(
        algorithm=algorithm,
        bundle_id=sha256_bytes(canonical_bytes({"algorithm": algorithm, "content": content})),
        source_hash=source_hash, dependency_hash=dependency_hash,
        dataset_hashes=dataset_hashes, runner_hash=runner_hash,
        config_hash=config_hash, content=content,
    )


def verify_frozen_bundle_compatibility(
    experiment_dir: Path | str,
    contract: ExperimentContract,
    lock: dict[str, Any],
) -> dict[str, Any]:
    """Verify a frozen lock against its declared bundle-identity algorithm.

    A v1 lock is never reinterpreted as v2.  If it independently locks every
    v2-only execution component, this returns an explicit compatibility
    attestation containing *both* identities.  Otherwise execution must fail
    closed rather than equating the two algorithms.
    """
    algorithm = lock.get("identity", {}).get(
        "bundle_identity_algorithm", BUNDLE_IDENTITY_ALGORITHM_V1
    )
    frozen_bundle_id = lock.get("identity", {}).get("bundle_id")
    if algorithm in {BUNDLE_IDENTITY_ALGORITHM_V2, BUNDLE_IDENTITY_ALGORITHM_V3}:
        current = compute_bundle_identity(experiment_dir, contract, algorithm=algorithm)
        return {
            "status": "PASS" if current.bundle_id == frozen_bundle_id else "FAIL",
            "algorithm": algorithm,
            "frozen_bundle_id": frozen_bundle_id,
            "materialized_bundle_id": current.bundle_id,
            "cryptographically_complete": current.bundle_id == frozen_bundle_id,
        }
    if algorithm != BUNDLE_IDENTITY_ALGORITHM_V1:
        return {"status": "FAIL", "algorithm": algorithm, "error": "Unsupported frozen bundle algorithm"}

    legacy = compute_bundle_identity(experiment_dir, contract, algorithm=algorithm)
    modern = compute_bundle_identity(experiment_dir, contract, algorithm=BUNDLE_IDENTITY_ALGORITHM_V2)
    source_spec = contract.get("execution", "source", default={})
    invocation = contract.get("execution", "invocation", default=None)
    closure_declared = isinstance(source_spec, dict) and bool(source_spec.get("expected_sha256"))
    closure_matches = closure_declared and source_spec.get("expected_sha256") == modern.content["execution_source_closure_sha256"]
    complete = (
        legacy.bundle_id == frozen_bundle_id
        and compute_contract_hash(contract.data) == lock.get("contract_hash")
        and lock.get("locks", {}).get("runner") == modern.runner_hash
        and closure_matches
        and invocation is not None
    )
    return {
        "status": "PASS" if complete else "FAIL",
        "algorithm": algorithm,
        "frozen_bundle_id": frozen_bundle_id,
        "materialized_bundle_id": modern.bundle_id,
        "legacy_bundle_id_verified": legacy.bundle_id == frozen_bundle_id,
        "contract_hash_verified": compute_contract_hash(contract.data) == lock.get("contract_hash"),
        "runner_verified": lock.get("locks", {}).get("runner") == modern.runner_hash,
        "execution_source_closure_verified": closure_matches,
        "invocation_declared": invocation is not None,
        "cryptographically_complete": complete,
    }


class BundleBuilder:
    """Builds a content-addressed bundle for an experiment."""

    def __init__(self, experiment_dir: Path | str):
        self.experiment_dir = Path(experiment_dir).resolve()
        self.bundle_dir = self.experiment_dir / "bundle"

    def build(self) -> tuple[Path, str]:
        """Build the bundle and return (bundle_path, bundle_id)."""

        return self._build(require_frozen=True)

    def preflight(
        self, *, input_bindings: dict[str, str] | None = None, environment_bindings: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Verify an ephemeral candidate bundle without a run or lifecycle change."""
        contract_data = load_contract(self.experiment_dir / "EXPERIMENT.yaml").data
        with tempfile.TemporaryDirectory(prefix="expcon-preflight-") as temporary:
            original = self.bundle_dir
            self.bundle_dir = Path(temporary) / "bundle"
            try:
                bundle_path, bundle_id = self._build(require_frozen=False)
                verification = BundleVerifier(bundle_path).verify()
                closure = json.loads((bundle_path / "execution_source_manifest.json").read_text(encoding="utf-8"))
                self._static_python_import_check(bundle_path, closure, repository_root(self.experiment_dir, load_contract(self.experiment_dir / "EXPERIMENT.yaml")))
                invocation = resolve_invocation(
                    contract_data.get("execution", {}).get("invocation"),
                    bundle_root=bundle_path,
                    output_root=bundle_path / "candidate-output",
                    input_bindings=input_bindings or {},
                    environment_bindings=environment_bindings or {},
                )
                return {
                    "status": "PASS" if verification["status"] == "PASS" else "FAIL",
                    "bundle_id": bundle_id,
                    "verification": verification,
                    "entrypoint": closure["entrypoint"],
                    "execution_source_sha256": sha256_bytes(canonical_bytes(closure)),
                    "execution_identity_sha256": compute_execution_identity_hash_v2(
                        contract_data, runner_sha256=closure["entrypoint"]["sha256"],
                        execution_source_sha256=sha256_bytes(canonical_bytes(closure)),
                    ),
                    "source_file_count": len(closure["files"]),
                    "invocation": invocation.attestation,
                    "ephemeral": True,
                }
            finally:
                self.bundle_dir = original

    @staticmethod
    def _static_python_import_check(bundle_path: Path, closure: dict[str, Any], repository_root: Path) -> None:
        """Detect unbundled local imports without importing or executing code."""
        script = bundle_path / closure["entrypoint"]["bundle_relative_path"]
        try:
            tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        except SyntaxError as exc:
            raise BundleError(f"Entrypoint syntax check failed: {exc}") from exc
        roots = {entry["repository_relative_path"].split("/")[1]
                 for entry in closure["files"]
                 if entry["repository_relative_path"].startswith("src/") and "/" in entry["repository_relative_path"]}
        local_roots = {path.name for path in (repository_root / "src").iterdir()} if (repository_root / "src").is_dir() else set()
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        missing = sorted(root for root in imported & local_roots if root not in roots or not (bundle_path / "source" / root).exists())
        if missing:
            raise BundleError(f"Entrypoint imports repository package(s) absent from declared execution.source.include: {missing}")

    def _build(self, *, require_frozen: bool) -> tuple[Path, str]:
        from datetime import datetime, timezone

        contract = load_contract(self.experiment_dir / "EXPERIMENT.yaml")
        contract_data = contract.data
        lock_path = self.experiment_dir / "contract.lock.json"
        if require_frozen and not lock_path.exists():
            raise BundleError("Experiment must be frozen before it can be bundled")

        identity = compute_bundle_identity(self.experiment_dir, contract)
        contract_hash = compute_contract_hash(contract_data)
        scientific_hash = compute_scientific_hash(contract_data)
        execution_hash = compute_execution_hash(contract_data)
        discovered_source_manifest = source_manifest(self.experiment_dir, contract)
        closure = resolve_source_closure(self.experiment_dir, contract)

        manifest_dict: dict[str, Any] = {
            "bundle_id": "",
            "bundle_identity_algorithm": identity.algorithm,
            "bundle_content": identity.content,
            "contract_hash": contract_hash,
            "scientific_hash": scientific_hash,
            "execution_hash": execution_hash,
            "source_hash": identity.source_hash,
            "dependency_hash": identity.dependency_hash,
            "dataset_hashes": identity.dataset_hashes,
            "runner_hash": identity.runner_hash,
            "config_hash": identity.config_hash,
            "files": [],
        }
        bundle_id = identity.bundle_id

        legacy_compatibility = None
        if require_frozen:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_algorithm = lock.get("identity", {}).get(
                "bundle_identity_algorithm", BUNDLE_IDENTITY_ALGORITHM_V1
            )
            if lock_algorithm in {BUNDLE_IDENTITY_ALGORITHM_V2, BUNDLE_IDENTITY_ALGORITHM_V3} and lock.get("identity", {}).get("bundle_id") != bundle_id:
                raise BundleError("Frozen v2 bundle content identity diverged; execution is refused")
            if lock_algorithm == BUNDLE_IDENTITY_ALGORITHM_V1:
                legacy_compatibility = verify_frozen_bundle_compatibility(
                    self.experiment_dir, contract, lock
                )
                if legacy_compatibility["status"] != "PASS":
                    raise BundleError("Frozen v1 bundle cannot be cryptographically verified under compatibility")

        # Create bundle directory
        if self.bundle_dir.exists():
            shutil.rmtree(self.bundle_dir)
        self.bundle_dir.mkdir(parents=True)

        # The freeze record is protected bundle input, never regenerated by a
        # backend.  It permits a verifier to bind execution to the frozen
        # identity rather than to mutable YAML.
        if lock_path.exists():
            shutil.copy2(lock_path, self.bundle_dir / "contract.lock.json")

        # Copy resolved contract
        resolved_contract = self.bundle_dir / "resolved_contract.json"
        resolved_contract.write_text(
            json.dumps(contract_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Copy source manifest
        source_manifest_file = self.bundle_dir / "source_manifest.json"
        source_manifest_file.write_text(
            json.dumps(canonical_source_manifest(discovered_source_manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (self.bundle_dir / "execution_source_manifest.json").write_text(
            json.dumps(closure.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Copy configs
        configs_dir = self.bundle_dir / "configs"
        configs_dir.mkdir(exist_ok=True)
        self._copy_configs(contract, configs_dir)

        # Copy runner
        runner_dir = self.bundle_dir / "runner"
        runner_dir.mkdir(exist_ok=True)
        self._copy_runner(contract, runner_dir)
        self._copy_source_closure(closure)
        if identity.algorithm == BUNDLE_IDENTITY_ALGORITHM_V3 and contract.get("environment", "dependency_lock") is not None:
            shutil.copy2(_declared_dependency_path(self.experiment_dir, contract), self.bundle_dir / "dependency.lock")

        # Write bundle manifest
        manifest_dict["files"] = self._collect_file_hashes()
        manifest_dict["bundle_id"] = bundle_id
        manifest_dict["created_at"] = datetime.now(timezone.utc).isoformat()
        if legacy_compatibility is not None:
            manifest_dict["legacy_compatibility"] = legacy_compatibility

        manifest_file = self.bundle_dir / "bundle_manifest.json"
        manifest_file.write_text(
            json.dumps(manifest_dict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Write hashes.json
        hashes_file = self.bundle_dir / "hashes.json"
        hashes_file.write_text(
            json.dumps(
                {
                    "bundle_id": bundle_id,
                    "contract_hash": contract_hash,
                    "scientific_hash": scientific_hash,
                    "execution_hash": execution_hash,
                    "bundle_identity_algorithm": identity.algorithm,
                    "source_hash": identity.source_hash,
                    "dependency_hash": identity.dependency_hash,
                    "config_hash": identity.config_hash,
                    "runner_hash": identity.runner_hash,
                    "dataset_hashes": identity.dataset_hashes,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        return self.bundle_dir, bundle_id

    def _compute_dependency_hash(self, contract: ExperimentContract) -> str:
        lock_file = contract.get("environment", "dependency_lock", default="uv.lock")
        lock_path = self.experiment_dir / str(lock_file)
        if not lock_path.exists():
            lock_path = self.experiment_dir.parent / str(lock_file)
        if lock_path.exists():
            return file_sha256(lock_path)
        return sha256_bytes(canonical_bytes({"missing": str(lock_file)}))

    def _compute_dataset_hashes(self, contract: ExperimentContract) -> dict[str, str]:
        result = {}
        datasets = contract.get("data", "datasets", default=[])
        if datasets:
            for ds in datasets:
                if isinstance(ds, dict) and "path" in ds:
                    ds_path = self.experiment_dir / str(ds["path"])
                    if ds_path.exists():
                        result[str(ds["path"])] = file_sha256(ds_path)
                    else:
                        result[str(ds["path"])] = sha256_bytes(canonical_bytes({"missing": str(ds["path"])}))
        return result

    def _compute_runner_hash(self, contract: ExperimentContract) -> str:
        entries = resolve_entrypoints(self.experiment_dir, contract)
        if entries:
            return sha256_bytes(canonical_bytes([
                {"entrypoint": entry.declared_path, "sha256": entry.sha256} for entry in entries
            ]))
        return sha256_bytes(canonical_bytes({"no_stages": True}))

    def _compute_config_hash(self, contract: ExperimentContract) -> str:
        configs = contract.get("execution", "configs", default=[])
        if not configs:
            # Try to find config files in a configs directory
            configs_dir = self.experiment_dir / "configs"
            if configs_dir.exists():
                configs = [str(p.relative_to(self.experiment_dir)) for p in configs_dir.iterdir() if p.is_file()]

        entries = []
        for cfg in configs:
            cfg_path = self.experiment_dir / str(cfg)
            if cfg_path.exists():
                entries.append({"path": cfg, "sha256": file_sha256(cfg_path)})
        return sha256_bytes(canonical_bytes(entries))

    def _copy_configs(self, contract: ExperimentContract, dest: Path) -> None:
        if contract.data.get("bundle_identity_algorithm") == BUNDLE_IDENTITY_ALGORITHM_V3:
            for relative in _config_entries(self.experiment_dir, contract):
                target = contained_path(dest, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(contained_path(self.experiment_dir, relative), target)
            return
        configs_dir = self.experiment_dir / "configs"
        if configs_dir.exists():
            for f in configs_dir.iterdir():
                if f.is_file():
                    shutil.copy2(f, dest / f.name)

    def _copy_runner(self, contract: ExperimentContract, dest: Path) -> None:
        for entry in resolve_entrypoints(self.experiment_dir, contract):
            target = self.bundle_dir / entry.bundle_relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry.source_path, target)
            # Kaggle notebooks execute with adjacent metadata.  Treat that
            # metadata as immutable transport payload, not as a generated
            # backend default.  It is included in the bundle file manifest.
            if entry.source_path.suffix == ".ipynb":
                metadata = entry.source_path.parent / "kernel-metadata.json"
                if not metadata.is_file():
                    raise BundleError(f"Kaggle notebook entrypoint lacks kernel-metadata.json: {entry.declared_path}")
                shutil.copy2(metadata, target.parent / "kernel-metadata.json")

    def _copy_source_closure(self, closure) -> None:
        for entry in closure.entries:
            target = self.bundle_dir / entry.bundle_relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry.source_path, target)

    def _collect_file_hashes(self) -> list[dict[str, Any]]:
        files = []
        for path in sorted(self.bundle_dir.rglob("*")):
            if path.is_file():
                files.append(
                    {
                        "relative_path": str(path.relative_to(self.bundle_dir)),
                        "size_bytes": path.stat().st_size,
                        "sha256": file_sha256(path),
                    }
                )
        return files


class BundleVerifier:
    """Verifies bundle integrity against its manifest."""

    def __init__(self, bundle_path: Path | str, expected_bundle_id: str | None = None):
        self.bundle_path = Path(bundle_path).resolve()
        self.manifest_path = self.bundle_path / "bundle_manifest.json"
        self.expected_bundle_id = expected_bundle_id

    def verify(self) -> dict[str, Any]:
        errors: list[str] = []
        manifest: dict[str, Any] = {}
        try:
            manifest = json.loads(self.manifest_path.read_text())
            self._verify_content(manifest, errors)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append(f"INVALID_BUNDLE: {exc}")
        if not isinstance(manifest, dict):
            manifest = {}
        files = manifest.get("files", [])
        return {"status": "FAIL" if errors else "PASS", "errors": errors,
                "bundle_id": manifest.get("bundle_id"), "file_count": len(files) if isinstance(files, list) else 0,
                "trusted_identity": self.expected_bundle_id is not None and not errors}

    def _verify_content(self, manifest: dict[str, Any], errors: list[str]) -> None:
        if self.expected_bundle_id is not None and manifest.get("bundle_id") != self.expected_bundle_id:
            errors.append("EXPECTED_BUNDLE_ID_MISMATCH")
        if bundle_id_for(manifest) != manifest.get("bundle_id"):
            errors.append("BUNDLE_ID_MISMATCH")
        listed: set[str] = set()
        for entry in manifest["files"]:
            relative = entry["relative_path"]
            path = contained_path(self.bundle_path, relative)
            if relative in listed:
                errors.append(f"DUPLICATE_FILE: {relative}")
            listed.add(relative)
            if not path.is_file():
                errors.append(f"MISSING: {relative}")
            elif path.stat().st_size != entry["size_bytes"] or file_sha256(path) != entry["sha256"]:
                errors.append(f"HASH_MISMATCH: {relative}")
        for path in self.bundle_path.rglob("*"):
            if path.is_symlink():
                contained_path(self.bundle_path, path.relative_to(self.bundle_path).as_posix())
            if path.is_file():
                relative = path.relative_to(self.bundle_path).as_posix()
                if relative not in listed | {"bundle_manifest.json", "hashes.json"}:
                    errors.append(f"EXTRA_FILE: {relative}")
        contract = json.loads((self.bundle_path / "resolved_contract.json").read_text())
        if compute_contract_hash(contract) != manifest["contract_hash"]:
            errors.append("CONTRACT_HASH_MISMATCH")
        algorithm = manifest.get("bundle_identity_algorithm", BUNDLE_IDENTITY_ALGORITHM_V1)
        if algorithm == BUNDLE_IDENTITY_ALGORITHM_V1:
            # Retain historical interpretation; no stronger execution assurance inferred.
            if self.expected_bundle_id is not None:
                errors.append("LEGACY_BUNDLE_REQUIRES_EXPLICIT_COMPATIBILITY")
            return
        content = manifest["bundle_content"]
        for key in ("contract_hash", "scientific_hash", "execution_hash", "runner_hash",
                    "dependency_hash", "dataset_hashes", "config_hash"):
            if content[key] != manifest[key]:
                errors.append(f"IDENTITY_FIELD_MISMATCH: {key}")
        if content["contract_hash"] != compute_contract_hash(contract):
            errors.append("EXECUTABLE_CONTRACT_MISMATCH")
        entries = []
        for entry in content["entrypoints"]:
            path = contained_path(self.bundle_path / "runner", entry["entrypoint"])
            digest = file_sha256(path)
            entries.append({"entrypoint": entry["entrypoint"], "sha256": digest})
            if digest != entry["sha256"]:
                errors.append(f"EXECUTABLE_HASH_MISMATCH: {entry['entrypoint']}")
        if sha256_bytes(canonical_bytes(entries)) != content["runner_hash"]:
            errors.append("EXECUTABLE_RUNNER_IDENTITY_MISMATCH")
        closure = content["execution_source_closure"]
        if sha256_bytes(canonical_bytes(closure)) != content["execution_source_closure_sha256"]:
            errors.append("EXECUTABLE_SOURCE_IDENTITY_MISMATCH")
        for entry in closure["files"]:
            path = contained_path(self.bundle_path, entry["bundle_relative_path"])
            if file_sha256(path) != entry["sha256"] or path.stat().st_size != entry["size_bytes"]:
                errors.append(f"EXECUTABLE_SOURCE_HASH_MISMATCH: {entry['bundle_relative_path']}")
        source = json.loads((self.bundle_path / "source_manifest.json").read_text())
        if source != content["repository_source_manifest"] or sha256_bytes(canonical_bytes(source)) != content["repository_source_manifest_sha256"]:
            errors.append("EXECUTABLE_PROVENANCE_MISMATCH")
        materialized_closure = json.loads((self.bundle_path / "execution_source_manifest.json").read_text())
        if materialized_closure != closure:
            errors.append("EXECUTABLE_CLOSURE_MISMATCH")
        expected_executables = {str(Path("runner") / item["entrypoint"]) for item in content["entrypoints"]}
        expected_executables.update(item["bundle_relative_path"] for item in closure["files"])
        actual_executables = {p.relative_to(self.bundle_path).as_posix()
                              for directory in ("runner", "source")
                              for p in (self.bundle_path / directory).rglob("*") if p.is_file()}
        if algorithm == BUNDLE_IDENTITY_ALGORITHM_V2 and not any(str(s.get("entrypoint", "")).endswith(".ipynb") for s in contract.get("execution", {}).get("stages", [])) and actual_executables != expected_executables:
            errors.append("EXECUTABLE_UNDECLARED_PAYLOAD")
        if algorithm == BUNDLE_IDENTITY_ALGORITHM_V3:
            actual_payload = {p.relative_to(self.bundle_path).as_posix(): file_sha256(p)
                              for directory in ("runner", "source", "configs")
                              for p in (self.bundle_path / directory).rglob("*") if p.is_file()}
            if (self.bundle_path / "dependency.lock").is_file():
                actual_payload["dependency.lock"] = file_sha256(self.bundle_path / "dependency.lock")
            if actual_payload != content["payload_files"]:
                errors.append("EXECUTABLE_PAYLOAD_MISMATCH")
        elif not any(str(s.get("entrypoint", "")).endswith(".ipynb") for s in contract.get("execution", {}).get("stages", [])):
            declared_configs = contract.get("execution", {}).get("configs", [])
            if not declared_configs:
                declared_configs = [f"configs/{p.name}" for p in sorted((self.bundle_path / "configs").glob("*")) if p.is_file()]
            configs = [{"path": relative, "sha256": file_sha256(contained_path(self.bundle_path / "configs", Path(relative).name))}
                       for relative in sorted(declared_configs)]
            if sha256_bytes(canonical_bytes(configs)) != content["config_hash"]:
                errors.append("EXECUTABLE_CONFIG_MISMATCH")
        if algorithm == BUNDLE_IDENTITY_ALGORITHM_V2 and self.expected_bundle_id is not None and any(str(s.get("entrypoint", "")).endswith(".ipynb") for s in contract.get("execution", {}).get("stages", [])):
            errors.append("UNBOUND_NOTEBOOK_METADATA: requires opt-in bundle v3")


def verify_bundle(bundle_path: Path | str) -> dict[str, Any]:
    """Convenience function to verify a bundle."""
    verifier = BundleVerifier(bundle_path)
    return verifier.verify()


def create_bundle(experiment_dir: Path | str) -> tuple[Path, str]:
    """Convenience function to create a bundle."""
    builder = BundleBuilder(experiment_dir)
    return builder.build()
