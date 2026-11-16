"""Workspace-bound application API used by MCP and background workers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import Any
from pathlib import Path

import yaml

from expcon.adjudication.acceptance import validate_acceptance
from expcon.artifacts.artifact import ArtifactRegistry
from expcon.bundle.bundle import BundleBuilder, BundleVerifier, compute_bundle_identity
from expcon.contract.contract import load_contract
from expcon.contract.operations import (
    validate_experiment,
    freeze_experiment,
    diff_experiment,
)
from expcon.hashing.digest import sha256_bytes, file_sha256
from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.service import operations
from expcon.util.json_io import atomic_json, file_lock
from expcon.util.path import contained_path, safe_identifier


def page(items: list, offset: int = 0, limit: int = 50) -> dict:
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("INVALID_PAGE")
    return {
        "items": items[offset : offset + limit],
        "count": len(items),
        "next_offset": offset + limit if offset + limit < len(items) else None,
    }


class ExperimentService:
    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).resolve()
        self.lifecycle = ExperimentLifecycle(self.root)

    def path(self, relative: str) -> Path:
        return contained_path(self.root, relative)

    def experiment(self, reference: str) -> Path:
        path = self.path(reference)
        if path.name == "EXPERIMENT.yaml":
            path = path.parent
        if not (path / "EXPERIMENT.yaml").is_file():
            path = self.path("experiments/" + reference)
        if any(p.is_symlink() for p in path.rglob("*") if p.name not in {"bundle"}):
            raise ValueError("DRAFT_SYMLINK_UNSUPPORTED")
        load_contract(path / "EXPERIMENT.yaml")
        return path

    def inspect(self, experiment: str) -> dict:
        path = self.experiment(experiment)
        contract = load_contract(path / "EXPERIMENT.yaml")
        lock = path / "contract.lock.json"
        return {
            "contract": contract.data,
            "state": self.lifecycle.get_experiment_state(path).value,
            "frozen": lock.exists(),
            "identity": json.loads(lock.read_text()) if lock.exists() else None,
            "experiment_directory": str(path.relative_to(self.root)),
        }

    def validate(self, experiment: str) -> dict:
        return validate_experiment(self.experiment(experiment))

    def preflight(self, experiment: str, inputs: dict | None = None) -> dict:
        path = self.experiment(experiment)
        self.validate(experiment)
        contract = load_contract(path / "EXPERIMENT.yaml")
        identity = compute_bundle_identity(path, contract)
        from expcon.runner.inputs import content_identity

        observed = {
            name: content_identity(self.path(value))
            for name, value in (inputs or {}).items()
        }
        return {
            "status": "PASS",
            "observed_inputs": observed,
            "candidate_id": identity.bundle_id,
            "contract_hash": identity.content["contract_hash"],
            "bundle_identity_algorithm": identity.algorithm,
            "message": "Candidate identity only; execution admission verifies environment and input bindings.",
        }

    def init(self, experiment: str, contract: dict) -> dict:
        safe_identifier(contract["experiment"]["id"])
        safe_identifier(contract["experiment"]["version"])
        path = self.path(experiment)
        if path.exists():
            raise ValueError("EXPERIMENT_ALREADY_EXISTS")
        contract = {**contract, "bundle_identity_algorithm": "expcon-bundle-v3"}
        from expcon.contract.contract import ExperimentContract

        ExperimentContract(contract)
        path.mkdir(parents=True)
        (path / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract, sort_keys=False))
        return self.inspect(experiment)

    def freeze(self, experiment: str, expected_candidate_id: str) -> dict:
        path = self.experiment(experiment)
        contract = load_contract(path / "EXPERIMENT.yaml")
        safe_identifier(contract.experiment_id)
        safe_identifier(contract.version)
        validate_acceptance(contract.get("evaluation", "acceptance"))
        for stage in contract.get("execution", "stages", default=[]):
            spec = (
                stage.get(
                    "invocation", contract.get("execution", "invocation", default={})
                )
                or {}
            )
            for declaration in spec.get("inputs", {}).values():
                if not declaration.get("sha256"):
                    raise ValueError("SCIENTIFIC_INPUT_IDENTITY_REQUIRED")
        with file_lock(self.root / ".expcon/admission.lock"):
            candidate = self.preflight(experiment)
            if candidate["candidate_id"] != expected_candidate_id:
                raise ValueError("CANDIDATE_CHANGED")
            if (path / "contract.lock.json").exists():
                lock = json.loads((path / "contract.lock.json").read_text())
                if lock["identity"]["bundle_id"] != expected_candidate_id:
                    raise ValueError("EXPERIMENT_IDENTITY_CONFLICT")
                return {"status": "FROZEN", **lock["identity"]}
            result = freeze_experiment(path, self.root, expected_bundle_id=expected_candidate_id)
            return {**result, "experiment_directory": str(path.relative_to(self.root))}

    def import_draft(
        self, draft_directory: str, expected_candidate_id: str | None = None
    ) -> dict:
        """Import resolved files without treating repository metadata as file paths."""
        from expcon.bundle.source import resolve_entrypoints, resolve_source_closure

        draft = self.experiment(draft_directory)
        candidate = self.preflight(draft_directory)["candidate_id"]
        if expected_candidate_id and candidate != expected_candidate_id:
            raise ValueError("CANDIDATE_CHANGED")
        contract = load_contract(draft / "EXPERIMENT.yaml")
        safe_identifier(contract.experiment_id)
        safe_identifier(contract.version)
        target = self.path(
            f"experiments/{contract.experiment_id.lower()}_{contract.version}"
        )
        if target == draft:
            return self.freeze(draft_directory, candidate)
        with file_lock(self.root / ".expcon/import.lock"):
            if target.exists():
                if (
                    self.preflight(str(target.relative_to(self.root)))["candidate_id"]
                    != candidate
                ):
                    raise ValueError("EXPERIMENT_IDENTITY_CONFLICT")
                return self.freeze(str(target.relative_to(self.root)), candidate)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".admission-", dir=target.parent))
            try:
                shutil.copy2(draft / "EXPERIMENT.yaml", temporary / "EXPERIMENT.yaml")
                entries = [
                    (e.source_path, e.declared_path)
                    for e in resolve_entrypoints(draft, contract)
                ]
                entries += [
                    (e.source_path, e.repository_relative_path.as_posix())
                    for e in resolve_source_closure(draft, contract).entries
                ]
                from expcon.bundle.bundle import _config_entries

                for relative in _config_entries(draft, contract):
                    entries.append((draft / relative, relative))
                for dataset in contract.get("data", "datasets", default=[]):
                    if isinstance(dataset, dict) and dataset.get("path"):
                        entries.append(
                            (contained_path(draft, dataset["path"]), dataset["path"])
                        )
                for source, relative in entries:
                    source.resolve().relative_to(self.root)
                    if source.is_symlink():
                        raise ValueError("INPUT_SYMLINK")
                    destination = contained_path(temporary, relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    if source.suffix == ".ipynb":
                        shutil.copy2(
                            source.parent / "kernel-metadata.json",
                            destination.parent / "kernel-metadata.json",
                        )
                validate_experiment(temporary)
                if (
                    compute_bundle_identity(
                        temporary, load_contract(temporary / "EXPERIMENT.yaml")
                    ).bundle_id
                    != candidate
                ):
                    raise ValueError("IMPORTED_CANDIDATE_CHANGED")
                os.rename(temporary, target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        return self.freeze(str(target.relative_to(self.root)), candidate)

    def bundle(self, experiment: str) -> dict:
        path = self.experiment(experiment)
        self.validate(experiment)
        if diff_experiment(path)["divergence_detected"]:
            raise ValueError("FROZEN_EXPERIMENT_DIVERGED")
        bundle, identity = BundleBuilder(path).build()
        check = BundleVerifier(bundle, expected_bundle_id=identity).verify()
        if check["status"] != "PASS":
            raise ValueError(str(check))
        return {
            "status": "BUNDLED",
            "bundle_id": identity,
            "bundle_path": str(bundle.relative_to(self.root)),
        }

    def run(
        self,
        experiment: str,
        idempotency_key: str,
        backend: str = "local",
        kernel: str | None = None,
        inputs: dict | None = None,
    ) -> dict:
        self.validate(experiment)
        safe_identifier(idempotency_key)
        path = self.experiment(experiment)
        request = {
            "experiment": str(path.relative_to(self.root)),
            "backend": backend,
            "kernel": kernel,
            "inputs": {
                name: str(self.path(value)) for name, value in (inputs or {}).items()
            },
        }
        directory = self.root / ".expcon/requests"
        key = sha256_bytes(idempotency_key.encode())
        record = directory / f"{key}.json"
        with file_lock(directory / f"{key}.lock"):
            if record.exists():
                previous = json.loads(record.read_text())
                if previous["request"] != request:
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return previous
            run_id = "run-" + uuid.uuid4().hex
            payload: dict[str, Any] = {
                "request": request,
                "run_id": run_id,
                "status": "QUEUED",
            }
            atomic_json(record, payload, replace=False)
            with (directory / f"{key}.log").open("ab") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "expcon.service.worker",
                        str(self.root),
                        key,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            atomic_json(directory / f"{key}.pid.json", {"worker_pid": process.pid})
            return payload

    def status(self, run_id: str) -> dict:
        try:
            self.lifecycle.load_run(run_id)
            return operations.status(self.root, run_id, True)
        except (KeyError, SystemExit):
            pass
        for file in (self.root / ".expcon/requests").glob("*.json"):
            record = json.loads(file.read_text())
            if record.get("run_id") == run_id:
                pid_file = file.with_suffix(".pid.json")
                if record["status"] in {"QUEUED", "DISPATCHING"} and pid_file.exists():
                    try:
                        os.kill(json.loads(pid_file.read_text())["worker_pid"], 0)
                    except ProcessLookupError:
                        return {
                            **record,
                            "status": "BLOCKED",
                            "reason": "SUBMISSION_OUTCOME_UNKNOWN",
                        }
                return record
        raise ValueError("RUN_NOT_FOUND")

    def fetch(self, run_id: str) -> dict:
        with file_lock(self.lifecycle.run_dir(run_id) / ".fetch.lock"):
            run = self.lifecycle.load_run(run_id)
            if run.metadata.get("evidence_path"):
                return {
                    "status": "FETCHED",
                    "evidence_path": run.metadata["evidence_path"],
                    "run_id": run_id,
                }
            return operations.fetch(self.root, run_id, None, True)

    def verify(self, run_id: str) -> dict:
        return operations.verify(self.root, run_id, None, True)

    def adjudicate(self, run_id: str) -> dict:
        return operations.adjudicate(self.root, run_id, True)

    def result(self, run_id: str) -> dict:
        run = self.lifecycle.load_run(run_id)
        result = run.to_dict()
        for name in ("adjudication_path", "verification_path"):
            reference = run.metadata.get(name)
            result[name.removesuffix("_path")] = (
                json.loads(self.path(reference).read_text()) if reference else None
            )
        result["adjudication_current"] = bool(
            result.get("adjudication") and run.state.value == "ADJUDICATED"
        )
        if not result["adjudication_current"] and result.get("adjudication"):
            result["historical_adjudication"] = result.pop("adjudication")
            result["adjudication"] = None
        return result

    def artifacts(self, run_id: str, offset: int = 0, limit: int = 50) -> dict:
        registry = ArtifactRegistry(self.lifecycle.run_dir(run_id))
        return page([a.to_dict() for a in registry.list()], offset, limit)

    def artifact_read(
        self, run_id: str, artifact_id: str, offset: int = 0, limit: int = 8192
    ) -> dict:
        if offset < 0 or not 1 <= limit <= 65536:
            raise ValueError("INVALID_RANGE")
        artifacts = ArtifactRegistry(self.lifecycle.run_dir(run_id)).list()
        artifact = next(a for a in artifacts if a.artifact_id == artifact_id)
        path = Path(artifact.path)
        path.resolve().relative_to(self.lifecycle.run_dir(run_id).resolve())
        if file_sha256(path) != artifact.hash:
            raise ValueError("ARTIFACT_CHANGED")
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(limit)
        try:
            return {
                "artifact": artifact.to_dict(),
                "text": data.decode("utf-8"),
                "next_offset": offset + len(data),
            }
        except UnicodeDecodeError:
            return {"artifact": artifact.to_dict(), "binary": True}

    def history(self, offset: int = 0, limit: int = 50) -> dict:
        path = self.root / ".expcon/research_history.json"
        history = (
            json.loads(path.read_text())
            if path.exists()
            else {"proposals": [], "decisions": []}
        )
        return {
            "runs": page(
                [r.to_dict() for r in self.lifecycle.list_runs()], offset, limit
            ),
            "proposals": page(history["proposals"], offset, limit),
            "decisions": page(history["decisions"], offset, limit),
        }

    def record(self, kind: str, entry: dict) -> dict:
        if kind not in {"proposals", "decisions"}:
            raise ValueError("INVALID_RECORD_KIND")
        for reference in entry.get("referenced_runs", []):
            self.lifecycle.load_run(reference)
        path = self.root / ".expcon/research_history.json"
        with file_lock(path.with_suffix(".lock")):
            history = (
                json.loads(path.read_text())
                if path.exists()
                else {"proposals": [], "decisions": []}
            )
            entry = {**entry, "id": uuid.uuid4().hex}
            history[kind].append(entry)
            atomic_json(path, history)
        return entry
