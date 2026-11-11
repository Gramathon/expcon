"""Hybrid Kaggle adapter tests without network access or credentials."""
from __future__ import annotations

import json

import pytest

from expcon.backends.kaggle import KaggleApiTransport, KagglePermissionError
from expcon.runner.backends import KaggleBackend, RunContext


class _Api:
    def __init__(self):
        self.views = 0

    def authenticate(self):
        pass

    def kernels_view(self, ref):
        self.views += 1
        return {"id": 42, "versionNumber": 6 + self.views, "status": "RUNNING", "token": "never-persist"}

    def kernels_status(self, ref):
        return {"status": "COMPLETE"}

    def kernels_output(self, ref, path, kernel_version_number):
        from pathlib import Path
        Path(path, "output.txt").write_text(f"{ref}@{kernel_version_number}")


class _Cli:
    def capabilities(self):
        return {"installed": True, "kernel.push": True}

    def push_kernel(self, directory):
        return {"stdout": "pushed", "stderr": ""}

    def kernel_status(self, ref):
        return "complete"


def test_api_capabilities_and_exact_kernel_identity_are_persisted(tmp_path):
    api = KaggleApiTransport(api=_Api(), sleeper=lambda _: None)
    backend = KaggleBackend(tmp_path, api=api, cli=_Cli())
    bundle = _notebook_bundle(tmp_path)
    context = RunContext("E19", "v001", "bundle-sha", "contract-sha", run_id="run-e19", kernel="owner/e19-v001")
    backend.submit(bundle, context)
    record = json.loads((tmp_path / ".expcon" / "runs" / "run-e19" / "kaggle.json").read_text())
    assert record["remote"]["kernel"]["version"] == 8
    assert record["contract_sha256"] == "contract-sha"
    assert "never-persist" not in json.dumps(record)
    assert record["remote"]["sources"]["kernels"] == ["owner/parent"]
    assert record["frozen_payload"]["push_diagnostic"]["stdout"] == "pushed"


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


def _notebook_bundle(root):
    bundle = root / "bundle"
    notebook = bundle / "runner" / "kaggle" / "demo.ipynb"
    notebook.parent.mkdir(parents=True)
    notebook.write_text("{}")
    (notebook.parent / "kernel-metadata.json").write_text(json.dumps({
        "id": "owner/demo", "code_file": "demo.ipynb", "kernel_sources": ["owner/parent"],
    }))
    (bundle / "resolved_contract.json").write_text(json.dumps({"execution": {"stages": [{"entrypoint": "kaggle/demo.ipynb"}]}}))
    return bundle


def test_notebook_preflight_requires_exact_provenance_capabilities(tmp_path):
    backend = KaggleBackend(tmp_path, api=KaggleApiTransport(api=_Api()), cli=_Cli())
    preflight = backend.preflight(_notebook_bundle(tmp_path))
    assert preflight["status"] == "READY"
    assert len(preflight["notebook_sha256"]) == 64


def test_capability_preflight_fails_before_push_when_api_absent(tmp_path):
    class NoApi:
        def capabilities(self):
            return {"available": False, "kernel.inspect": False, "kernel.status": False, "output.version_safe": False}
    backend = KaggleBackend(tmp_path, api=NoApi(), cli=_Cli())
    with pytest.raises(Exception, match="KAGGLE_API_UNAVAILABLE"):
        backend.preflight(_notebook_bundle(tmp_path))


def test_notebook_dispatch_rejects_missing_metadata(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "runner").mkdir(parents=True)
    (bundle / "runner" / "x.ipynb").write_text("{}")
    (bundle / "resolved_contract.json").write_text(json.dumps({"execution": {"stages": [{"entrypoint": "x.ipynb"}]}}))
    with pytest.raises(Exception, match="KAGGLE_NOTEBOOK_DISPATCH_MISMATCH"):
        KaggleBackend._notebook_payload(bundle)


def test_version_bound_output_custody_is_hashed(tmp_path):
    api = KaggleApiTransport(api=_Api())
    backend = KaggleBackend(tmp_path, api=api, cli=_Cli())
    run = tmp_path / ".expcon" / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "kaggle.json").write_text(json.dumps({"remote": {"kernel": {"ref": "owner/demo", "version": 7}}}))
    out = backend.fetch("r1", tmp_path / "fetched")
    custody = json.loads((out / "artifact_custody.json").read_text())
    assert custody["artifacts"][0]["kernel_version"] == 7
    assert len(custody["artifacts"][0]["sha256"]) == 64


def test_non_json_cli_push_output_is_diagnostic_not_identity(tmp_path):
    class TextCli(_Cli):
        def push_kernel(self, directory):
            return {"stdout": "queued on legacy cli", "stderr": ""}
    backend = KaggleBackend(tmp_path, api=KaggleApiTransport(api=_Api()), cli=TextCli())
    backend.submit(_notebook_bundle(tmp_path), RunContext("E", "v", "b", "c", run_id="r", kernel="owner/demo"))
    record = json.loads((tmp_path / ".expcon" / "runs" / "r" / "kaggle.json").read_text())
    assert record["remote"]["kernel"]["version"] == 8
    assert record["frozen_payload"]["push_diagnostic"]["stdout"] == "queued on legacy cli"


def test_authentication_failure_is_typed(tmp_path):
    class BadAuth(_Api):
        def authenticate(self):
            raise RuntimeError("unauthorized")
    backend = KaggleBackend(tmp_path, api=KaggleApiTransport(api=BadAuth()), cli=_Cli())
    with pytest.raises(Exception, match="KAGGLE_AUTH_FAILURE"):
        backend.preflight(_notebook_bundle(tmp_path))


def test_non_advancing_version_fails_closed(tmp_path):
    class StaticApi(_Api):
        def kernels_view(self, ref):
            return {"id": 42, "versionNumber": 7, "status": "RUNNING"}
    backend = KaggleBackend(tmp_path, api=KaggleApiTransport(api=StaticApi()), cli=_Cli())
    with pytest.raises(Exception, match="KAGGLE_VERSION_BINDING_FAILURE"):
        backend.submit(_notebook_bundle(tmp_path), RunContext("E", "v", "b", "c", run_id="r", kernel="owner/demo"))


def test_output_without_version_api_fails_closed(tmp_path):
    class NoOutput(_Api):
        kernels_output = None
    backend = KaggleBackend(tmp_path, api=KaggleApiTransport(api=NoOutput()), cli=_Cli())
    with pytest.raises(Exception, match="KAGGLE_OUTPUT_IDENTITY_FAILURE"):
        backend.preflight(_notebook_bundle(tmp_path))
