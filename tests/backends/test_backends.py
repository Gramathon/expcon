"""Backend abstraction tests."""

import json
from pathlib import Path

import pytest

from expcon.runner.backends import (
    ExecutionBackend,
    LocalBackend,
    KaggleBackend,
    RunContext,
    RunStatus,
    BackendError,
)
from expcon.runner.runner import StageRunner


class TestBackendInterface:
    def test_abstract_backend(self):
        backend = ExecutionBackend()
        with pytest.raises(NotImplementedError):
            backend.submit(Path("/tmp"), RunContext("E00", "v001", "bundle123", "hash"))

    def test_local_backend_name(self):
        backend = LocalBackend(Path("/tmp"))
        assert backend.name == "local"

    def test_kaggle_backend_name(self):
        backend = KaggleBackend(Path("/tmp"))
        assert backend.name == "kaggle"


class TestLocalBackend:
    def test_local_backend_submit(self, tmp_path):
        backend = LocalBackend(tmp_path)
        context = RunContext(
            experiment_id="E00",
            version="v001",
            bundle_id="bundle123",
            contract_hash="hash123",
            run_id="test-run-1",
        )
        # Create a minimal bundle
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        resolved = bundle_dir / "resolved_contract.json"
        resolved.write_text(json.dumps({"experiment": {"id": "E00", "version": "v001"}, "execution": {"stages": []}}), encoding="utf-8")
        manifest = bundle_dir / "bundle_manifest.json"
        manifest.write_text(json.dumps({"bundle_id": "bundle123", "files": []}), encoding="utf-8")

        run_id = backend.submit(bundle_dir, context)
        assert run_id == "test-run-1"
        status = backend.status(run_id)
        assert status.state in ("completed", "failed", "running")

    def test_local_backend_cancel(self, tmp_path):
        backend = LocalBackend(tmp_path)
        result = backend.cancel("nonexistent")
        assert result is True


class TestKaggleBackend:
    def test_kaggle_backend_submit_simulated(self, tmp_path):
        backend = KaggleBackend(tmp_path)
        context = RunContext(
            experiment_id="E00",
            version="v001",
            bundle_id="bundle123",
            contract_hash="hash123",
            kernel="smoke",
            accelerator="none",
        )
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        resolved = bundle_dir / "resolved_contract.json"
        resolved.write_text(json.dumps({"experiment": {"id": "E00", "version": "v001"}, "execution": {"stages": []}}), encoding="utf-8")
        manifest = bundle_dir / "bundle_manifest.json"
        manifest.write_text(json.dumps({"bundle_id": "bundle123", "files": []}), encoding="utf-8")

        run_id = backend.submit(bundle_dir, context)
        assert "kaggle" in run_id
        status = backend.status(run_id)
        assert status.state in ("running", "completed", "failed", "pending")


class TestStageRunner:
    def test_runner_uses_backend(self, tmp_path):
        backend = LocalBackend(tmp_path)
        runner = StageRunner(backend)
        assert runner.backend is backend

    def test_runner_get_status(self, tmp_path):
        backend = LocalBackend(tmp_path)
        runner = StageRunner(backend)
        context = RunContext(
            experiment_id="E00",
            version="v001",
            bundle_id="bundle123",
            contract_hash="hash123",
            run_id="test-run",
        )
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        resolved = bundle_dir / "resolved_contract.json"
        resolved.write_text(json.dumps({"experiment": {"id": "E00", "version": "v001"}, "execution": {"stages": []}}), encoding="utf-8")
        manifest = bundle_dir / "bundle_manifest.json"
        manifest.write_text(json.dumps({"bundle_id": "bundle123", "files": []}), encoding="utf-8")

        run_id = runner.run(bundle_dir, context)
        status = runner.get_status(run_id)
        assert status.run_id == run_id
