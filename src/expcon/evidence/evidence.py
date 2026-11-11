"""Evidence bundle creation and verification.

Every completed or failed execution returns an evidence package.
Verification must detect:
  - modified output
  - changed metric
  - changed predictions
  - missing required artifact
  - wrong contract
  - wrong bundle ID
  - wrong dataset manifest
  - broken artifact provenance
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from expcon.hashing.digest import file_sha256
from expcon.util.path import contained_path
from expcon.contract.canonical import compute_contract_hash


class EvidenceError(Exception):
    """Raised when evidence verification fails."""


@dataclass
class EvidenceBundle:
    """A complete evidence package for a run."""

    evidence_id: str
    run_id: str
    experiment_id: str
    contract_hash: str
    bundle_id: str
    verified: bool = False
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    verification_errors: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "contract_hash": self.contract_hash,
            "bundle_id": self.bundle_id,
            "verified": self.verified,
            "artifacts": self.artifacts,
            "metrics": self.metrics,
            "environment": self.environment,
            "verification_errors": self.verification_errors,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceBundle":
        return cls(
            evidence_id=data["evidence_id"],
            run_id=data["run_id"],
            experiment_id=data["experiment_id"],
            contract_hash=data["contract_hash"],
            bundle_id=data["bundle_id"],
            verified=data.get("verified", False),
            artifacts=data.get("artifacts", []),
            metrics=data.get("metrics", {}),
            environment=data.get("environment", {}),
            verification_errors=data.get("verification_errors", []),
            created_at=data.get("created_at", ""),
        )


def evidence_seal(evidence_dir: Path) -> dict[str, str]:
    manifest_path = evidence_dir / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    return {"evidence_id": manifest["evidence_id"], "manifest_sha256": file_sha256(manifest_path)}


def bind_evidence(lifecycle, run_id: str, evidence_dir: Path) -> None:
    """Trust-root operation used only after local packaging; never by verification."""
    run = lifecycle.load_run(run_id)
    manifest = json.loads((evidence_dir / "evidence_manifest.json").read_text())
    for key in ("run_id", "experiment_id", "contract_hash", "bundle_id"):
        if manifest[key] != getattr(run, key):
            raise EvidenceError(f"Cannot bind mismatched {key}")
    seal = evidence_seal(evidence_dir)
    seals = run.metadata.setdefault("evidence_seals", [])
    previous = next((item for item in seals if item["evidence_id"] == seal["evidence_id"]), None)
    if previous is not None and previous != seal:
        raise EvidenceError("Existing evidence seal is immutable; use a new evidence version")
    if previous is None:
        seals.append(seal)
        lifecycle._save_run(run)


class EvidenceVerifier:
    """Read-only verification against an independently retained run seal.

    Historical manifests remain readable but cannot acquire stronger assurance
    without their missing independent anchor. Verification never writes evidence.
    """

    def __init__(self, evidence_dir: Path | str, bundle_path: Path | str | None = None,
                 *, expected_run=None):
        self.evidence_dir = Path(evidence_dir).resolve()
        self.bundle_path = Path(bundle_path) if bundle_path else None
        self.manifest_path = self.evidence_dir / "evidence_manifest.json"
        self.expected_run = expected_run
        # Local run directories are trusted host state, not transferred evidence.
        run_file = self.evidence_dir.parent / "run.json"
        if expected_run is None and run_file.is_file() and self.evidence_dir.parent.parent.name == "runs":
            from expcon.lifecycle.experiment_state import ExperimentLifecycle
            self.expected_run = ExperimentLifecycle(self.evidence_dir.parents[3]).load_run(self.evidence_dir.parent.name)

    def verify(self) -> dict[str, Any]:
        errors: list[str] = []
        manifest: dict[str, Any] = {}
        try:
            manifest = json.loads(self.manifest_path.read_text())
            self._verify(manifest, errors)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append(f"INVALID_EVIDENCE: {exc}")
        return {"status": "FAIL" if errors else "PASS", "errors": errors,
                "verified": not errors, "evidence_id": manifest.get("evidence_id") if isinstance(manifest, dict) else None}

    def _verify(self, manifest: dict[str, Any], errors: list[str]) -> None:
        from expcon.bundle.bundle import BundleVerifier
        if manifest.get("evidence_algorithm") != "expcon-evidence-v2":
            errors.append("LEGACY_EVIDENCE_UNANCHORED: historical status is not independent verification")
        run = self.expected_run
        if run is None:
            errors.append("EXPECTED_RUN_REQUIRED")
        else:
            for key in ("run_id", "experiment_id", "contract_hash", "bundle_id"):
                if manifest.get(key) != getattr(run, key):
                    errors.append(f"EXPECTED_{key.upper()}_MISMATCH")
            seal = evidence_seal(self.evidence_dir)
            if seal not in run.metadata.get("evidence_seals", []):
                errors.append("EVIDENCE_SEAL_MISMATCH")
        if self.bundle_path is None or not self.bundle_path.is_dir():
            errors.append("EXPECTED_BUNDLE_REQUIRED")
        else:
            check = BundleVerifier(self.bundle_path, expected_bundle_id=run.bundle_id if run else None).verify()
            if check["status"] != "PASS":
                errors.extend(f"BUNDLE_VERIFICATION_FAILED: {item}" for item in check["errors"])
        contract = json.loads((self.evidence_dir / "resolved_contract.json").read_text())
        if compute_contract_hash(contract) != manifest["contract_hash"]:
            errors.append("CONTRACT_HASH_MISMATCH")
        hashes_path = self.evidence_dir / "hashes.json"
        if file_sha256(hashes_path) != manifest.get("hashes_sha256"):
            errors.append("HASHES_MANIFEST_MISMATCH: hashes.json")
        inventory = json.loads(hashes_path.read_text())["files"]
        for relative, expected in inventory.items():
            path = contained_path(self.evidence_dir, relative)
            if not path.is_file() or file_sha256(path) != expected:
                errors.append(f"CONTENT_HASH_MISMATCH: {relative}")
        actual = set()
        for path in self.evidence_dir.rglob("*"):
            if path.is_symlink():
                contained_path(self.evidence_dir, path.relative_to(self.evidence_dir).as_posix())
            if path.is_file():
                actual.add(path.relative_to(self.evidence_dir).as_posix())
        if actual - {"hashes.json", "evidence_manifest.json"} != set(inventory):
            errors.append("EVIDENCE_INVENTORY_MISMATCH")
        artifacts = json.loads((self.evidence_dir / "artifacts.json").read_text())["artifacts"]
        if artifacts != manifest["artifacts"]:
            errors.append("ARTIFACT_MANIFEST_MISMATCH")
        for artifact in artifacts:
            path = contained_path(self.evidence_dir / "artifacts", artifact["path"])
            if not path.is_file() or file_sha256(path) != artifact["hash"]:
                errors.append(f"ARTIFACT_HASH_MISMATCH: {artifact['path']}")
            output = contained_path(self.evidence_dir / "outputs", artifact["path"])
            if not output.is_file() or file_sha256(output) != artifact["hash"]:
                errors.append(f"OUTPUT_SUBSTITUTION: outputs/{artifact['path']}")
        required = contract.get("outputs", {}).get("required", [])
        for relative in required:
            path = contained_path(self.evidence_dir / "outputs", relative)
            if not path.is_file() or f"outputs/{relative}" not in inventory:
                errors.append(f"MISSING_REQUIRED_OUTPUT: {relative}")
        environment = json.loads((self.evidence_dir / "environment.json").read_text())
        if not environment or environment.get("python") == "unknown":
            errors.append("MISSING_ENVIRONMENT_ATTESTATION")
        metric_source = contained_path(self.evidence_dir / "outputs", contract.get("evaluation", {}).get("metrics_file", "metrics.json"))
        metric_copy = self.evidence_dir / "metrics/metrics.json"
        if metric_copy.is_file() and (not metric_source.is_file() or json.loads(metric_source.read_text()) != json.loads(metric_copy.read_text())):
            errors.append("METRIC_SOURCE_MISMATCH")

    def package_evidence(self, run_id: str, experiment_id: str, contract_hash: str,
                         bundle_id: str, output_dir: Path, required_outputs: list[str]) -> EvidenceBundle:
        """Create a new immutable package; never repair or overwrite an old one."""
        import shutil
        import uuid
        output_dir = Path(output_dir).resolve()
        if self.manifest_path.exists():
            raise EvidenceError("Evidence already packaged; use a new version directory")
        for name in ("resolved_contract.json", "environment.json"):
            if not (output_dir / name).is_file():
                raise EvidenceError(f"Missing packaging input: {name}")
        contract = json.loads((output_dir / "resolved_contract.json").read_text())
        if compute_contract_hash(contract) != contract_hash:
            raise EvidenceError("Packaging contract hash differs from expected run")
        if required_outputs != contract.get("outputs", {}).get("required", []):
            raise EvidenceError("Required outputs differ from frozen specification")
        metric_copy = output_dir / "metrics/metrics.json"
        metric_source = contained_path(output_dir / "outputs", contract.get("evaluation", {}).get("metrics_file", "metrics.json"))
        if metric_copy.is_file() and (not metric_source.is_file() or json.loads(metric_source.read_text()) != json.loads(metric_copy.read_text())):
            raise EvidenceError("METRIC_SOURCE_MISMATCH")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                relative = path.relative_to(output_dir).as_posix()
                source = contained_path(output_dir, relative)
                destination = contained_path(self.evidence_dir, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        artifacts: list[dict[str, Any]] = []
        outputs = self.evidence_dir / "outputs"
        for path in sorted(outputs.rglob("*")):
            if path.is_file():
                relative = path.relative_to(outputs).as_posix()
                destination = contained_path(self.evidence_dir / "artifacts", relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                artifacts.append({"artifact_id": f"art-{uuid.uuid4().hex}", "artifact_type": "output",
                                  "hash": file_sha256(path), "path": relative,
                                  "run_id": run_id, "experiment_id": experiment_id,
                                  "verification_state": "REGISTERED"})
        metrics_file = self.evidence_dir / "metrics/metrics.json"
        metrics = json.loads(metrics_file.read_text()) if metrics_file.exists() else {}
        bundle = EvidenceBundle(f"ev-{run_id}-{uuid.uuid4().hex}", run_id, experiment_id,
                                contract_hash, bundle_id, artifacts=artifacts, metrics=metrics,
                                created_at=datetime.now(timezone.utc).isoformat())
        (self.evidence_dir / "artifacts.json").write_text(json.dumps({"artifacts": artifacts}, indent=2, sort_keys=True)+"\n")
        files = {path.relative_to(self.evidence_dir).as_posix(): file_sha256(path)
                 for path in sorted(self.evidence_dir.rglob("*")) if path.is_file()
                 and path.relative_to(self.evidence_dir).as_posix() not in {"hashes.json", "evidence_manifest.json"}}
        hashes = self.evidence_dir / "hashes.json"
        hashes.write_text(json.dumps({"algorithm": "sha256", "files": files}, indent=2, sort_keys=True)+"\n")
        manifest = {**bundle.to_dict(), "evidence_algorithm": "expcon-evidence-v2",
                    "hashes_sha256": file_sha256(hashes)}
        self.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n")
        if (self.evidence_dir.parent / "run.json").is_file() and self.evidence_dir.parent.parent.name == "runs":
            from expcon.lifecycle.experiment_state import ExperimentLifecycle
            bind_evidence(ExperimentLifecycle(self.evidence_dir.parents[3]), run_id, self.evidence_dir)
        return bundle


def verify_evidence(evidence_dir: Path | str, bundle_path: Path | str | None = None,
                    *, expected_run=None) -> dict[str, Any]:
    return EvidenceVerifier(evidence_dir, bundle_path, expected_run=expected_run).verify()
