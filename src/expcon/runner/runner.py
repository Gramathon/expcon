"""Stage runner - executes experiment stages and registers artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from expcon.runner.backends import ExecutionBackend, RunContext, RunStatus


@dataclass
class StageResult:
    """Result of executing a single stage."""

    stage_id: str
    success: bool
    output: str = ""
    error: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "artifacts": self.artifacts,
            "metrics": self.metrics,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageResult":
        return cls(
            stage_id=data["stage_id"],
            success=data["success"],
            output=data.get("output", ""),
            error=data.get("error", ""),
            artifacts=data.get("artifacts", []),
            metrics=data.get("metrics", {}),
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass
class RunContext:
    """Context for a backend run."""

    experiment_id: str
    version: str
    bundle_id: str
    contract_hash: str
    kernel: Optional[str] = None
    accelerator: str = "none"
    environment: dict[str, str] = field(default_factory=dict)
    extra_args: list[str] = field(default_factory=list)


class StageRunner:
    """Runs experiment stages and registers artifacts.

    This is deliberately boring - no scientific decision-making.
    """

    def __init__(self, backend: ExecutionBackend):
        self.backend = backend

    def run(self, bundle_path: Path, context: RunContext) -> str:
        """Submit a bundle to the backend and return a run_id."""
        return self.backend.submit(bundle_path, context)

    def get_status(self, run_id: str) -> RunStatus:
        """Get the status of a run."""
        return self.backend.status(run_id)

    def fetch_evidence(self, run_id: str, destination: Path) -> Path:
        """Fetch evidence from a completed run."""
        return self.backend.fetch(run_id, destination)

    def cancel(self, run_id: str) -> bool:
        """Cancel a running job."""
        return self.backend.cancel(run_id)
