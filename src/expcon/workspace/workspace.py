"""tmux workspace management.

tmux provides operational continuity.  Expcon provides scientific continuity.
The tmux session is NOT the source of scientific state.  If the session
disappears, Expcon reconstructs state from persistent run records.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional


class WorkspaceError(Exception):
    """Raised when workspace operations fail."""


class WorkspaceManager:
    """Manages tmux workspaces for experiment operations."""

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()
        self.state_dir = self.workspace_root / ".expcon"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _session_name(self, experiment_ref: str) -> str:
        """Generate a safe tmux session name from an experiment reference."""
        safe = experiment_ref.replace("/", "-").replace(".", "-").replace("_", "-")
        return f"expcon-{safe}"

    def _has_tmux(self) -> bool:
        return shutil.which("tmux") is not None

    def create_workspace(self, experiment_ref: str, experiment_dir: Path | None = None) -> dict[str, Any]:
        """Create a tmux workspace for an experiment.

        Layout:
        ┌───────────────────────────────────────────────┐
        │ coding / Expcon agent                        │
        ├───────────────────────┬───────────────────────┤
        │ expcon events --follow│ backend status/logs   │
        ├───────────────────────┴───────────────────────┤
        │ ordinary shell                               │
        └───────────────────────────────────────────────┘
        """
        session_name = self._session_name(experiment_ref)

        if not self._has_tmux():
            raise WorkspaceError("tmux is not installed")

        # Check if session already exists
        if self._session_exists(session_name):
            return {
                "session": session_name,
                "created": False,
                "message": f"Workspace already exists: {session_name}",
                "attach_command": f"tmux attach -t {session_name}",
            }

        # Find experiment directory
        if experiment_dir is None:
            experiment_dir = self._find_experiment_dir(experiment_ref)

        # Create the session with initial window
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name, "-x", "200", "-y", "50"],
            capture_output=True,
            check=False,
        )

        # Pane 1: events --follow (top-left)
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{session_name}:0.0", f"cd {self.workspace_root}", "Enter"],
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{session_name}:0.0", "expcon events --follow " + self._find_run_id(experiment_ref), "Enter"],
            capture_output=True,
        )

        # Split: top-right for backend status
        subprocess.run(
            ["tmux", "split-window", "-h", "-t", f"{session_name}:0.0"],
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{session_name}:0.0", f"cd {self.workspace_root}", "Enter"],
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{session_name}:0.0", "expcon ps", "Enter"],
            capture_output=True,
        )

        # Split: bottom full-width shell
        subprocess.run(
            ["tmux", "split-window", "-v", "-t", f"{session_name}:0.1"],
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{session_name}:0.1", f"cd {self.workspace_root}", "Enter"],
            capture_output=True,
        )

        # Set layout
        subprocess.run(
            ["tmux", "select-layout", "-t", session_name, "even-layout"],
            capture_output=True,
        )

        # Set window title
        subprocess.run(
            ["tmux", "rename-window", "-t", f"{session_name}:0", f"expcon:{experiment_ref}"],
            capture_output=True,
        )

        # Persist workspace metadata (NOT scientific state)
        meta = {
            "session_name": session_name,
            "experiment_ref": experiment_ref,
            "experiment_dir": str(experiment_dir) if experiment_dir else None,
            "created_at": _utc_now(),
            "tmux_session": True,
        }
        meta_file = self.state_dir / "workspaces" / f"{session_name}.json"
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        return {
            "session": session_name,
            "created": True,
            "message": f"Workspace created: {session_name}",
            "attach_command": f"tmux attach -t {session_name}",
            "experiment_dir": str(experiment_dir) if experiment_dir else None,
        }

    def attach_workspace(self, experiment_ref: str) -> dict[str, Any]:
        """Attach to an existing workspace."""
        session_name = self._session_name(experiment_ref)

        if not self._session_exists(session_name):
            # Recreate if session was lost (tmux destroyed but state persists)
            return self.create_workspace(experiment_ref)

        return {
            "session": session_name,
            "created": False,
            "message": f"Attaching to existing workspace: {session_name}",
            "attach_command": f"tmux attach -t {session_name}",
        }

    def list_workspaces(self) -> list[dict[str, Any]]:
        """List all known workspaces."""
        workspaces_dir = self.state_dir / "workspaces"
        if not workspaces_dir.exists():
            return []

        result = []
        for meta_file in sorted(workspaces_dir.glob("*.json")):
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            session_name = meta.get("session_name", "")
            meta["active"] = self._session_exists(session_name)
            result.append(meta)
        return result

    def kill_workspace(self, experiment_ref: str) -> dict[str, Any]:
        """Kill a tmux workspace. Scientific state is preserved."""
        session_name = self._session_name(experiment_ref)

        if not self._session_exists(session_name):
            return {
                "session": session_name,
                "killed": False,
                "message": f"Session {session_name} not found",
            }

        subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            capture_output=True,
        )

        return {
            "session": session_name,
            "killed": True,
            "message": f"Session {session_name} killed. Scientific state preserved.",
        }

    def _session_exists(self, session_name: str) -> bool:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        return result.returncode == 0

    def _find_experiment_dir(self, experiment_ref: str) -> Path | None:
        """Find the experiment directory for a reference like 'E13/v002'."""
        # Search common locations
        parts = experiment_ref.split("/")
        search_roots = [self.workspace_root, self.workspace_root.parent]

        for root in search_roots:
            if not root.exists():
                continue
            # Try direct match
            candidate = root / "experiments" / experiment_ref
            if candidate.exists():
                return candidate
            # Try with parts
            if len(parts) == 2:
                for exp_dir in (root / "experiments").iterdir() if (root / "experiments").exists() else []:
                    if parts[0] in exp_dir.name and parts[1] in exp_dir.name:
                        return exp_dir
            # Try workspace_root itself
            if (root / "EXPERIMENT.yaml").exists():
                return root

        return None

    def _find_run_id(self, experiment_ref: str) -> str:
        """Find the most recent run ID for an experiment."""
        from expcon.lifecycle.experiment_state import ExperimentLifecycle

        lifecycle = ExperimentLifecycle(self.workspace_root)
        # Try to extract experiment ID from ref
        parts = experiment_ref.split("/")
        if len(parts) >= 1:
            exp_id = parts[0]
            runs = lifecycle.list_runs(exp_id)
            if runs:
                return runs[-1].run_id
        return ""

    def reconstruct_state_after_loss(self) -> dict[str, Any]:
        """Reconstruct state after tmux session loss.

        This verifies that scientific/run state survives tmux destruction.
        """
        from expcon.lifecycle.experiment_state import ExperimentLifecycle

        lifecycle = ExperimentLifecycle(self.workspace_root)
        runs = lifecycle.list_runs()

        return {
            "tmux_sessions_active": self._count_active_sessions(),
            "runs_recoverable": len(runs),
            "run_states": [r.state.value for r in runs],
            "message": "Scientific state reconstructed from persistent run records",
        }

    def _count_active_sessions(self) -> int:
        if not self._has_tmux():
            return 0
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return 0
        return len([line for line in result.stdout.strip().splitlines() if line.startswith("expcon-")])


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def create_workspace(workspace_root: Path | str, experiment_ref: str) -> dict[str, Any]:
    """Convenience function to create a workspace."""
    manager = WorkspaceManager(workspace_root)
    return manager.create_workspace(experiment_ref)


def attach_workspace(workspace_root: Path | str, experiment_ref: str) -> dict[str, Any]:
    """Convenience function to attach to a workspace."""
    manager = WorkspaceManager(workspace_root)
    return manager.attach_workspace(experiment_ref)
