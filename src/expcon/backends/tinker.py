"""Optional adapter for the public Tinker SDK and CLI.

Tinker is a managed LLM post-training service, not a generic remote-shell
backend.  Expcon runs the frozen local driver; that driver owns documented
``TrainingClient``/``SamplingClient`` calls and reports stable remote identity.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from expcon.artifacts.artifact import ArtifactRegistry
from expcon.hashing.manifest import compute_directory_manifest, manifest_hash
from expcon.runner.backends import BackendError, ExecutionBackend, LocalBackend, RunContext, RunStatus
from expcon.util.env import redact_secrets
from expcon.util.path import safe_extract_zip


class TinkerError(BackendError):
    """A typed, credential-safe Tinker integration error."""


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return redact_secrets(value)
    if hasattr(value, "model_dump"):
        return redact_secrets(value.model_dump())
    if hasattr(value, "to_dict"):
        return redact_secrets(value.to_dict())
    return redact_secrets(dict(getattr(value, "__dict__", {})))


def _result(value: Any) -> Any:
    """Resolve only documented SDK futures, preserving ordinary responses."""
    return value.result() if hasattr(value, "result") and callable(value.result) else value


class TinkerSdkTransport:
    """Small public-SDK transport; no credentials or internal SDK state persist."""

    def __init__(self, sdk: Any | None = None):
        self.sdk: Any = sdk
        if sdk is None:
            try:
                self.sdk = importlib.import_module("tinker")
            except ImportError:
                self.sdk = None

    @property
    def available(self) -> bool:
        return self.sdk is not None

    @property
    def version(self) -> str | None:
        if not self.available:
            return None
        return str(getattr(self.sdk, "__version__", None) or self._installed_version() or "unknown")

    @staticmethod
    def _installed_version() -> str | None:
        try:
            return importlib.metadata.version("tinker")
        except importlib.metadata.PackageNotFoundError:
            return None

    @property
    def configured(self) -> bool:
        return bool(os.environ.get("TINKER_API_KEY"))

    def service(self) -> Any:
        if not self.available:
            raise TinkerError("TINKER_SDK_UNAVAILABLE")
        if not self.configured:
            raise TinkerError("TINKER_AUTH_UNAVAILABLE")
        try:
            return self.sdk.ServiceClient()
        except Exception as exc:
            raise self._error(exc) from exc

    def _error(self, exc: Exception) -> TinkerError:
        name = type(exc).__name__.lower()
        text = str(exc).lower()
        if "permission" in name or "permission" in text or "forbidden" in text:
            return TinkerError("TINKER_PERMISSION_DENIED")
        if "auth" in name or "auth" in text or "unauthorized" in text:
            return TinkerError("TINKER_AUTH_UNAVAILABLE")
        if "rate" in name or "429" in text:
            return TinkerError("TINKER_RATE_LIMITED")
        if "connection" in name or "timeout" in name or "unavailable" in text:
            return TinkerError("TINKER_SERVICE_UNAVAILABLE")
        return TinkerError(f"TINKER_SERVICE_ERROR: {redact_secrets(str(exc))[:300]}")

    def diagnostics(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sdk_installed": self.available,
            "sdk_version": self.version,
            "authenticated": False,
            "reachable": False,
            "capabilities": {},
            "principal": None,
        }
        if not self.available or not self.configured:
            result["reason"] = "TINKER_SDK_UNAVAILABLE" if not self.available else "TINKER_AUTH_UNAVAILABLE"
            return result
        try:
            service = self.service()
            result["capabilities"] = _as_dict(_result(service.get_server_capabilities()))
            rest = service.create_rest_client()
            result["principal"] = _as_dict(_result(rest.whoami()))
            result["authenticated"] = True
            result["reachable"] = True
        except TinkerError as exc:
            result["reason"] = str(exc)
        return redact_secrets(result)

    def rest(self) -> Any:
        try:
            return self.service().create_rest_client()
        except TinkerError:
            raise
        except Exception as exc:
            raise self._error(exc) from exc

    def list_training_runs(self) -> dict[str, Any]:
        try:
            return _as_dict(_result(self.rest().list_training_runs()))
        except Exception as exc:
            raise self._error(exc) from exc

    def get_training_run(self, training_run_id: str) -> dict[str, Any]:
        try:
            return _as_dict(_result(self.rest().get_training_run(training_run_id)))
        except Exception as exc:
            raise self._error(exc) from exc

    def list_sessions(self) -> dict[str, Any]:
        try:
            return _as_dict(_result(self.rest().list_sessions()))
        except Exception as exc:
            raise self._error(exc) from exc

    def get_session(self, session_id: str) -> dict[str, Any]:
        try:
            return _as_dict(_result(self.rest().get_session(session_id)))
        except Exception as exc:
            raise self._error(exc) from exc

    def list_checkpoints(self, training_run_id: str | None = None) -> dict[str, Any]:
        try:
            rest = self.rest()
            response = rest.list_checkpoints(training_run_id) if training_run_id else rest.list_user_checkpoints()
            return _as_dict(_result(response))
        except Exception as exc:
            raise self._error(exc) from exc

    def checkpoint_info(self, tinker_path: str) -> dict[str, Any]:
        if not tinker_path.startswith("tinker://"):
            raise TinkerError("TINKER_CHECKPOINT_PATH_INVALID")
        try:
            return _as_dict(_result(self.rest().get_weights_info_by_tinker_path(tinker_path)))
        except Exception as exc:
            raise self._error(exc) from exc

    def checkpoint_archive_url(self, tinker_path: str) -> str:
        if not tinker_path.startswith("tinker://"):
            raise TinkerError("TINKER_CHECKPOINT_PATH_INVALID")
        try:
            response = _result(self.rest().get_checkpoint_archive_url_from_tinker_path(tinker_path))
            raw = response if isinstance(response, dict) else dict(getattr(response, "__dict__", {}))
            url = raw.get("url") or raw.get("archive_url") or raw.get("archiveUrl")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise TinkerError("TINKER_CHECKPOINT_MISSING")
            return url
        except TinkerError:
            raise
        except Exception as exc:
            raise self._error(exc) from exc

    def export_session_trace(self, session_id: str) -> dict[str, Any]:
        try:
            return _as_dict(_result(self.rest().export_session_trace(session_id)))
        except Exception as exc:
            raise self._error(exc) from exc

    def billing_usage(self) -> dict[str, Any]:
        raise TinkerError("TINKER_BILLING_DATE_RANGE_REQUIRED")


class TinkerCliTransport:
    """Official CLI capability detection; SDK remains canonical for state reads."""

    def __init__(self, executable: str = "tinker"):
        self.executable = executable

    def capabilities(self) -> dict[str, Any]:
        installed = shutil.which(self.executable) is not None
        return {"installed": installed, "version": self.version() if installed else None,
                "format_json": installed, "checkpoint_diagnostics": installed,
                "session_diagnostics": installed, "billing": installed}

    def version(self) -> str | None:
        if not shutil.which(self.executable):
            return None
        try:
            result = subprocess.run([self.executable, "version"], capture_output=True, text=True, timeout=15)
            return redact_secrets(result.stdout.strip() or result.stderr.strip()) if result.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None


class TinkerCompatibleInferenceTransport:
    """Provenance validator for Tinker's documented beta protocol wrappers.

    The frozen driver, not Expcon, invokes a compatible client.  This class
    prevents records from relabelling Tinker sampling as OpenAI or Anthropic and
    deliberately provides no protocol fallback.
    """

    _protocols = {"native_sampling", "openai_compatible", "anthropic_compatible"}

    def identity(self, protocol: str, model_path: str, sampling_config: dict[str, Any]) -> dict[str, Any]:
        if protocol not in self._protocols:
            raise TinkerError("TINKER_INFERENCE_PROTOCOL_UNSUPPORTED")
        if protocol != "native_sampling" and not model_path.startswith("tinker://"):
            raise TinkerError("TINKER_CHECKPOINT_PATH_INVALID")
        return {"provider": "tinker", "protocol": protocol, "model_path": model_path,
                "sampling_config": redact_secrets(sampling_config)}


def _identity(data: dict[str, Any], context: RunContext, sdk_version: str | None) -> dict[str, Any]:
    """Allowlist stable driver-reported Tinker observations."""
    remote = {key: data.get(key) for key in (
        "project_id", "session_id", "training_run_id", "model_id", "base_model",
        "lora", "sampler_id", "checkpoints", "training_step",
    ) if data.get(key) is not None}
    if not remote.get("training_run_id") and not remote.get("session_id"):
        raise TinkerError("TINKER_REMOTE_IDENTITY_UNRESOLVED")
    result = {
        "backend": "tinker", "contract_sha256": context.contract_hash,
        "bundle_sha256": context.bundle_id, "sdk_version": sdk_version,
        "driver_identity": {"bundle_id": context.bundle_id}, "remote": remote,
    }
    sampling = data.get("sampling")
    if isinstance(sampling, dict):
        result["inference"] = TinkerCompatibleInferenceTransport().identity(
            str(sampling.get("protocol", "native_sampling")),
            str(sampling.get("model_path", remote.get("sampler_id", ""))),
            dict(sampling.get("config", {})),
        )
    return redact_secrets(result)


def validate_resume_mode(declared: str | None, observed: str | None) -> None:
    """Fail closed when a frozen resume mode cannot be honoured exactly."""
    valid = {"weights_only", "weights_and_optimizer"}
    if declared is not None and declared not in valid:
        raise TinkerError("TINKER_RESUME_MODE_MISMATCH")
    if declared is not None and declared != observed:
        raise TinkerError("TINKER_RESUME_MODE_MISMATCH")


def validate_driver_identity(contract: dict[str, Any], observed: dict[str, Any]) -> None:
    """Reject a driver that bound a different frozen model or LoRA declaration."""
    training = contract.get("training_service", {})
    expected_model = training.get("base_model") or contract.get("model", {}).get("base_model")
    if expected_model and observed.get("base_model") != expected_model:
        raise TinkerError("TINKER_MODEL_IDENTITY_MISMATCH")
    expected_lora = training.get("lora")
    if expected_lora is not None and observed.get("lora") != expected_lora:
        raise TinkerError("TINKER_LORA_CONFIGURATION_MISMATCH")


class _TinkerDriverExecutor(LocalBackend):
    """Local frozen driver executor that passes only Tinker's credential in memory."""

    def _clean_env(self) -> dict[str, str]:
        env = super()._clean_env()
        if os.environ.get("TINKER_API_KEY"):
            env["TINKER_API_KEY"] = os.environ["TINKER_API_KEY"]
        return env


class TinkerBackend(ExecutionBackend):
    """Managed LLM training backend driven through the frozen local Python loop."""

    name = "tinker"

    def __init__(self, workspace_root: Path | str, sdk: TinkerSdkTransport | None = None,
                 cli: TinkerCliTransport | None = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.sdk = sdk or TinkerSdkTransport()
        self.cli = cli or TinkerCliTransport()

    def capabilities(self) -> dict[str, Any]:
        return {"generic": {"execute": False}, "training": {"managed": self.sdk.available,
                "forward": self.sdk.available, "forward_backward": self.sdk.available,
                "optimizer_step": self.sdk.available, "resume_weights": self.sdk.available,
                "resume_full_state": self.sdk.available},
                "sampling": {"native": self.sdk.available, "openai_compatible": "beta",
                             "anthropic_compatible": "beta"},
                "artifacts": {"save_training_state": self.sdk.available,
                              "save_sampler_weights": self.sdk.available,
                              "list_checkpoints": self.sdk.available,
                              "fetch_checkpoint": self.sdk.available},
                "observability": {"inspect_run": self.sdk.available, "list_runs": self.sdk.available,
                                   "inspect_session": self.sdk.available, "export_session_trace": self.sdk.available}}

    def resolve(self, requirements: dict[str, Any]) -> dict[str, Any]:
        diagnostics = self.sdk.diagnostics()
        if not diagnostics["sdk_installed"]:
            return {"satisfied": False, "reason": "TINKER_SDK_UNAVAILABLE", "capabilities": self.capabilities()}
        if not diagnostics["authenticated"]:
            return {"satisfied": False, "reason": diagnostics.get("reason", "TINKER_AUTH_UNAVAILABLE"), "capabilities": self.capabilities()}
        return {"satisfied": True, "requirements": requirements, "capabilities": self.capabilities(),
                "server": diagnostics["capabilities"]}

    def submit(self, bundle: Path, context: RunContext) -> str:
        resolved = self.resolve(context.environment.get("requirements", {}))
        if not resolved["satisfied"]:
            raise TinkerError(f"BLOCKED: {resolved['reason']}")
        run_id = context.run_id or f"tinker-{context.experiment_id}-{uuid.uuid4().hex[:8]}"
        context.run_id = run_id
        contract_data: dict[str, Any] = {}
        declared_resume: str | None = None
        resolved_contract = Path(bundle) / "resolved_contract.json"
        if resolved_contract.exists():
            try:
                contract_data = json.loads(resolved_contract.read_text(encoding="utf-8"))
                declared_resume = contract_data.get("training_service", {}).get("resume", {}).get("mode")
            except (OSError, ValueError):
                raise TinkerError("TINKER_CONTRACT_INVALID")
        driver = _TinkerDriverExecutor(self.workspace_root)
        driver.submit(bundle, context)
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        identities = sorted(run_dir.glob("stages/**/tinker_identity.json"))
        if not identities:
            raise TinkerError("TINKER_REMOTE_IDENTITY_UNRESOLVED")
        try:
            raw = json.loads(identities[-1].read_text(encoding="utf-8"))
            validate_resume_mode(declared_resume, raw.get("resume_mode"))
            validate_driver_identity(contract_data, raw)
            record = _identity(raw, context, self.sdk.version)
        except (OSError, ValueError, TinkerError) as exc:
            raise TinkerError("TINKER_REMOTE_IDENTITY_UNRESOLVED") from exc
        (run_dir / "tinker.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return run_id

    def status(self, run_id: str) -> RunStatus:
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        record_path = run_dir / "tinker.json"
        if not record_path.exists():
            return RunStatus(run_id=run_id, state="pending", message="Tinker identity not yet recorded")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        remote = record.get("remote", {})
        details: dict[str, Any] = {"remote": remote}
        training_run_id = remote.get("training_run_id")
        if training_run_id:
            try:
                details["training_run"] = self.sdk.get_training_run(training_run_id)
            except TinkerError as exc:
                details["observation_error"] = str(exc)
        status_file = run_dir / "status.txt"
        state = status_file.read_text(encoding="utf-8").strip() if status_file.exists() else "running"
        return RunStatus(run_id=run_id, state=state, message=f"Tinker driver: {state}", details=redact_secrets(details))

    def fetch(self, run_id: str, destination: Path) -> Path:
        return _TinkerDriverExecutor(self.workspace_root).fetch(run_id, destination)

    def cancel(self, run_id: str) -> bool:
        return False

    def fetch_checkpoint(self, tinker_path: str, destination: Path, *, run_id: str | None = None,
                         experiment_id: str | None = None) -> dict[str, Any]:
        """Download a checkpoint archive safely and register it only with a run."""
        archive_url = self.sdk.checkpoint_archive_url(tinker_path)
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / "checkpoint.zip"
        try:
            with urllib.request.urlopen(archive_url, timeout=120) as response:  # nosec B310: signed HTTPS URL from Tinker SDK
                archive.write_bytes(response.read())
            extracted = safe_extract_zip(archive, destination / "checkpoint")
        except Exception as exc:
            raise TinkerError("TINKER_CHECKPOINT_FETCH_FAILED") from exc
        finally:
            archive.unlink(missing_ok=True)
        root = destination / "checkpoint"
        if not extracted:
            raise TinkerError("TINKER_CHECKPOINT_FETCH_FAILED")
        manifest = compute_directory_manifest(root)
        manifest_file = destination / "checkpoint.manifest.json"
        manifest_file.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result: dict[str, Any] = {"tinker_path": tinker_path, "files": extracted,
                                  "manifest": manifest.to_dict(), "manifest_sha256": manifest_hash(manifest),
                                  "manifest_path": str(manifest_file)}
        if run_id and experiment_id:
            registry = ArtifactRegistry(self.workspace_root / ".expcon" / "runs" / run_id)
            artifact = registry.register(manifest_file, "tinker_checkpoint", experiment_id, run_id,
                                         metadata={"tinker_path": tinker_path, "manifest_sha256": result["manifest_sha256"]})
            result["artifact"] = artifact.to_dict()
        return redact_secrets(result)
