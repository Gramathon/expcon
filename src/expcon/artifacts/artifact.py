"""Artifact model - first-class scientific objects with provenance."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from expcon.hashing.digest import file_sha256
from expcon.util.json_io import atomic_json, file_lock
from expcon.util.path import safe_identifier


class ArtifactError(Exception):
    """Raised when artifact operations fail."""


@dataclass
class Artifact:
    """A first-class scientific artifact with full provenance."""

    artifact_id: str
    artifact_type: str
    hash: str
    experiment_id: str
    run_id: str
    parent_inputs: list[str] = field(default_factory=list)
    producer_stage: str = ""
    created_at: str = ""
    verification_state: str = "UNVERIFIED"
    path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "hash": self.hash,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "parent_inputs": self.parent_inputs,
            "producer_stage": self.producer_stage,
            "created_at": self.created_at,
            "verification_state": self.verification_state,
            "path": self.path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artifact":
        return cls(
            artifact_id=data["artifact_id"],
            artifact_type=data["artifact_type"],
            hash=data["hash"],
            experiment_id=data["experiment_id"],
            run_id=data["run_id"],
            parent_inputs=data.get("parent_inputs", []),
            producer_stage=data.get("producer_stage", ""),
            created_at=data.get("created_at", ""),
            verification_state=data.get("verification_state", "UNVERIFIED"),
            path=data.get("path", ""),
            metadata=data.get("metadata", {}),
        )


class ArtifactRegistry:
    """Registry for artifacts within a run.

    Artifacts are stored as a provenance DAG manifest, not a graph database.
    """

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.artifacts_file = self.run_dir / "artifacts.json"
        self._artifacts: list[Artifact] = []
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.artifacts_file.exists():
            data = json.loads(self.artifacts_file.read_text(encoding="utf-8"))
            self._artifacts = [Artifact.from_dict(a) for a in data.get("artifacts", [])]
        self._loaded = True

    def _save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "run_id": str(self.run_dir.name),
            "artifacts": [a.to_dict() for a in self._artifacts],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_json(self.artifacts_file, data)

    def register(self, file_path: Path, artifact_type: str, experiment_id: str,
                 run_id: str, producer_stage: str = "", parent_inputs=None, metadata=None) -> Artifact:
        safe_identifier(run_id)
        if run_id != self.run_dir.name:
            raise ArtifactError("Producing run does not match registry")
        with file_lock(self.run_dir / ".artifacts.lock"):
            self._loaded = False
            return self._register(file_path, artifact_type, experiment_id, run_id,
                                  producer_stage, parent_inputs, metadata)

    def _register(
        self,
        file_path: Path,
        artifact_type: str,
        experiment_id: str,
        run_id: str,
        producer_stage: str = "",
        parent_inputs: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Artifact:
        """Register an artifact by computing its hash and provenance."""
        self._load()
        file_path = Path(file_path)
        if not file_path.exists():
            raise ArtifactError(f"Artifact file not found: {file_path}")

        artifact = Artifact(
            artifact_id=f"art-{uuid.uuid4().hex[:8]}",
            artifact_type=artifact_type,
            hash=file_sha256(file_path),
            experiment_id=experiment_id,
            run_id=run_id,
            parent_inputs=parent_inputs or [],
            producer_stage=producer_stage,
            created_at=datetime.now(timezone.utc).isoformat(),
            verification_state="REGISTERED",
            path=str(file_path),
            metadata=metadata or {},
        )
        self._artifacts.append(artifact)
        self._save()
        return artifact

    def get(self, artifact_id: str) -> Optional[Artifact]:
        """Look up an artifact by ID."""
        self._load()
        for a in self._artifacts:
            if a.artifact_id == artifact_id:
                return a
        return None

    def list(self, artifact_type: Optional[str] = None) -> list[Artifact]:
        """List all artifacts, optionally filtered by type."""
        self._load()
        if artifact_type is None:
            return list(self._artifacts)
        return [a for a in self._artifacts if a.artifact_type == artifact_type]

    def verify(self, file_path: Path, artifact_id: str) -> bool:
        """Verify that a file matches the registered artifact hash."""
        artifact = self.get(artifact_id)
        if artifact is None:
            raise ArtifactError(f"Artifact not found: {artifact_id}")
        actual_hash = file_sha256(file_path)
        return actual_hash == artifact.hash

    def to_provenance_dag(self) -> dict[str, Any]:
        """Return a structured provenance DAG."""
        self._load()
        nodes = []
        edges = []
        for a in self._artifacts:
            nodes.append({
                "id": a.artifact_id,
                "type": a.artifact_type,
                "hash": a.hash,
                "stage": a.producer_stage,
            })
            for parent in a.parent_inputs:
                edges.append({"from": parent, "to": a.artifact_id})
        return {"nodes": nodes, "edges": edges}
