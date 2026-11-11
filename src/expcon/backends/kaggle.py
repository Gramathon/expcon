"""Official Kaggle Public API and CLI transports.

The API transport is deliberately optional: Expcon reuses normal Kaggle
authentication supplied by the official client, but never owns credentials.
"""
from __future__ import annotations

import random
import importlib
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


class KaggleCapabilityError(KaggleTransportError):
    """A required provenance capability is unavailable; never safe to bypass."""


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
        self.api: Any = api
        self.available = api is not None
        if api is None:
            try:
                self.api = importlib.import_module("kaggle.api.kaggle_api_extended").KaggleApi()
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
            # The official API surface varies by installed client version.  A
            # backend may only accept output when it can request a bound version.
            "output.version_safe": bool(self.available and callable(getattr(self.api, "kernels_output", None))),
        }

    def authenticate(self) -> None:
        if not self.api:
            raise KaggleCapabilityError("KAGGLE_API_UNAVAILABLE")
        try:
            self.api.authenticate()
        except Exception as exc:
            raise KaggleTransportError("KAGGLE_AUTH_FAILURE") from exc

    def _read(self, operation: str, call: Callable[[], Any]) -> Any:
        for attempt in range(1, self.attempts + 1):
            try:
                return call()
            except Exception as exc:
                status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
                text = str(exc).lower()
                if status in (401,) or "unauthorized" in text:
                    raise KaggleTransportError("KAGGLE_AUTH_FAILURE") from exc
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

    def fetch_kernel_outputs(self, ref: str, version: int | str, destination: Path) -> None:
        """Fetch one exact output version, or fail before accepting any bytes."""
        self.authenticate()
        if not callable(getattr(self.api, "kernels_output", None)):
            raise KaggleCapabilityError("KAGGLE_OUTPUT_IDENTITY_FAILURE: version-addressable output API unavailable")
        destination.mkdir(parents=True, exist_ok=True)
        try:
            # The official client accepts a version argument on supported releases.
            self.api.kernels_output(ref, path=str(destination), kernel_version_number=version)
        except TypeError as exc:
            raise KaggleCapabilityError("KAGGLE_OUTPUT_IDENTITY_FAILURE: client lacks version-addressable kernel output") from exc
        except Exception as exc:
            raise KaggleTransportError("KAGGLE_OUTPUT_IDENTITY_FAILURE") from exc


class KaggleCliTransport:
    """Structured subprocess adapter for the official installed Kaggle CLI."""

    def __init__(self, executable: str = "kaggle"):
        self.executable = executable

    def capabilities(self) -> dict[str, str | bool]:
        present = shutil.which(self.executable) is not None
        return {"installed": present, "kernel.push": present, "kernel.status": present,
                "output.fetch": present, "kernel.logs": present, "competition.submit": present}

    def authenticated_identity(self) -> dict[str, str]:
        """Read non-secret OAuth client facts from the official CLI."""
        version = self._run(["--version"], timeout=30).stdout.strip()
        config = self._run(["config", "view"], timeout=30).stdout
        fields: dict[str, str] = {"path": str(Path(shutil.which(self.executable) or self.executable).resolve()), "version": version}
        for line in config.splitlines():
            text = line.strip().lstrip("-").strip()
            if ":" in text:
                key, value = (part.strip() for part in text.split(":", 1))
                if key in {"username", "auth_method"}:
                    fields[key] = value
        if not fields.get("username") or not fields.get("auth_method"):
            raise KaggleTransportError("KAGGLE_AUTH_FAILURE: authenticated CLI identity unavailable")
        return fields

    def pull_source(self, ref: str, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        self._run(["kernels", "pull", ref, "-p", str(destination), "-m"], timeout=180)

    def fetch_current_outputs(self, ref: str, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        self._run(["kernels", "output", ref, "-p", str(destination), "--force"], timeout=180)

    def _run(self, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
        if not shutil.which(self.executable):
            raise KaggleTransportError("Kaggle CLI is not installed")
        result = subprocess.run([self.executable, *args], capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise KaggleTransportError(redact_secrets({"error": result.stderr or result.stdout})["error"][:1000])
        return result

    def push_kernel(self, directory: Path) -> dict[str, str]:
        try:
            result = self._run(["kernels", "push", "-p", str(directory)])
        except KaggleTransportError as exc:
            raise KaggleTransportError(f"KAGGLE_PUSH_FAILURE: {exc}") from exc
        # CLI output is diagnostic only.  It must never be parsed as a remote
        # identity because empty or non-JSON output is normal across CLI versions.
        return {"stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}

    def kernel_status(self, ref: str) -> str:
        return self._run(["kernels", "status", ref], timeout=30).stdout.strip()

    def fetch_outputs(self, ref: str, destination: Path) -> None:
        self._run(["kernels", "output", ref, "-p", str(destination), "--force"], timeout=180)

    def logs(self, ref: str) -> str:
        return self._run(["kernels", "status", ref], timeout=30).stdout
