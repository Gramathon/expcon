"""Persistent experiment and run state management.

State is persisted as JSON files inside the experiment directory and
the global .expcon/ directory.  tmux sessions are NOT the database.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from expcon.lifecycle.state import (
    ExperimentState,
    RunState,
    StateError,
    transition as validate_transition,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    """A single execution run record."""

    run_id: str
    experiment_id: str
    version: str
    state: RunState
    backend: str
    created_at: str
    updated_at: str
    contract_hash: str = ""
    bundle_id: str = ""
    kernel: Optional[str] = None
    accelerator: str = "none"
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "version": self.version,
            "state": self.state.value,
            "backend": self.backend,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "contract_hash": self.contract_hash,
            "bundle_id": self.bundle_id,
            "kernel": self.kernel,
            "accelerator": self.accelerator,
            "events": self.events,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        return cls(
            run_id=data["run_id"],
            experiment_id=data["experiment_id"],
            version=data["version"],
            state=RunState(data["state"]),
            backend=data["backend"],
            created_at=data["created_at"],
            updated_at=data.get("updated_at", data["created_at"]),
            contract_hash=data.get("contract_hash", ""),
            bundle_id=data.get("bundle_id", ""),
            kernel=data.get("kernel"),
            accelerator=data.get("accelerator", "none"),
            events=data.get("events", []),
            metadata=data.get("metadata", {}),
        )


class EventLedger:
    """Append-only event log for a run."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.events_file = self.run_dir / "events.jsonl"

    def append(self, event_type: str, **fields: Any) -> dict[str, Any]:
        """Append an event to the log."""
        event = {
            "event": event_type,
            "timestamp": _utc_now(),
            **fields,
        }
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def read_all(self) -> list[dict[str, Any]]:
        """Read all events from the log."""
        if not self.events_file.exists():
            return []
        events = []
        for line in self.events_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events


class ExperimentLifecycle:
    """Manages experiment and run state on disk.

    The global state directory defaults to .expcon/ inside the workspace root.
    """

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()
        self.state_dir = self.workspace_root / ".expcon"
        self.runs_dir = self.state_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def experiment_state_path(self, experiment_dir: Path | str) -> Path:
        """Path to the experiment state file inside the experiment directory."""
        return Path(experiment_dir) / ".expcon_state.json"

    def get_experiment_state(self, experiment_dir: Path | str) -> ExperimentState:
        """Read the current experiment state from disk."""
        state_file = self.experiment_state_path(experiment_dir)
        if not state_file.exists():
            return ExperimentState.DRAFT
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return ExperimentState(data["state"])

    def set_experiment_state(
        self,
        experiment_dir: Path | str,
        new_state: ExperimentState,
        reason: str = "",
    ) -> ExperimentState:
        """Transition an experiment to a new state, validating the transition."""
        current = self.get_experiment_state(experiment_dir)
        validate_transition(current, new_state)

        state_file = self.experiment_state_path(experiment_dir)
        data = {
            "experiment": str(Path(experiment_dir).resolve()),
            "state": new_state.value,
            "updated_at": _utc_now(),
            "reason": reason,
        }
        state_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return new_state

    def create_run(
        self,
        experiment_id: str,
        version: str,
        backend: str,
        contract_hash: str = "",
        bundle_id: str = "",
        kernel: Optional[str] = None,
        accelerator: str = "none",
    ) -> RunRecord:
        """Create a new run record."""
        run_id = f"run-{experiment_id}-{uuid.uuid4().hex[:8]}"
        now = _utc_now()
        run = RunRecord(
            run_id=run_id,
            experiment_id=experiment_id,
            version=version,
            state=RunState.CREATED,
            backend=backend,
            created_at=now,
            updated_at=now,
            contract_hash=contract_hash,
            bundle_id=bundle_id,
            kernel=kernel,
            accelerator=accelerator,
        )
        self._save_run(run)
        ledger = EventLedger(self.run_dir(run_id))
        ledger.append("RUN_CREATED", run_id=run_id, backend=backend, accelerator=accelerator)
        return run

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def _save_run(self, run: RunRecord) -> None:
        run_dir = self.run_dir(run.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text(
            json.dumps(run.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def load_run(self, run_id: str) -> RunRecord:
        """Load a run record by ID."""
        run_file = self.run_dir(run_id) / "run.json"
        if not run_file.exists():
            raise KeyError(f"Run not found: {run_id}")
        return RunRecord.from_dict(json.loads(run_file.read_text(encoding="utf-8")))

    def update_run_state(self, run_id: str, new_state: RunState, reason: str = "", **event_fields: Any) -> RunState:
        """Transition a run to a new state, validating and logging."""
        run = self.load_run(run_id)
        current = run.state
        validate_transition(current, new_state)

        run.state = new_state
        run.updated_at = _utc_now()
        self._save_run(run)

        ledger = EventLedger(self.run_dir(run_id))
        ledger.append(new_state.value, run_id=run_id, reason=reason, **event_fields)
        return new_state

    def list_runs(self, experiment_id: Optional[str] = None) -> list[RunRecord]:
        """List all runs, optionally filtered by experiment ID."""
        runs = []
        for run_dir in sorted(self.runs_dir.iterdir()):
            run_file = run_dir / "run.json"
            if not run_file.exists():
                continue
            run = RunRecord.from_dict(json.loads(run_file.read_text(encoding="utf-8")))
            if experiment_id is None or run.experiment_id == experiment_id:
                runs.append(run)
        return runs

    def get_run_events(self, run_id: str, follow: bool = False) -> list[dict[str, Any]]:
        """Get all events for a run. If follow=True, tail the file continuously."""
        ledger = EventLedger(self.run_dir(run_id))
        if not follow:
            return ledger.read_all()

        events = ledger.read_all()
        for line in self._follow_file(ledger.events_file, len(events)):
            events.append(json.loads(line))
        return events

    def _follow_file(self, path: Path, from_count: int):
        """Generator that yields new lines appended to a file."""
        import time as _time

        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            f.seek(0, 2)  # Go to end
            while True:
                line = f.readline()
                if line:
                    yield line
                else:
                    _time.sleep(0.5)
                    # Check if file was truncated/rotated
                    current_pos = f.tell()
                    f.seek(0, 2)
                    if f.tell() < current_pos:
                        f.seek(0)
