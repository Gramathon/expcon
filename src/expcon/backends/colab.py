"""Official Google Colab Runtime API adapter.

This adapter deliberately manages runtimes only.  The public API exposes no
bundle/workload execution endpoint, and Expcon never uses ConnectionInfo as an
execution channel or persists its short-lived token.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from expcon.runner.backends import BackendError, ExecutionBackend, RunContext, RunStatus
from expcon.util.env import redact_secrets

COLAB_API = "https://colaboratory.googleapis.com"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ColabClientError(BackendError):
    """A rejected or unavailable Colab API request."""


class ColabApiClient:
    """Small stdlib client for the allowlisted official REST API."""

    def __init__(self, access_token: str | None = None, base_url: str = COLAB_API):
        self.access_token = access_token or os.environ.get("EXPCON_COLAB_ACCESS_TOKEN")
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.access_token:
            raise ColabClientError("Colab OAuth access token is not configured (set EXPCON_COLAB_ACCESS_TOKEN)")
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urlencode(query)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=payload, method=method)
        request.add_header("Authorization", f"Bearer {self.access_token}")
        request.add_header("Accept", "application/json")
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=30) as response:  # nosec B310: fixed HTTPS API endpoint
                return redact_secrets(json.loads(response.read().decode("utf-8")))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ColabClientError(f"Colab API {method} {path} failed: HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise ColabClientError(f"Colab API unavailable: {exc.reason}") from exc

    def runtime_specs(self) -> list[dict[str, Any]]:
        return self.request("GET", "/v1beta/runtimespecs").get("runtimeSpecs", [])

    def runtimes(self) -> list[dict[str, Any]]:
        return self.request("GET", "/v1beta/runtimes").get("runtimes", [])

    def runtime(self, runtime_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1beta/runtimes/{runtime_id}")

    def create_runtime(self, runtime: dict[str, Any], runtime_id: str) -> dict[str, Any]:
        return self.request("POST", "/v1beta/runtimes", runtime, {
            "requestId": str(uuid.uuid4()), "runtimeId": runtime_id,
        })

    def operation(self, name: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/{name.lstrip('/')}")

    def delete_runtime(self, runtime_id: str) -> dict[str, Any]:
        return self.request("DELETE", f"/v1beta/runtimes/{runtime_id}")

    def wait_operation(self, name: str, timeout_seconds: int = 300) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            operation = self.operation(name)
            if operation.get("done"):
                return operation
            if time.monotonic() >= deadline:
                raise ColabClientError(f"Timed out waiting for Colab operation {name}")
            time.sleep(2)


def _runtime_identity(runtime: dict[str, Any]) -> dict[str, Any]:
    """Extract stable provider observations and omit all ConnectionInfo."""
    spec = runtime.get("runtimeSpec", runtime.get("spec", {}))
    return redact_secrets({
        "runtime_id": runtime.get("name", runtime.get("runtimeId", "")).split("/")[-1],
        "runtime_spec": spec,
        "accelerator": spec.get("accelerator", spec.get("acceleratorType")),
        "shape": spec.get("shape", spec.get("runtimeShape")),
        "runtime_version": runtime.get("version", runtime.get("runtimeVersion", runtime.get("imageVersion"))),
        "state": runtime.get("state"),
        "observed_at": _now(),
    })


class ColabBackend(ExecutionBackend):
    """Provision and observe Colab runtimes through the official REST API."""

    name = "colab"

    def __init__(self, workspace_root: Path | str, client: ColabApiClient | None = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.client = client or ColabApiClient()

    def resolve(self, requirements: dict[str, Any]) -> dict[str, Any]:
        specs = self.client.runtime_specs()
        accelerator = requirements.get("accelerator", {}) if requirements else {}
        wanted = str(accelerator.get("variant", "")).upper()
        eligible = [spec for spec in specs if spec.get("eligible")]
        matches = [spec for spec in eligible if not wanted or wanted in json.dumps(spec.get("key", {})).upper()]
        return {"eligible_specs": redact_secrets(matches), "satisfied": bool(matches) if wanted else bool(eligible)}

    def submit(self, bundle: Path, context: RunContext) -> str:
        run_id = context.run_id or f"colab-{context.experiment_id}-{uuid.uuid4().hex[:8]}"
        requirements = context.environment.get("requirements", {}) if context.environment else {}
        resolution = self.resolve(requirements)
        if not resolution["satisfied"]:
            raise ColabClientError("BLOCKED: no eligible Colab runtime satisfies frozen execution requirements")
        selected = resolution["eligible_specs"][0]
        runtime_id = f"expcon-{run_id.lower()}"[:63]
        runtime_body = {"runtimeSpec": selected.get("key", selected)}
        operation = self.client.create_runtime(runtime_body, runtime_id)
        operation_name = operation.get("name", "")
        if not operation_name:
            raise ColabClientError("Colab create operation did not include an operation name")
        completed = self.client.wait_operation(operation_name)
        if completed.get("error"):
            raise ColabClientError(f"BLOCKED: Colab runtime creation failed: {completed['error']}")
        runtime = self.client.runtime(runtime_id)
        observation = _runtime_identity(runtime)
        if not observation.get("runtime_version"):
            raise ColabClientError("BLOCKED: Colab did not return an exact runtime image version")
        record = {
            "expcon_run_id": run_id,
            "experiment_id": context.experiment_id,
            "version": context.version,
            "contract_sha256": context.contract_hash,
            "bundle_sha256": context.bundle_id,
            "create_operation": operation_name,
            "created_at": _now(),
            "observations": [observation],
        }
        run_dir = self.workspace_root / ".expcon" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "colab.json").write_text(json.dumps(redact_secrets(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # There is intentionally no arbitrary-code execution call here.
        raise ColabClientError("BLOCKED: Colab Runtime API provisioned a runtime but exposes no bundle execution endpoint")

    def status(self, run_id: str) -> RunStatus:
        record_path = self.workspace_root / ".expcon" / "runs" / run_id / "colab.json"
        if not record_path.exists():
            return RunStatus(run_id=run_id, state="pending", message="No Colab runtime record")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        runtime_id = record.get("observations", [{}])[-1].get("runtime_id")
        if not runtime_id:
            return RunStatus(run_id=run_id, state="pending", details=redact_secrets(record))
        runtime = self.client.runtime(runtime_id)
        observation = _runtime_identity(runtime)
        record.setdefault("observations", []).append(observation)
        record_path.write_text(json.dumps(redact_secrets(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return RunStatus(run_id=run_id, state=str(observation.get("state", "unknown")).lower(), details=observation)

    def fetch(self, run_id: str, destination: Path) -> Path:
        raise ColabClientError("Colab Runtime API has no output-fetch endpoint; use an approved artifact transport")

    def cancel(self, run_id: str) -> bool:
        return self.release(run_id)

    def release(self, run_id: str) -> bool:
        record_path = self.workspace_root / ".expcon" / "runs" / run_id / "colab.json"
        if not record_path.exists():
            return False
        record = json.loads(record_path.read_text(encoding="utf-8"))
        runtime_id = record.get("observations", [{}])[-1].get("runtime_id")
        if not runtime_id:
            return False
        self.client.delete_runtime(runtime_id)
        return True
