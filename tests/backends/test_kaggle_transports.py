"""Hybrid Kaggle adapter tests without network access or credentials."""
from __future__ import annotations

import json

import pytest

from expcon.backends.kaggle import KaggleApiTransport, KagglePermissionError
from expcon.runner.backends import KaggleBackend, RunContext


class _Api:
    def authenticate(self):
        pass

    def kernels_view(self, ref):
        return {"id": 42, "versionNumber": 7, "status": "RUNNING", "token": "never-persist"}

    def kernels_status(self, ref):
        return {"status": "COMPLETE"}


class _Cli:
    def capabilities(self):
        return {"installed": True}

    def push_kernel(self, directory):
        pass

    def kernel_status(self, ref):
        return "complete"


def test_api_capabilities_and_exact_kernel_identity_are_persisted(tmp_path):
    api = KaggleApiTransport(api=_Api(), sleeper=lambda _: None)
    backend = KaggleBackend(tmp_path, api=api, cli=_Cli())
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    context = RunContext("E19", "v001", "bundle-sha", "contract-sha", run_id="run-e19", kernel="owner/e19-v001")
    backend.submit(bundle, context)
    record = json.loads((tmp_path / ".expcon" / "runs" / "run-e19" / "kaggle.json").read_text())
    assert record["remote"]["kernel"]["version"] == 7
    assert record["contract_sha256"] == "contract-sha"
    assert "never-persist" not in json.dumps(record)


def test_permission_failure_is_distinguished_from_authentication():
    class Forbidden(_Api):
        def kernels_view(self, ref):
            error = Exception("forbidden")
            error.status = 403
            raise error

    with pytest.raises(KagglePermissionError, match="KAGGLE_PERMISSION_INSUFFICIENT"):
        KaggleApiTransport(api=Forbidden()).inspect_kernel("owner/slug")


def test_rate_limit_retries_are_bounded():
    calls = []
    class Limited(_Api):
        def kernels_view(self, ref):
            calls.append(ref)
            error = Exception("too many requests")
            error.status = 429
            raise error

    with pytest.raises(Exception, match="KAGGLE_RATE_LIMIT_EXHAUSTED"):
        KaggleApiTransport(api=Limited(), attempts=2, sleeper=lambda _: None).inspect_kernel("owner/slug")
    assert len(calls) == 2
