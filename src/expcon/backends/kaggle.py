"""Official Kaggle Public API and CLI transports.

The API transport is deliberately optional: Expcon reuses normal Kaggle
authentication supplied by the official client, but never owns credentials.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from expcon.util.env import redact_secrets


class KaggleTransportError(Exception):
    pass


class KagglePermissionError(KaggleTransportError):
    pass


def _object_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return redact_secrets(value)
    if hasattr(value, "to_dict"):
        return redact_secrets(value.to_dict())
    return redact_secrets(dict(getattr(value, "__dict__", {})))


class KaggleApiTransport:
    """Typed read adapter over the official installed Kaggle Python API."""

    def __init__(self, api: Any | None = None, attempts: int = 3, sleeper: Callable[[float], None] = time.sleep):
        self.attempts, self.sleeper = attempts, sleeper
        self.api = api
        self.available = api is not None
        if api is None:
            try:
                from kaggle.api.kaggle_api_extended import KaggleApi
                self.api = KaggleApi()
                self.available = True
            except ImportError:
                self.api = None

    def capabilities(self) -> dict[str, str | bool]:
        return {
            "available": self.available,
            "kernel.inspect": self.available,
            "kernel.status": self.available,
            "dataset.inspect": self.available,
            "competition.inspect": self.available,
            "submission.inspect": self.available,
        }

    def authenticate(self) -> None:
        if not self.api:
            raise KaggleTransportError("Kaggle Public API package is not installed")
        try:
            self.api.authenticate()
        except Exception as exc:
            raise KaggleTransportError("KAGGLE_AUTH_FAILED") from exc

    def _read(self, operation: str, call: Callable[[], Any]) -> Any:
        for attempt in range(1, self.attempts + 1):
            try:
                return call()
            except Exception as exc:
                status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
                text = str(exc).lower()
                if status in (401,) or "unauthorized" in text:
                    raise KaggleTransportError("KAGGLE_AUTH_FAILED") from exc
                if status in (403,) or "forbidden" in text or "permission" in text:
                    raise KagglePermissionError("KAGGLE_PERMISSION_INSUFFICIENT") from exc
                if status == 429 or "too many requests" in text:
                    if attempt == self.attempts:
                        raise KaggleTransportError("KAGGLE_RATE_LIMIT_EXHAUSTED") from exc
                    self.sleeper(min(8.0, 0.5 * (2 ** (attempt - 1)) + random.random() * 0.25))
                    continue
                raise KaggleTransportError(f"Kaggle API {operation} failed") from exc
        raise AssertionError("unreachable")

    def inspect_kernel(self, ref: str) -> dict[str, Any]:
        self.authenticate()
        result = self._read("kernel.inspect", lambda: self.api.kernels_view(ref))
        return _object_dict(result)

    def kernel_status(self, ref: str) -> dict[str, Any]:
        self.authenticate()
        result = self._read("kernel.status", lambda: self.api.kernels_status(ref))
        return _object_dict(result)

    def inspect_dataset(self, ref: str) -> dict[str, Any]:
        self.authenticate()
        result = self._read("dataset.inspect", lambda: self.api.datasets_view(ref))
        return _object_dict(result)

    def competition_info(self, ref: str) -> dict[str, Any]:
        self.authenticate()
        result = self._read("competition.inspect", lambda: self.api.competition_view(ref))
        return _object_dict(result)


class KaggleCliTransport:
    """Structured subprocess adapter for the official installed Kaggle CLI."""

    def __init__(self, executable: str = "kaggle"):
        self.executable = executable

    def capabilities(self) -> dict[str, str | bool]:
        present = shutil.which(self.executable) is not None
        return {"installed": present, "kernel.push": present, "kernel.status": present,
                "output.fetch": present, "kernel.logs": present, "competition.submit": present}

    def _run(self, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
        if not shutil.which(self.executable):
            raise KaggleTransportError("Kaggle CLI is not installed")
        result = subprocess.run([self.executable, *args], capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise KaggleTransportError(redact_secrets({"error": result.stderr or result.stdout})["error"][:1000])
        return result

    def push_kernel(self, directory: Path) -> None:
        self._run(["kernels", "push", "-p", str(directory)])

    def kernel_status(self, ref: str) -> str:
        return self._run(["kernels", "status", ref], timeout=30).stdout.strip()

    def fetch_outputs(self, ref: str, destination: Path) -> None:
        self._run(["kernels", "output", ref, "-p", str(destination), "--force"], timeout=180)

    def logs(self, ref: str) -> str:
        return self._run(["kernels", "status", ref], timeout=30).stdout
