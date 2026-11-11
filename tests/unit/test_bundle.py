"""Tests for bundle creation and verification."""

import json
from pathlib import Path

import pytest
import yaml

from expcon.bundle.bundle import BundleBuilder, BundleVerifier
from expcon.contract.operations import freeze_experiment
from expcon.bundle.source import SourceResolutionError, resolve_entrypoint
from expcon.contract.contract import load_contract


@pytest.fixture
def frozen_experiment(tmp_path):
    """Create a frozen experiment for bundle testing."""
    contract = {
        "schema_version": 1,
        "experiment": {"id": "E00", "version": "v001", "title": "Test"},
        "hypothesis": {"statement": "Test hypothesis"},
        "source": {"repository": ".", "dirty_tree_allowed": False},
        "execution": {
            "allowed_backends": ["local"],
            "accelerator": {"type": "none"},
            "stages": [{"id": "main", "entrypoint": "run.py", "requires": []}],
        },
        "environment": {"python": "3.10", "dependency_lock": "uv.lock"},
        "evaluation": {"primary_metric": "accuracy", "threshold": 0.5},
        "outputs": {"required": ["metrics.json"]},
        "reproducibility": {"level": "seeded", "seed": 42},
        "scientific_parameters": {"seed": 42, "metric": "accuracy"},
    }
    exp_dir = tmp_path / "experiments" / "e00_v001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
    (exp_dir / "run.py").write_text("print('bundle test runner')\n", encoding="utf-8")
    freeze_experiment(exp_dir, tmp_path)
    return exp_dir


class TestBundle:
    def test_bundle_creation(self, frozen_experiment):
        builder = BundleBuilder(frozen_experiment)
        bundle_path, bundle_id = builder.build()
        assert bundle_path.exists()
        assert len(bundle_id) == 64
        assert (bundle_path / "bundle_manifest.json").exists()
        assert (bundle_path / "resolved_contract.json").exists()
        assert (bundle_path / "hashes.json").exists()

    def test_bundle_id_deterministic(self, frozen_experiment):
        builder = BundleBuilder(frozen_experiment)
        _, id1 = builder.build()
        _, id2 = builder.build()
        assert id1 == id2

    def test_bundle_verification_pass(self, frozen_experiment):
        builder = BundleBuilder(frozen_experiment)
        bundle_path, _ = builder.build()
        verifier = BundleVerifier(bundle_path)
        result = verifier.verify()
        assert result["status"] == "PASS"

    def test_bundle_tampering_detected(self, frozen_experiment):
        builder = BundleBuilder(frozen_experiment)
        bundle_path, _ = builder.build()
        # Tamper with a file
        manifest = json.loads((bundle_path / "bundle_manifest.json").read_text())
        first_file = manifest["files"][0]
        file_path = bundle_path / first_file["relative_path"]
        original = file_path.read_bytes()
        file_path.write_bytes(original + b"tampered")
        verifier = BundleVerifier(bundle_path)
        result = verifier.verify()
        assert result["status"] == "FAIL"
        assert any("HASH_MISMATCH" in e or "SIZE_MISMATCH" in e for e in result["errors"])

    def test_bundle_extra_file_detected(self, frozen_experiment):
        builder = BundleBuilder(frozen_experiment)
        bundle_path, _ = builder.build()
        (bundle_path / "extra_file.txt").write_text("extra", encoding="utf-8")
        verifier = BundleVerifier(bundle_path)
        result = verifier.verify()
        assert result["status"] == "FAIL"
        assert any("EXTRA_FILE" in e for e in result["errors"])

    def test_bundle_id_mismatch_detected(self, frozen_experiment):
        builder = BundleBuilder(frozen_experiment)
        bundle_path, _ = builder.build()
        manifest = json.loads((bundle_path / "bundle_manifest.json").read_text())
        manifest["bundle_id"] = "0" * 64
        (bundle_path / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        verifier = BundleVerifier(bundle_path)
        result = verifier.verify()
        assert result["status"] == "FAIL"
        assert any("BUNDLE_ID_MISMATCH" in e for e in result["errors"])

    def test_runner_inside_experiment_is_bundled(self, frozen_experiment):
        bundle_path, _ = BundleBuilder(frozen_experiment).build()
        assert (bundle_path / "runner" / "run.py").is_file()

    def test_repository_root_runner_is_in_source_manifest_and_bundle(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test-project'\nversion = '0'\n", encoding="utf-8")
        runner = tmp_path / "runner.py"
        runner.write_text("print('external')\n", encoding="utf-8")
        exp_dir = _freeze_external_runner_experiment(tmp_path, "runner.py")

        bundle_path, _ = BundleBuilder(exp_dir).build()
        source = json.loads((bundle_path / "source_manifest.json").read_text(encoding="utf-8"))
        entry = next(item for item in source["entries"] if item["relative_path"] == "runner.py")
        bundled = bundle_path / "runner" / "runner.py"
        assert bundled.is_file()
        assert entry["sha256"] == _sha256(runner) == _sha256(bundled)

    def test_nested_repository_runner_has_deterministic_bundle_path(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test-project'\nversion = '0'\n", encoding="utf-8")
        runner = tmp_path / "scripts" / "audit" / "nested.py"
        runner.parent.mkdir(parents=True)
        runner.write_text("print('nested')\n", encoding="utf-8")
        exp_dir = _freeze_external_runner_experiment(tmp_path, "scripts/audit/nested.py")

        bundle_path, _ = BundleBuilder(exp_dir).build()
        bundled = bundle_path / "runner" / "scripts" / "audit" / "nested.py"
        assert bundled.is_file()
        assert _sha256(runner) == _sha256(bundled)

    def test_entrypoint_path_traversal_is_rejected(self, frozen_experiment):
        contract = yaml.safe_load((frozen_experiment / "EXPERIMENT.yaml").read_text(encoding="utf-8"))
        contract["execution"]["stages"][0]["entrypoint"] = "../escape.py"
        (frozen_experiment / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
        with pytest.raises(SourceResolutionError, match="safe repository-relative"):
            resolve_entrypoint(frozen_experiment, load_contract(frozen_experiment / "EXPERIMENT.yaml"), "../escape.py")


def _freeze_external_runner_experiment(root: Path, entrypoint: str) -> Path:
    contract = {
        "schema_version": 1,
        "experiment": {"id": "E01", "version": "v001", "title": "External runner"},
        "hypothesis": {"statement": "Test hypothesis"},
        "source": {"repository": "."},
        "execution": {"allowed_backends": ["local"], "stages": [{"id": "main", "entrypoint": entrypoint}]},
        "evaluation": {"primary_metric": "accuracy"},
        "outputs": {"required": ["metrics.json"]},
        "reproducibility": {"level": "seeded", "seed": 1},
        "scientific_parameters": {"seed": 1},
    }
    exp_dir = root / "experiments" / "e01_v001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
    freeze_experiment(exp_dir, root)
    return exp_dir


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
