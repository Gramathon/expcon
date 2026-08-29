"""Tests for bundle creation and verification."""

import json
from pathlib import Path

import pytest
import yaml

from expcon.bundle.bundle import BundleBuilder, BundleVerifier, bundle_id_for, BundleError
from expcon.contract.operations import freeze_experiment


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
