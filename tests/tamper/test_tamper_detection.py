"""Adversarial tamper detection tests."""

import json

import pytest
import yaml

from expcon.contract.operations import freeze_experiment
from expcon.bundle.bundle import BundleBuilder, BundleVerifier
from expcon.hashing.canonical import canonical_bytes
from expcon.hashing.digest import sha256_bytes


@pytest.fixture
def frozen_exp(tmp_path):
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
    (exp_dir / "run.py").write_text("print('tamper runner')\n", encoding="utf-8")
    freeze_experiment(exp_dir, tmp_path)
    return exp_dir


class TestFrozenParameterMutation:
    """Changing a frozen scientific parameter must be detected."""

    def test_seed_change_detected(self, frozen_exp):
        contract_path = frozen_exp / "EXPERIMENT.yaml"
        contract = yaml.safe_load(contract_path.read_text())
        contract["scientific_parameters"]["seed"] = 100
        contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")

        from expcon.contract.operations import diff_experiment
        result = diff_experiment(frozen_exp)
        assert result["divergence_detected"]

    def test_learning_rate_change_detected(self, frozen_exp):
        contract_path = frozen_exp / "EXPERIMENT.yaml"
        contract = yaml.safe_load(contract_path.read_text())
        contract["scientific_parameters"]["learning_rate"] = 0.001
        contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")

        from expcon.contract.operations import diff_experiment
        result = diff_experiment(frozen_exp)
        assert result["divergence_detected"]

    def test_metric_change_detected(self, frozen_exp):
        contract_path = frozen_exp / "EXPERIMENT.yaml"
        contract = yaml.safe_load(contract_path.read_text())
        contract["evaluation"]["primary_metric"] = "f1"
        contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")

        from expcon.contract.operations import diff_experiment
        result = diff_experiment(frozen_exp)
        assert result["divergence_detected"]


class TestBundleTampering:
    """Any protected modification must fail verification."""

    def test_byte_tampering_detected(self, frozen_exp):
        builder = BundleBuilder(frozen_exp)
        bundle_path, _ = builder.build()
        assert BundleVerifier(bundle_path).verify()["status"] == "PASS"
        manifest = json.loads((bundle_path / "bundle_manifest.json").read_text())
        first_file = manifest["files"][0]
        file_path = bundle_path / first_file["relative_path"]
        original = file_path.read_bytes()
        file_path.write_bytes(original + b"tampered")

        verifier = BundleVerifier(bundle_path)
        result = verifier.verify()
        assert result["status"] == "FAIL"

    def test_manifest_tampering_detected(self, frozen_exp):
        builder = BundleBuilder(frozen_exp)
        bundle_path, _ = builder.build()
        assert BundleVerifier(bundle_path).verify()["status"] == "PASS"
        manifest_path = bundle_path / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["bundle_id"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        verifier = BundleVerifier(bundle_path)
        result = verifier.verify()
        assert result["status"] == "FAIL"
        assert any("BUNDLE_ID_MISMATCH" in e for e in result["errors"])


class TestEvidenceTampering:
    """Tampering with evidence must be detected."""

    def test_missing_manifest_fails_before_metrics_check(self, tmp_path):
        from expcon.evidence.evidence import EvidenceVerifier

        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        metrics_dir = evidence_dir / "metrics"
        metrics_dir.mkdir()
        metrics = {"accuracy": 0.85, "metrics_hash": sha256_bytes(canonical_bytes({"accuracy": 0.85}))}
        (metrics_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")

        # Tamper
        metrics["accuracy"] = 0.99
        (metrics_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")

        verifier = EvidenceVerifier(evidence_dir)
        result = verifier.verify()
        assert result["status"] == "FAIL"
        assert any("evidence_manifest.json" in error for error in result["errors"])
        # Actual metrics mutation is covered from a complete valid baseline in
        # tests/recovery/test_integrity.py::test_complete_inventory_is_checked.


class TestPathTraversal:
    """Archive path traversal must be prevented."""

    def test_path_traversal_blocked(self, tmp_path):
        from expcon.util.path import safe_extract_zip

        # Create a malicious zip with path traversal
        import zipfile

        malicious_zip = tmp_path / "malicious.zip"
        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("../../../etc/passwd", "malicious")

        dest = tmp_path / "extracted"
        with pytest.raises(ValueError, match="traversal"):
            safe_extract_zip(malicious_zip, dest)

    def test_safe_path_check(self, tmp_path):
        from expcon.util.path import is_path_safe

        base = tmp_path / "base"
        base.mkdir()
        safe = tmp_path / "base" / "safe.txt"
        safe.write_text("ok", encoding="utf-8")
        assert is_path_safe(safe, base)

        unsafe = tmp_path / ".." / "unsafe.txt"
        assert not is_path_safe(unsafe, base)
