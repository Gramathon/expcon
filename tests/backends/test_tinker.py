"""Tinker adapter tests at the public SDK boundary; no network or paid work."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from expcon.backends.tinker import (
    TinkerBackend,
    TinkerCompatibleInferenceTransport,
    TinkerError,
    TinkerSdkTransport,
    validate_driver_identity,
    validate_resume_mode,
)
from expcon.runner.backends import RunContext
from expcon.util.env import redact_secrets


class _Rest:
    def whoami(self):
        return {"id": "principal-1", "api_key": "not-for-output"}

    def list_training_runs(self):
        return {"training_runs": [{"id": "train-1"}]}

    def get_training_run(self, run_id):
        return {"id": run_id, "status": "RUNNING"}

    def list_sessions(self):
        return {"sessions": [{"id": "session-1"}]}

    def get_session(self, session_id):
        return {"id": session_id}

    def list_user_checkpoints(self):
        return {"checkpoints": []}

    def list_checkpoints(self, training_run_id):
        return {"checkpoints": [{"training_run_id": training_run_id}]}

    def get_weights_info_by_tinker_path(self, path):
        return {"path": path, "checkpoint_type": "sampler_weights"}

    def get_checkpoint_archive_url_from_tinker_path(self, path):
        return {"url": "https://download.example/checkpoint.zip?signature=temporary"}

    def export_session_trace(self, session_id):
        return {"session_id": session_id, "trace": []}


class _Service:
    def get_server_capabilities(self):
        return {"supported_models": ["Qwen/Qwen3-8B"], "token": "secret"}

    def create_rest_client(self):
        return _Rest()


class _Sdk:
    __version__ = "0.test"

    def ServiceClient(self):
        return _Service()


def _transport(monkeypatch):
    monkeypatch.setenv("TINKER_API_KEY", "tinker-secret-value")
    return TinkerSdkTransport(sdk=_Sdk())


def _bundle(tmp_path, *, resume_mode=None):
    bundle = tmp_path / "bundle"
    runner = bundle / "runner"
    runner.mkdir(parents=True)
    contract = {"execution": {"stages": [{"id": "train", "entrypoint": "driver.py"}]}}
    if resume_mode:
        contract["training_service"] = {"resume": {"mode": resume_mode}}
    (bundle / "resolved_contract.json").write_text(json.dumps(contract), encoding="utf-8")
    (bundle / "bundle_manifest.json").write_text("{}", encoding="utf-8")
    (runner / "driver.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "out=Path(sys.argv[sys.argv.index('--output-root')+1]); out.mkdir(parents=True,exist_ok=True)\n"
        "(out/'tinker_identity.json').write_text(json.dumps({'training_run_id':'train-1','session_id':'session-1','base_model':'Qwen/Qwen3-8B','resume_mode':'weights_and_optimizer'}))\n"
        "(out/'metrics.json').write_text('{}')\n",
        encoding="utf-8",
    )
    return bundle


def test_tinker_doctor_boundary_and_credentials_are_redacted(monkeypatch):
    diagnostics = _transport(monkeypatch).diagnostics()
    encoded = json.dumps(diagnostics)
    assert diagnostics["authenticated"]
    assert "tinker-secret-value" not in encoded
    assert "not-for-output" not in encoded
    assert diagnostics["capabilities"]["token"] == "***REDACTED***"


def test_tinker_driver_persists_identity_without_api_key(monkeypatch, tmp_path):
    backend = TinkerBackend(tmp_path, sdk=_transport(monkeypatch))
    context = RunContext("S07", "v003", "bundle-sha", "contract-sha", run_id="run-s07")
    backend.submit(_bundle(tmp_path, resume_mode="weights_and_optimizer"), context)
    record = json.loads((tmp_path / ".expcon" / "runs" / "run-s07" / "tinker.json").read_text())
    assert record["remote"]["training_run_id"] == "train-1"
    assert record["remote"]["session_id"] == "session-1"
    assert "tinker-secret-value" not in json.dumps(record)
    assert backend.status("run-s07").details["training_run"]["id"] == "train-1"


def test_tinker_missing_identity_blocks_provenance(monkeypatch, tmp_path):
    bundle = _bundle(tmp_path)
    (bundle / "runner" / "driver.py").write_text("", encoding="utf-8")
    backend = TinkerBackend(tmp_path, sdk=_transport(monkeypatch))
    with pytest.raises(TinkerError, match="TINKER_REMOTE_IDENTITY_UNRESOLVED"):
        backend.submit(bundle, RunContext("S07", "v003", "b", "c", run_id="run-no-id"))


def test_resume_mode_never_falls_back():
    validate_resume_mode("weights_only", "weights_only")
    with pytest.raises(TinkerError, match="TINKER_RESUME_MODE_MISMATCH"):
        validate_resume_mode("weights_and_optimizer", "weights_only")


def test_driver_cannot_bind_a_different_frozen_model_or_lora():
    frozen = {"training_service": {"base_model": "Qwen/Qwen3-8B", "lora": {"rank": 32}}}
    with pytest.raises(TinkerError, match="TINKER_MODEL_IDENTITY_MISMATCH"):
        validate_driver_identity(frozen, {"base_model": "Qwen/Qwen3-4B", "lora": {"rank": 32}})
    with pytest.raises(TinkerError, match="TINKER_LORA_CONFIGURATION_MISMATCH"):
        validate_driver_identity(frozen, {"base_model": "Qwen/Qwen3-8B", "lora": {"rank": 16}})


def test_compatible_inference_identity_remains_tinker_and_never_falls_back():
    transport = TinkerCompatibleInferenceTransport()
    record = transport.identity("openai_compatible", "tinker://run/sampler_weights/000001", {"temperature": 0})
    assert record["provider"] == "tinker"
    assert record["protocol"] == "openai_compatible"
    with pytest.raises(TinkerError, match="TINKER_INFERENCE_PROTOCOL_UNSUPPORTED"):
        transport.identity("openai", "tinker://run/sampler_weights/000001", {})


def test_signed_checkpoint_url_and_environment_secret_are_redacted(monkeypatch):
    monkeypatch.setenv("TINKER_API_KEY", "tinker-secret-value")
    output = redact_secrets({"archive_url": "https://a.example/file?signature=temp", "message": "tinker-secret-value"})
    assert "tinker-secret-value" not in json.dumps(output)
    assert output["archive_url"] == "***REDACTED***"


def test_checkpoint_fetch_rejects_traversal_archive(monkeypatch, tmp_path):
    transport = _transport(monkeypatch)
    backend = TinkerBackend(tmp_path, sdk=transport)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape", "bad")
    payload = archive.getvalue()

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: _Response(payload))
    with pytest.raises(TinkerError, match="TINKER_CHECKPOINT_FETCH_FAILED"):
        backend.fetch_checkpoint("tinker://run/sampler_weights/000001", tmp_path / "download")
