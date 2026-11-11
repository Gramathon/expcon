"""Colab Runtime API backend tests; no network or credentials are used."""
from __future__ import annotations

import json

import pytest

from expcon.backends.colab import ColabBackend, ColabClientError
from expcon.runner.backends import RunContext
from expcon.util.env import redact_secrets


class FakeColabClient:
    def runtime_specs(self):
        return [{"key": {"accelerator": "GPU", "shape": "HIGHMEM"}, "eligible": True}]

    def create_runtime(self, runtime, runtime_id):
        assert "connectionInfo" not in runtime
        return {"name": "operations/create-1"}

    def wait_operation(self, name):
        assert name == "operations/create-1"
        return {"done": True}

    def runtime(self, runtime_id):
        return {
            "name": f"runtimes/{runtime_id}",
            "runtimeSpec": {"accelerator": "GPU", "shape": "HIGHMEM"},
            "version": "colab-runtime-2026.08.30",
            "state": "ACTIVE",
            "connectionInfo": {"token": "short-lived-credential", "hostname": "ignore"},
        }

    def delete_runtime(self, runtime_id):
        return {}


def test_colab_provision_records_runtime_without_connection_token(tmp_path):
    backend = ColabBackend(tmp_path, client=FakeColabClient())
    context = RunContext("E01", "v001", "bundle-sha", "contract-sha", run_id="run-e01")
    context.environment = {"requirements": {"accelerator": {"variant": "GPU"}}}
    with pytest.raises(ColabClientError, match="BLOCKED"):
        backend.submit(tmp_path / "bundle", context)
    contents = (tmp_path / ".expcon" / "runs" / "run-e01" / "colab.json").read_text()
    assert "short-lived-credential" not in contents
    assert "connectionInfo" not in contents
    record = json.loads(contents)
    assert record["contract_sha256"] == "contract-sha"
    assert record["observations"][0]["runtime_version"] == "colab-runtime-2026.08.30"


def test_colab_blocks_when_no_eligible_spec(tmp_path):
    class Ineligible(FakeColabClient):
        def runtime_specs(self):
            return [{"key": {"accelerator": "CPU"}, "eligible": False}]

    backend = ColabBackend(tmp_path, client=Ineligible())
    context = RunContext("E01", "v001", "bundle", "contract", run_id="run-e01")
    context.environment = {"requirements": {"accelerator": {"variant": "GPU"}}}
    with pytest.raises(ColabClientError, match="no eligible"):
        backend.submit(tmp_path / "bundle", context)


def test_redaction_removes_colab_connection_info_and_nested_token():
    redacted = redact_secrets({"runtime": {"connectionInfo": {"token": "secret"}}, "token": "also-secret"})
    encoded = json.dumps(redacted)
    assert "secret" not in encoded
    assert "also-secret" not in encoded


def test_allocated_colab_runtime_released_on_missing_version(tmp_path):
    released = []
    class MissingVersion(FakeColabClient):
        def runtime(self, runtime_id):
            return {"name": runtime_id}
        def delete_runtime(self, runtime_id):
            released.append(runtime_id)
    with pytest.raises(ColabClientError, match="exact runtime"):
        ColabBackend(tmp_path, client=MissingVersion()).submit(tmp_path, RunContext("E", "v001", "b", "c", run_id="safe"))
    assert released == ["expcon-safe"]
