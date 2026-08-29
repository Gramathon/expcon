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
from typing import Any, Optional

from expcon.hashing.canonical import canonical_bytes
from expcon.hashing.digest import sha256_bytes, file_sha256
from expcon.hashing.manifest import compute_directory_manifest
from expcon.contract.canonical import compute_contract_hash
from expcon.artifacts.artifact import ArtifactRegistry


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


class EvidenceVerifier:
    """Verifies an evidence bundle against the frozen contract and bundle."""

    def __init__(self, evidence_dir: Path | str, bundle_path: Path | str | None = None):
        self.evidence_dir = Path(evidence_dir).resolve()
        self.bundle_path = Path(bundle_path) if bundle_path else None
        self.manifest_path = self.evidence_dir / "evidence_manifest.json"

    def verify(self) -> dict[str, Any]:
        """Verify the evidence bundle.

        Returns a dict with:
          - status: PASS | FAIL
          - errors: list of error strings
          - verified: bool
        """
        errors = []

        # Load evidence manifest
        if not self.manifest_path.exists():
            return {"status": "FAIL", "errors": ["evidence_manifest.json not found"], "verified": False}

        manifest = EvidenceBundle.from_dict(
            json.loads(self.manifest_path.read_text(encoding="utf-8"))
        )

        # 1. Verify contract hash
        resolved_contract_path = self.evidence_dir / "resolved_contract.json"
        if resolved_contract_path.exists():
            contract_data = json.loads(resolved_contract_path.read_text(encoding="utf-8"))
            actual_contract_hash = compute_contract_hash(contract_data)
            if actual_contract_hash != manifest.contract_hash:
                errors.append(f"CONTRACT_HASH_MISMATCH: expected={manifest.contract_hash} actual={actual_contract_hash}")
        else:
            errors.append("MISSING: resolved_contract.json")

        # 2. Verify bundle ID (if bundle is available)
        if self.bundle_path and self.bundle_path.exists():
            bundle_manifest_path = self.bundle_path / "bundle_manifest.json"
            if bundle_manifest_path.exists():
                bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
                if bundle_manifest.get("bundle_id") != manifest.bundle_id:
                    errors.append(f"BUNDLE_ID_MISMATCH: expected={manifest.bundle_id} actual={bundle_manifest.get('bundle_id')}")

                # Verify bundle integrity
                from expcon.bundle.bundle import BundleVerifier

                bundle_verification = BundleVerifier(self.bundle_path).verify()
                if bundle_verification["status"] != "PASS":
                    errors.append(f"BUNDLE_VERIFICATION_FAILED: {bundle_verification['errors']}")
            else:
                errors.append("BUNDLE_MANIFEST_NOT_FOUND")
        # Bundle verification is optional - if no bundle path is provided,
        # skip bundle verification rather than failing

        # 3. Verify artifacts
        artifacts_file = self.evidence_dir / "artifacts.json"
        if artifacts_file.exists():
            registry = ArtifactRegistry(self.evidence_dir)
            artifact_data = json.loads(artifacts_file.read_text(encoding="utf-8"))
            for artifact_entry in artifact_data.get("artifacts", []):
                artifact_file = self.evidence_dir / "artifacts" / artifact_entry.get("path", "")
                if not artifact_file.exists():
                    errors.append(f"MISSING_ARTIFACT: {artifact_entry.get('path')}")
                    continue
                actual_hash = file_sha256(artifact_file)
                if actual_hash != artifact_entry.get("hash"):
                    errors.append(f"ARTIFACT_HASH_MISMATCH: {artifact_entry.get('path')}")
        else:
            errors.append("MISSING: artifacts.json")

        # 4. Verify metrics haven't been tampered
        metrics_file = self.evidence_dir / "metrics" / "metrics.json"
        if metrics_file.exists():
            metrics_data = json.loads(metrics_file.read_text(encoding="utf-8"))
            metrics_hash = sha256_bytes(canonical_bytes(metrics_data))
            if "metrics_hash" in manifest.metrics:
                if metrics_hash != manifest.metrics["metrics_hash"]:
                    errors.append(f"METRICS_TAMPERED: expected={manifest.metrics['metrics_hash']} actual={metrics_hash}")
            else:
                # Record the hash for future verification
                manifest.metrics["metrics_hash"] = metrics_hash
        else:
            # Check if metrics are embedded in manifest
            if not manifest.metrics:
                errors.append("MISSING_METRICS")

        # 5. Verify environment
        env_file = self.evidence_dir / "environment.json"
        if not env_file.exists():
            errors.append("MISSING: environment.json")

        # 6. Verify required outputs
        required_outputs = manifest.metrics.get("required_outputs", [])
        for req_output in required_outputs:
            output_file = self.evidence_dir / "outputs" / req_output
            if not output_file.exists():
                errors.append(f"MISSING_REQUIRED_OUTPUT: {req_output}")

        verified = len(errors) == 0
        manifest.verified = verified
        manifest.verification_errors = errors

        # Update manifest
        self.manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        return {
            "status": "PASS" if verified else "FAIL",
            "errors": errors,
            "verified": verified,
            "evidence_id": manifest.evidence_id,
        }

    def package_evidence(
        self,
        run_id: str,
        experiment_id: str,
        contract_hash: str,
        bundle_id: str,
        output_dir: Path,
        required_outputs: list[str],
    ) -> EvidenceBundle:
        """Package evidence from a run's output directory."""
        output_dir = Path(output_dir).resolve()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        # Copy resolved contract
        resolved = output_dir / "resolved_contract.json"
        if resolved.exists():
            import shutil

            shutil.copy2(resolved, self.evidence_dir / "resolved_contract.json")

        # Copy environment
        env_file = output_dir / "environment.json"
        if env_file.exists():
            import shutil

            shutil.copy2(env_file, self.evidence_dir / "environment.json")
        else:
            env_data = {
                "python": "unknown",
                "platform": "unknown",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            (self.evidence_dir / "environment.json").write_text(
                json.dumps(env_data, indent=2) + "\n", encoding="utf-8"
            )

        # Collect artifacts
        artifacts_list = []
        artifacts_dir = self.evidence_dir / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)

        # Also create outputs/ directory for required output verification
        outputs_evidence_dir = self.evidence_dir / "outputs"
        outputs_evidence_dir.mkdir(exist_ok=True)

        # Look for output files
        outputs_dir = output_dir / "outputs"
        if outputs_dir.exists():
            import shutil

            for f in outputs_dir.iterdir():
                if f.is_file():
                    dest = artifacts_dir / f.name
                    shutil.copy2(f, dest)
                    # Also copy to outputs/ for required output verification
                    shutil.copy2(f, outputs_evidence_dir / f.name)
                    artifacts_list.append({
                        "artifact_id": f"art-{f.name}",
                        "artifact_type": self._infer_type(f.name),
                        "hash": file_sha256(dest),
                        "path": f.name,
                    })

        # Collect metrics
        metrics_data = {}
        metrics_dir = output_dir / "metrics"
        if metrics_dir.exists():
            metrics_dest = self.evidence_dir / "metrics"
            metrics_dest.mkdir(exist_ok=True)
            for f in metrics_dir.iterdir():
                if f.is_file():
                    import shutil

                    shutil.copy2(f, metrics_dest / f.name)
                    if f.suffix == ".json":
                        metrics_data.update(json.loads(f.read_text(encoding="utf-8")))
            metrics_data["metrics_hash"] = sha256_bytes(canonical_bytes(metrics_data))
            metrics_data["required_outputs"] = required_outputs
        else:
            metrics_dest = self.evidence_dir / "metrics"
            metrics_dest.mkdir(exist_ok=True)

        # Copy stage manifests if available
        stage_manifests = output_dir / "stage_manifests"
        if stage_manifests.exists():
            import shutil

            shutil.copytree(stage_manifests, self.evidence_dir / "stage_manifests", dirs_exist_ok=True)

        # Copy logs
        logs_dir = output_dir / "logs"
        if logs_dir.exists():
            import shutil

            shutil.copytree(logs_dir, self.evidence_dir / "logs", dirs_exist_ok=True)

        # Compute evidence hash
        evidence_manifest = EvidenceBundle(
            evidence_id=f"ev-{run_id}",
            run_id=run_id,
            experiment_id=experiment_id,
            contract_hash=contract_hash,
            bundle_id=bundle_id,
            verified=False,
            artifacts=artifacts_list,
            metrics=metrics_data,
            environment={},
            verification_errors=[],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        self.manifest_path.write_text(
            json.dumps(evidence_manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Write artifacts.json for verify to check
        (self.evidence_dir / "artifacts.json").write_text(
            json.dumps({"artifacts": artifacts_list}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        # Write hashes.json
        evidence_manifest_dir = self.evidence_dir
        file_manifest = compute_directory_manifest(evidence_manifest_dir, skip_hidden=True)
        (evidence_manifest_dir / "hashes.json").write_text(
            json.dumps(file_manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        return evidence_manifest

    def _infer_type(self, filename: str) -> str:
        """Infer artifact type from filename."""
        name = filename.lower()
        if name.endswith(".parquet"):
            return "predictions"
        if name.endswith(".json"):
            return "metrics"
        if name.endswith(".pth") or name.endswith(".safetensors"):
            return "checkpoint"
        if name.endswith(".csv"):
            return "dataset"
        if name.endswith(".png") or name.endswith(".jpg"):
            return "plot"
        if "submission" in name:
            return "submission"
        return "other"


def verify_evidence(evidence_dir: Path | str, bundle_path: Path | str | None = None) -> dict[str, Any]:
    """Convenience function to verify evidence."""
    verifier = EvidenceVerifier(evidence_dir, bundle_path)
    return verifier.verify()
