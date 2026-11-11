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
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from expcon.util.env import redact_secrets
from expcon.util.path import safe_identifier
from expcon.util.json_io import atomic_json, file_lock
from expcon.backends.kaggle import KaggleApiTransport, KaggleCliTransport, KaggleTransportError
from expcon.hashing.digest import file_sha256
from expcon.runner.invocation import InvocationError, resolve_invocation


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
    environment: dict[str, Any] = field(default_factory=dict)
    extra_args: list[str] = field(default_factory=list)
    input_bindings: dict[str, str] = field(default_factory=dict)
    environment_bindings: dict[str, str] = field(default_factory=dict)
    interpreter: Optional[str] = None
    environment_attestation: dict[str, Any] = field(default_factory=dict)


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
        if not getattr(context, "run_id", ""):
            context.run_id = f"{self.name}-{context.experiment_id}-" + __import__("uuid").uuid4().hex[:8]
        safe_identifier(context.run_id)
        lock = self.workspace_root / ".expcon/runs" / context.run_id / ".submission.lock"
        with file_lock(lock):
            return self._submit_once(bundle, context)

    def _submit_once(self, bundle: Path, context: RunContext) -> str:
        run_id = context.run_id if context.run_id else f"local-{context.experiment_id}-" + __import__("uuid").uuid4().hex[:8]
        safe_identifier(run_id)
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        safe_identifier(run_id)
        attempt = run_dir / "submission.json"
        if attempt.exists():
            previous = json.loads(attempt.read_text())
            if previous.get("bundle_id") != context.bundle_id or previous.get("contract_hash") != context.contract_hash:
                raise BackendError("DUPLICATE_SUBMISSION_IDENTITY_MISMATCH")
            if (run_dir / "status.txt").is_file():
                return run_id
            raise BackendError("BLOCKED: SUBMISSION_OUTCOME_UNKNOWN; reconcile, never automatically resubmit")
        atomic_json(attempt, {"run_id": run_id, "bundle_id": context.bundle_id,
                              "contract_hash": context.contract_hash, "state": "ATTEMPTED"})

        # Write run context
        (run_dir / "context.json").write_text(
            json.dumps({**redact_secrets({k: v for k, v in context.__dict__.items() if k != "environment_bindings"}), "environment_binding_keys": sorted(context.environment_bindings)}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Execute stages from the bundle
        bundle_path = Path(bundle)
        manifest_path = bundle_path / "bundle_manifest.json"
        json.loads(manifest_path.read_text(encoding="utf-8"))

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
            execution = contract.get("execution", {})
            default_invocation = execution.get("invocation")
            pending = [{**stage, "_invocation": stage.get("invocation", default_invocation)}
                       for stage in execution.get("stages", [])]
            ordered = []
            completed: set[str] = set()
            while pending:
                ready = next((stage for stage in pending if set(stage.get("requires", [])) <= completed), None)
                if ready is None:
                    raise BackendError("Invalid or unsupported stage dependency graph")
                safe_identifier(ready["id"])
                ordered.append(ready)
                completed.add(ready["id"])
                pending.remove(ready)
            return ordered
        return []

    def _execute_stage(
        self, stage: dict[str, Any], bundle_path: Path, run_dir: Path, context: RunContext
    ) -> Any:
        from expcon.runner.runner import StageResult

        stage_id = safe_identifier(stage.get("id", "unknown"))
        entrypoint = stage.get("entrypoint", "")

        # Find the entrypoint script in the bundle
        runner_dir = bundle_path / "runner"
        entrypoint_path = Path(entrypoint)
        if entrypoint_path.is_absolute() or ".." in entrypoint_path.parts:
            return StageResult(
                stage_id=stage_id,
                success=False,
                output="",
                error=f"Unsafe bundle entrypoint: {entrypoint}",
            )
        script_path = runner_dir / entrypoint_path

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
            invocation = resolve_invocation(
                stage.get("_invocation"), bundle_root=bundle_path, output_root=stage_output_dir,
                input_bindings=context.input_bindings, environment_bindings=context.environment_bindings,
            )
        except InvocationError as exc:
            return StageResult(stage_id=stage_id, success=False, output="", error=f"Invocation resolution failed: {exc}")
        (stage_output_dir / "invocation.json").write_text(
            json.dumps({
                **invocation.attestation,
                "runtime_environment": getattr(context, "environment_attestation", {}),
                "python_executable": getattr(context, "interpreter", None) or sys.executable,
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        command = [getattr(context, "interpreter", None) or sys.executable, str(script_path), *invocation.argv]
        process_record: dict[str, Any] = {
            "command": command,
            "cwd": str(bundle_path),
            "pythonpath": None,
            "spawn_attempted": True,
            "child_pid": None,
            "returncode": None,
            "exception": None,
        }
        try:
            source_root = bundle_path / "source"
            runtime_environment = {**self._clean_env(), **invocation.environment, "PYTHONDONTWRITEBYTECODE": "1"}
            if source_root.is_dir():
                # Always prefer the immutable bundled closure to the host checkout.
                runtime_environment["PYTHONPATH"] = str(source_root)
            process_record["pythonpath"] = runtime_environment.get("PYTHONPATH")
            started = time.monotonic()
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=str(bundle_path), env=runtime_environment,
            )
            process_record["dispatch_seconds"] = time.monotonic() - started
            process_record["child_pid"] = process.pid
            stdout, stderr = process.communicate(timeout=300)
            stdout, stderr = self._redact_output(stdout, context), self._redact_output(stderr, context)
            process_record["returncode"] = process.returncode
            process_record["duration_seconds"] = time.monotonic() - started
            (stage_output_dir / "stdout.log").write_text(stdout, encoding="utf-8")
            (stage_output_dir / "stderr.log").write_text(stderr, encoding="utf-8")
            (stage_output_dir / "process.json").write_text(
                json.dumps(process_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return StageResult(
                stage_id=stage_id,
                success=process.returncode == 0,
                output=stdout,
                error=stderr if process.returncode != 0 else "",
                duration_seconds=process_record["duration_seconds"],
            )
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            stdout, stderr = self._redact_output(stdout, context), self._redact_output(stderr, context)
            process_record.update({"returncode": process.returncode, "exception": "Stage timed out after 300s"})
            (stage_output_dir / "stdout.log").write_text(stdout, encoding="utf-8")
            (stage_output_dir / "stderr.log").write_text(stderr, encoding="utf-8")
            (stage_output_dir / "process.json").write_text(
                json.dumps(process_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return StageResult(
                stage_id=stage_id,
                success=False,
                output=stdout,
                error="Stage timed out after 300s",
            )
        except Exception as exc:
            process_record["exception"] = f"{type(exc).__name__}: {exc}"
            (stage_output_dir / "stdout.log").write_text("", encoding="utf-8")
            (stage_output_dir / "stderr.log").write_text(process_record["exception"], encoding="utf-8")
            (stage_output_dir / "process.json").write_text(
                json.dumps(process_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return StageResult(
                stage_id=stage_id,
                success=False,
                output="",
                error=str(exc),
            )

    @staticmethod
    def _redact_output(value: str, context: RunContext) -> str:
        value = redact_secrets(value)
        for secret in context.environment_bindings.values():
            if secret:
                value = value.replace(secret, "***REDACTED***")
        return value

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
        # Synchronous API has no safe cross-process cancellation handle.
        return False


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

    def preflight(self, bundle: Path) -> dict[str, Any]:
        """Fail before a remote run unless notebook custody can be proven."""
        api = self.api.capabilities()
        cli = self.cli.capabilities()
        if not cli.get("installed") or not cli.get("kernel.push"):
            raise BackendError("BLOCKED: BACKEND_CAPABILITY_MISMATCH: KAGGLE_PUSH_FAILURE")
        if not api.get("available"):
            raise BackendError("BLOCKED: BACKEND_CAPABILITY_MISMATCH: KAGGLE_API_UNAVAILABLE")
        try:
            self.api.authenticate()
        except KaggleTransportError as exc:
            raise BackendError(f"BLOCKED: BACKEND_CAPABILITY_MISMATCH: {exc}") from exc
        if not api.get("kernel.inspect") or not api.get("kernel.status"):
            raise BackendError("BLOCKED: BACKEND_CAPABILITY_MISMATCH: KAGGLE_VERSION_BINDING_FAILURE")
        if not api.get("output.version_safe"):
            raise BackendError("BLOCKED: BACKEND_CAPABILITY_MISMATCH: KAGGLE_OUTPUT_IDENTITY_FAILURE")
        payload = self._notebook_payload(Path(bundle))
        return {"status": "READY", "notebook": str(payload[0]), "metadata": str(payload[1]),
                "notebook_sha256": file_sha256(payload[0]), "metadata_sha256": file_sha256(payload[1])}

    @staticmethod
    def _notebook_payload(bundle: Path) -> tuple[Path, Path]:
        contract = json.loads((bundle / "resolved_contract.json").read_text(encoding="utf-8"))
        stages = contract.get("execution", {}).get("stages", [])
        if len(stages) != 1 or not str(stages[0].get("entrypoint", "")).endswith(".ipynb"):
            raise BackendError("KAGGLE_NOTEBOOK_DISPATCH_MISMATCH: exactly one .ipynb stage is required")
        relative = Path(stages[0]["entrypoint"])
        notebook = bundle / "runner" / relative
        metadata = notebook.parent / "kernel-metadata.json"
        if not notebook.is_file() or not metadata.is_file():
            raise BackendError("KAGGLE_NOTEBOOK_DISPATCH_MISMATCH: frozen notebook or kernel-metadata.json missing from bundle")
        try:
            parsed = json.loads(metadata.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BackendError("KAGGLE_NOTEBOOK_DISPATCH_MISMATCH: malformed kernel metadata") from exc
        if parsed.get("code_file") != notebook.name:
            raise BackendError("KAGGLE_NOTEBOOK_DISPATCH_MISMATCH: metadata code_file does not bind frozen notebook")
        return notebook, metadata

    def submit(self, bundle: Path, context: RunContext) -> str:
        if not getattr(context, "run_id", ""):
            context.run_id = f"{self.name}-{context.experiment_id}-" + __import__("uuid").uuid4().hex[:8]
        safe_identifier(context.run_id)
        lock = self.workspace_root / ".expcon/runs" / context.run_id / ".submission.lock"
        with file_lock(lock):
            return self._submit_once(bundle, context)

    def _submit_once(self, bundle: Path, context: RunContext) -> str:
        import uuid

        run_id = context.run_id if context.run_id else f"kaggle-{context.experiment_id}-{uuid.uuid4().hex[:8]}"
        safe_identifier(run_id)
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        safe_identifier(run_id)
        attempt = run_dir / "submission.json"
        if attempt.exists():
            previous = json.loads(attempt.read_text())
            if previous.get("bundle_id") != context.bundle_id or previous.get("contract_hash") != context.contract_hash:
                raise BackendError("DUPLICATE_SUBMISSION_IDENTITY_MISMATCH")
            if (run_dir / "status.txt").is_file():
                return run_id
            raise BackendError("BLOCKED: SUBMISSION_OUTCOME_UNKNOWN; reconcile, never automatically resubmit")
        atomic_json(attempt, {"run_id": run_id, "bundle_id": context.bundle_id,
                              "contract_hash": context.contract_hash, "state": "ATTEMPTED"})

        # Write run context
        (run_dir / "context.json").write_text(
            json.dumps({**redact_secrets({k: v for k, v in context.__dict__.items() if k != "environment_bindings"}), "environment_binding_keys": sorted(context.environment_bindings)}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Notebook-native transport: preserve the frozen artifact and its own
        # metadata verbatim; never generate a substitute Python runner.
        preflight = self.preflight(bundle)
        notebook, metadata_path = self._notebook_payload(Path(bundle))
        kaggle_work = run_dir / "kaggle_work"
        kaggle_work.mkdir(parents=True, exist_ok=True)
        shutil.copy2(notebook, kaggle_work / notebook.name)
        shutil.copy2(metadata_path, kaggle_work / "kernel-metadata.json")
        kernel_ref = context.kernel or json.loads(metadata_path.read_text(encoding="utf-8")).get("id")
        if not _valid_kaggle_ref(kernel_ref):
            raise BackendError("Invalid Kaggle kernel ref; expected owner/slug")
        kernel_metadata = json.loads((kaggle_work / "kernel-metadata.json").read_text(encoding="utf-8"))
        before = None
        try:
            before = self.api.inspect_kernel(kernel_ref).get("versionNumber")
        except KaggleTransportError:
            # A new private kernel may not yet exist; binding after push remains mandatory.
            pass

        # Submit via Kaggle CLI (if available)
        kaggle_available = bool(self.cli.capabilities()["installed"])
        if kaggle_available:
            try:
                push_log = self.cli.push_kernel(kaggle_work)
                (run_dir / "kaggle_submitted").write_text("true", encoding="utf-8")
                remote = self._resolve_remote_identity(kernel_ref, context, kernel_metadata, before)
                remote["frozen_payload"] = {**preflight, "push_diagnostic": push_log}
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

    def _resolve_remote_identity(self, kernel_ref: str, context: RunContext, metadata: dict[str, Any], before: Any = None) -> dict[str, Any]:
        """Bind this run to an exact API-reported kernel version or fail closed."""
        observed = self.api.inspect_kernel(kernel_ref)
        version = next((observed.get(key) for key in ("versionNumber", "version", "kernelVersionNumber") if observed.get(key) is not None), None)
        if version is None:
            raise BackendError("KAGGLE_VERSION_BINDING_FAILURE: Kaggle did not expose an exact kernel version")
        if before is not None and str(version) == str(before):
            raise BackendError("KAGGLE_VERSION_BINDING_FAILURE: push did not advance the observed version")
        owner, slug = kernel_ref.split("/", 1)
        return redact_secrets({
            "backend": "kaggle", "identity_source": "public_api",
            "contract_sha256": context.contract_hash, "bundle_sha256": context.bundle_id,
            "remote": {"kernel": {"owner": owner, "slug": slug, "ref": kernel_ref,
                                     "id": observed.get("id", observed.get("kernelId")), "version": version},
                       "session": {"id": observed.get("sessionId"), "status": observed.get("status")},
                       "runtime": {"machine_shape": observed.get("machineType", metadata.get("machine_shape")),
                                   "enable_gpu": metadata.get("enable_gpu"), "enable_tpu": metadata.get("enable_tpu"),
                                   "enable_internet": metadata.get("enable_internet")},
                       "sources": {"datasets": metadata.get("dataset_sources", []), "competitions": metadata.get("competition_sources", []),
                                   "kernels": metadata.get("kernel_sources", []), "models": metadata.get("model_sources", [])},
                       # Provider reporting is retained separately from the
                       # declaration.  The notebook remains responsible for
                       # checking mounted parent artifact hashes at runtime.
                       "kernel_source_binding": {
                           "declared": metadata.get("kernel_sources", []),
                           "provider_reported": observed.get("kernelSources", observed.get("kernel_sources")),
                       }}})

    def _execution_plan(self, bundle: Path, context: RunContext) -> list[dict[str, Any]]:
        """Resolve the same frozen stage protocol used by the local backend."""
        contract = json.loads((bundle / "resolved_contract.json").read_text(encoding="utf-8"))
        plan = []
        for stage in contract.get("execution", {}).get("stages", []):
            entrypoint = Path(stage["entrypoint"])
            if entrypoint.is_absolute() or ".." in entrypoint.parts:
                raise BackendError(f"Unsafe bundle entrypoint: {stage['entrypoint']}")
            invocation = resolve_invocation(
                stage.get("invocation", contract.get("execution", {}).get("invocation")),
                bundle_root=bundle,
                output_root=bundle / "candidate-output" / stage["id"],
                input_bindings=context.input_bindings,
                environment_bindings=context.environment_bindings,
            )
            plan.append({"id": stage["id"], "entrypoint": str(Path("runner") / entrypoint), "argv": invocation.argv,
                         "environment": invocation.environment, "attestation": invocation.attestation})
        return plan

    def _generate_kernel_script(self, context: RunContext, plan: list[dict[str, Any]]) -> str:
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

plan = {json.dumps(plan, sort_keys=True)}

# Try to run declared stages
for stage in plan:
    try:
        script = bundle_root / stage["entrypoint"]
        if not script.is_file(): raise RuntimeError(f"Entrypoint missing: {{script}}")
        env = {{**os.environ, **stage["environment"]}}
        source = bundle_root / "source"
        if source.is_dir(): env["PYTHONPATH"] = str(source)
        proc = subprocess.run(
            [sys.executable, str(script), *stage["argv"]], capture_output=True,
            text=True, timeout=600, cwd=str(bundle_root), env=env
        )
        results["outputs"].append({{
                "stage": stage["id"],
                "success": proc.returncode == 0,
                "stdout": proc.stdout[-5000:] if proc.stdout else "",
                "stderr": proc.stderr[-5000:] if proc.stderr else "",
        }})
    except Exception as exc:
        results["outputs"].append({{"stage": stage["id"], "success": False, "error": str(exc)}})

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
                if "complete" in output:
                    status = "completed"
                elif "error" in output or "failed" in output:
                    status = "failed"
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
            remote = json.loads(remote_record.read_text(encoding="utf-8"))
            kernel = remote["remote"]["kernel"]
            try:
                self.api.fetch_kernel_outputs(kernel["ref"], kernel["version"], evidence_dir)
            except KaggleTransportError as exc:
                raise BackendError(f"KAGGLE_OUTPUT_IDENTITY_FAILURE: {exc}") from exc
            artifacts = []
            for path in sorted(evidence_dir.rglob("*")):
                if path.is_file():
                    artifacts.append({
                        "path": str(path.relative_to(evidence_dir)),
                        "size_bytes": path.stat().st_size,
                        "sha256": file_sha256(path),
                        "kernel_version": kernel["version"],
                        "run_id": run_id,
                    })
            (evidence_dir / "artifact_custody.json").write_text(json.dumps({"artifacts": artifacts}, indent=2, sort_keys=True)+"\n", encoding="utf-8")
            return evidence_dir

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
        # No version-bound provider cancellation endpoint is implemented.
        # Never relabel a potentially running provider job as cancelled locally.
        return False

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
