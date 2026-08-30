"""Backend interface and implementations.

Backends are replaceable execution environments.  They may fail to execute
a frozen experiment, but they may never silently rewrite it.

Interface:
  submit(bundle, context) -> run_id
  status(run_id) -> RunStatus
  fetch(run_id, destination) -> evidence_path
  cancel(run_id) -> bool
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from expcon.util.env import redact_secrets
from expcon.backends.kaggle import KaggleApiTransport, KaggleCliTransport, KaggleTransportError


class BackendError(Exception):
    """Raised when a backend operation fails."""


@dataclass
class RunStatus:
    run_id: str
    state: str  # running, completed, failed, pending
    progress: float = 0.0
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    """Context for a backend run."""

    experiment_id: str
    version: str
    bundle_id: str
    contract_hash: str
    run_id: str = ""
    kernel: Optional[str] = None
    accelerator: str = "none"
    environment: dict[str, str] = field(default_factory=dict)
    extra_args: list[str] = field(default_factory=list)


class ExecutionBackend:
    """Capability-oriented backend interface.

    ``submit``/``cancel`` remain compatibility shims for the v0.1 runner.
    Provider adapters should expose resolution, provisioning, execution,
    observation, evidence retrieval, and release as separate operations.
    """

    name: str = "abstract"

    def capabilities(self) -> dict[str, Any]:
        """Describe public capability namespaces without provider inference."""
        return {"generic": {"execute": True}, "training": {}, "sampling": {},
                "artifacts": {}, "observability": {"status": True}}

    def resolve(self, requirements: dict[str, Any]) -> dict[str, Any]:
        """Determine whether the provider can satisfy frozen requirements."""
        return {"satisfied": True, "requirements": requirements}

    def provision(self, bundle: Path, context: RunContext) -> str:
        """Provision a provider run; retained as an explicit lifecycle hook."""
        return self.submit(bundle, context)

    def execute(self, bundle: Path, context: RunContext) -> str:
        """Execute a provisioned workload where the provider supports it."""
        return self.submit(bundle, context)

    def submit(self, bundle: Path, context: RunContext) -> str:
        """Submit a bundle for execution. Returns a run_id."""
        raise NotImplementedError

    def status(self, run_id: str) -> RunStatus:
        """Check the status of a run."""
        raise NotImplementedError

    def fetch(self, run_id: str, destination: Path) -> Path:
        """Fetch evidence from a completed run."""
        raise NotImplementedError

    def cancel(self, run_id: str) -> bool:
        """Cancel a running job."""
        raise NotImplementedError

    def release(self, run_id: str) -> bool:
        """Release provider resources after completion or a blocked run."""
        return self.cancel(run_id)


class LocalBackend(ExecutionBackend):
    """Local execution backend - runs stages directly via subprocess."""

    name = "local"

    def __init__(self, workspace_root: Path | str):
        self.workspace_root = Path(workspace_root).resolve()

    def capabilities(self) -> dict[str, Any]:
        return {"generic": {"execute": True}, "training": {"managed": False},
                "sampling": {"native": True}, "artifacts": {"fetch_checkpoint": True},
                "observability": {"status": True, "logs": True}}

    def submit(self, bundle: Path, context: RunContext) -> str:
        run_id = context.run_id if context.run_id else f"local-{context.experiment_id}-" + __import__("uuid").uuid4().hex[:8]
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Write run context
        (run_dir / "context.json").write_text(
            json.dumps(context.__dict__, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Execute stages from the bundle
        bundle_path = Path(bundle)
        manifest_path = bundle_path / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        stages = self._extract_stages_from_contract(bundle_path)
        results = []
        overall_success = True

        for stage in stages:
            stage_result = self._execute_stage(stage, bundle_path, run_dir, context)
            results.append(stage_result)
            if not stage_result.success:
                overall_success = False
                break

        # Write results
        (run_dir / "results.json").write_text(
            json.dumps(
                {"run_id": run_id, "success": overall_success, "stages": [r.to_dict() for r in results]},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        # Write status file
        status = "completed" if overall_success else "failed"
        (run_dir / "status.txt").write_text(status, encoding="utf-8")

        return run_id

    def _extract_stages_from_contract(self, bundle_path: Path) -> list[dict[str, Any]]:
        resolved = bundle_path / "resolved_contract.json"
        if resolved.exists():
            contract = json.loads(resolved.read_text(encoding="utf-8"))
            return contract.get("execution", {}).get("stages", [])
        return []

    def _execute_stage(
        self, stage: dict[str, Any], bundle_path: Path, run_dir: Path, context: RunContext
    ) -> "StageResult":
        from expcon.runner.runner import StageResult

        stage_id = stage.get("id", "unknown")
        entrypoint = stage.get("entrypoint", "")

        # Find the entrypoint script in the bundle
        runner_dir = bundle_path / "runner"
        script_path = runner_dir / Path(entrypoint).name

        stage_output_dir = run_dir / "stages" / stage_id
        stage_output_dir.mkdir(parents=True, exist_ok=True)

        if not script_path.exists():
            return StageResult(
                stage_id=stage_id,
                success=False,
                output="",
                error=f"Entrypoint not found: {script_path}",
            )

        try:
            result = subprocess.run(
                [sys.executable, str(script_path), "--bundle-root", str(bundle_path), "--output-root", str(stage_output_dir)],
                capture_output=True,
                text=True,
                cwd=str(bundle_path),
                timeout=300,
                env=self._clean_env(),
            )
            return StageResult(
                stage_id=stage_id,
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else "",
            )
        except subprocess.TimeoutExpired:
            return StageResult(
                stage_id=stage_id,
                success=False,
                output="",
                error="Stage timed out after 300s",
            )
        except Exception as exc:
            return StageResult(
                stage_id=stage_id,
                success=False,
                output="",
                error=str(exc),
            )

    def _clean_env(self) -> dict[str, str]:
        """Return a clean environment with secrets redacted."""
        env = os.environ.copy()
        # Remove any keys that look like secrets
        for key in list(env.keys()):
            if any(p.search(key) for p in [
                __import__("re").compile(r"(?i)api[_-]?key"),
                __import__("re").compile(r"(?i)secret"),
                __import__("re").compile(r"(?i)token"),
                __import__("re").compile(r"(?i)password"),
            ]):
                env.pop(key, None)
        return env

    def status(self, run_id: str) -> RunStatus:
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        status_file = run_dir / "status.txt"
        if not status_file.exists():
            return RunStatus(run_id=run_id, state="pending", message="Run not found")
        status = status_file.read_text(encoding="utf-8").strip()
        results_file = run_dir / "results.json"
        if results_file.exists():
            results = json.loads(results_file.read_text(encoding="utf-8"))
            completed = sum(1 for s in results.get("stages", []) if s.get("success"))
            total = len(results.get("stages", []))
            return RunStatus(
                run_id=run_id,
                state=status,
                progress=completed / total if total > 0 else 0.0,
                message=f"{completed}/{total} stages completed",
                details=results,
            )
        return RunStatus(run_id=run_id, state=status, message=status)

    def fetch(self, run_id: str, destination: Path) -> Path:
        """Fetch evidence from a completed local run."""
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)

        # Copy stage outputs
        stages_dir = run_dir / "stages"
        if stages_dir.exists():
            evidence_dir = dest / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            for stage_dir in stages_dir.iterdir():
                if stage_dir.is_dir():
                    target = evidence_dir / stage_dir.name
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(stage_dir, target)

        # Copy results
        results_file = run_dir / "results.json"
        if results_file.exists():
            shutil.copy2(results_file, dest / "evidence" / "results.json")

        return dest / "evidence"

    def cancel(self, run_id: str) -> bool:
        # Local runs are synchronous; cancel is a no-op
        return True


class KaggleBackend(ExecutionBackend):
    """Kaggle execution backend - wraps the Kaggle CLI.

    Does not store credentials.  Uses structured subprocess invocation.
    """

    name = "kaggle"

    def __init__(self, workspace_root: Path | str, api: KaggleApiTransport | None = None,
                 cli: KaggleCliTransport | None = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.kaggle_bin = os.environ.get("KAGGLE_BIN", "kaggle")
        self.api = api or KaggleApiTransport()
        self.cli = cli or KaggleCliTransport(self.kaggle_bin)

    def capabilities(self) -> dict[str, Any]:
        return {"generic": {"execute": True}, "training": {"managed": False},
                "sampling": {"native": False}, "artifacts": {"fetch_checkpoint": True},
                "observability": {"status": True, "logs": True},
                "competition": {"submit": bool(self.cli.capabilities().get("competition.submit"))}}

    def submit(self, bundle: Path, context: RunContext) -> str:
        import uuid

        run_id = context.run_id if context.run_id else f"kaggle-{context.experiment_id}-{uuid.uuid4().hex[:8]}"
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Write run context
        (run_dir / "context.json").write_text(
            json.dumps(context.__dict__, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Prepare Kaggle execution directory
        kaggle_work = run_dir / "kaggle_work"
        kaggle_work.mkdir(parents=True, exist_ok=True)

        # Copy bundle contents
        bundle_path = Path(bundle)
        for item in bundle_path.iterdir():
            if item.is_dir():
                shutil.copytree(item, kaggle_work / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, kaggle_work / item.name)

        # Write kernel metadata
        kernel_ref = context.kernel or f"{os.environ.get('KAGGLE_USERNAME', 'user')}/{run_id}"
        if not _valid_kaggle_ref(kernel_ref):
            raise BackendError("Invalid Kaggle kernel ref; expected owner/slug")
        kernel_metadata = {
            "id": kernel_ref,
            "title": run_id,
            "code_file": "runner/kernel.py",
            "language": "python",
            "kernel_type": "notebook",
            "is_private": True,
            "enable_gpu": context.accelerator != "none",
            "enable_tpu": False,
            "enable_internet": False,
            "dataset_sources": context.environment.get("dataset_sources", []),
            "competition_sources": context.environment.get("competition_sources", []),
            "kernel_sources": context.environment.get("kernel_sources", []),
            "model_sources": context.environment.get("model_sources", []),
        }
        (kaggle_work / "kernel-metadata.json").write_text(
            json.dumps(kernel_metadata, indent=2) + "\n", encoding="utf-8"
        )

        # Generate a simple kernel runner script
        kernel_script = kaggle_work / "runner" / "kernel.py"
        kernel_script.parent.mkdir(exist_ok=True)
        kernel_script.write_text(
            self._generate_kernel_script(context), encoding="utf-8"
        )

        # Submit via Kaggle CLI (if available)
        kaggle_available = bool(self.cli.capabilities()["installed"])
        if kaggle_available:
            try:
                self.cli.push_kernel(kaggle_work)
                (run_dir / "kaggle_submitted").write_text("true", encoding="utf-8")
                remote = self._resolve_remote_identity(kernel_ref, context, kernel_metadata)
                (run_dir / "kaggle.json").write_text(json.dumps(remote, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            except Exception as exc:
                (run_dir / "kaggle_submitted").write_text("false", encoding="utf-8")
                (run_dir / "kaggle_error.txt").write_text(str(exc), encoding="utf-8")
                raise
        else:
            # Kaggle CLI not available - simulate for testing
            (run_dir / "kaggle_submitted").write_text("simulated", encoding="utf-8")

        (run_dir / "status.txt").write_text("running", encoding="utf-8")

        return run_id

    def _resolve_remote_identity(self, kernel_ref: str, context: RunContext, metadata: dict[str, Any]) -> dict[str, Any]:
        """Bind this run to an exact API-reported kernel version or fail closed."""
        observed = self.api.inspect_kernel(kernel_ref)
        version = next((observed.get(key) for key in ("versionNumber", "version", "kernelVersionNumber") if observed.get(key) is not None), None)
        if version is None:
            raise BackendError("REMOTE_IDENTITY_UNRESOLVED: Kaggle did not expose an exact kernel version")
        owner, slug = kernel_ref.split("/", 1)
        return redact_secrets({
            "backend": "kaggle", "identity_source": "public_api",
            "contract_sha256": context.contract_hash, "bundle_sha256": context.bundle_id,
            "remote": {"kernel": {"owner": owner, "slug": slug, "ref": kernel_ref,
                                     "id": observed.get("id", observed.get("kernelId")), "version": version},
                       "session": {"id": observed.get("sessionId"), "status": observed.get("status")},
                       "runtime": {"machine_shape": observed.get("machineType", metadata.get("machine_type")),
                                   "enable_gpu": metadata["enable_gpu"], "enable_tpu": metadata["enable_tpu"],
                                   "enable_internet": metadata["enable_internet"]},
                       "sources": {"datasets": metadata["dataset_sources"], "competitions": metadata["competition_sources"],
                                   "kernels": metadata["kernel_sources"], "models": metadata["model_sources"]}}})

    def _generate_kernel_script(self, context: RunContext) -> str:
        return f'''#!/usr/bin/env python3
"""Auto-generated Kaggle kernel runner for {context.experiment_id}/{context.version}."""
import json
import os
import sys
import subprocess
from pathlib import Path

# Run the experiment stage
bundle_root = Path("/kaggle/working")
output_root = Path("/kaggle/working") / "{context.experiment_id}_outputs"
output_root.mkdir(parents=True, exist_ok=True)

results = {{
    "experiment_id": "{context.experiment_id}",
    "version": "{context.version}",
    "bundle_id": "{context.bundle_id}",
    "status": "completed",
    "outputs": [],
}}

# Try to run declared stages
runner_dir = bundle_root / "runner"
if runner_dir.exists():
    for script in sorted(runner_dir.glob("*.py")):
        try:
            proc = subprocess.run(
                [sys.executable, str(script), "--bundle-root", str(bundle_root), "--output-root", str(output_root)],
                capture_output=True, text=True, timeout=600, cwd=str(bundle_root)
            )
            results["outputs"].append({{
                "stage": script.name,
                "success": proc.returncode == 0,
                "stdout": proc.stdout[-5000:] if proc.stdout else "",
                "stderr": proc.stderr[-5000:] if proc.stderr else "",
            }})
        except Exception as exc:
            results["outputs"].append({{"stage": script.name, "success": False, "error": str(exc)}})

# Write results
(output_root / "kaggle_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))
'''

    def status(self, run_id: str) -> RunStatus:
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        status_file = run_dir / "status.txt"
        if not status_file.exists():
            return RunStatus(run_id=run_id, state="pending", message="Run not found")

        status = status_file.read_text(encoding="utf-8").strip()

        remote_record = run_dir / "kaggle.json"
        if remote_record.exists():
            remote = json.loads(remote_record.read_text(encoding="utf-8"))
            ref = remote["remote"]["kernel"]["ref"]
            try:
                observed = self.api.kernel_status(ref)
                status = str(observed.get("status", observed.get("state", status))).lower()
            except KaggleTransportError:
                # Explicit fallback: the remote identity stays API-bound, but
                # current operational status may come from the official CLI.
                output = self.cli.kernel_status(ref).lower()
                if "complete" in output: status = "completed"
                elif "error" in output or "failed" in output: status = "failed"
            except Exception:
                pass

        # Check for output files
        kaggle_work = run_dir / "kaggle_work"
        if (kaggle_work / "kaggle_results.json").exists():
            status = "completed"

        return RunStatus(run_id=run_id, state=status, message=f"Kaggle run: {status}")

    def fetch(self, run_id: str, destination: Path) -> Path:
        """Fetch evidence from a Kaggle run."""
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)
        evidence_dir = dest / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        remote_record = run_dir / "kaggle.json"
        if remote_record.exists():
            # The CLI's documented output command fetches *latest* output;
            # it cannot prove an older bound version, so refuse it here.
            raise BackendError("OUTPUT_VERSION_AMBIGUOUS: CLI output fetch is latest-only for an API-bound kernel version")

        # Copy any local results
        kaggle_work = run_dir / "kaggle_work"
        if kaggle_work.exists():
            for item in kaggle_work.iterdir():
                if item.is_file():
                    shutil.copy2(item, evidence_dir / item.name)

        # If no evidence was fetched, create a placeholder
        if not any(evidence_dir.iterdir()):
            (evidence_dir / "kaggle_results.json").write_text(
                json.dumps({"run_id": run_id, "status": "no_output_retrieved", "note": "Kaggle output not available"}),
                encoding="utf-8",
            )

        return evidence_dir

    def cancel(self, run_id: str) -> bool:
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        status_file = run_dir / "status.txt"
        if status_file.exists():
            status_file.write_text("failed", encoding="utf-8")
        return True

    def _clean_env(self) -> dict[str, str]:
        """Return a clean environment with secrets redacted."""
        env = os.environ.copy()
        import re

        secret_keys = [
            re.compile(r"(?i)api[_-]?key"),
            re.compile(r"(?i)secret"),
            re.compile(r"(?i)token"),
            re.compile(r"(?i)password"),
            re.compile(r"(?i)credential"),
            re.compile(r"(?i)kaggle.*source"),
        ]
        for key in list(env.keys()):
            if any(p.search(key) for p in secret_keys):
                env.pop(key, None)
        return env


def _valid_kaggle_ref(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}/[A-Za-z0-9][A-Za-z0-9_-]{0,62}", value))
