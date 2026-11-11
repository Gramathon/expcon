import hashlib
import json

import pytest

from expcon.bundle.bundle import BundleVerifier
from expcon.evidence.evidence import EvidenceVerifier


def snapshot(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file()}


def test_runner_and_mutable_file_checksum_cannot_preserve_identity(research_run):
    _, _, bundle, _, _ = research_run()
    assert BundleVerifier(bundle).verify()["status"] == "PASS"
    path = bundle / "runner/runner.py"
    path.write_text("# Different executable bytes; never executed.\n")
    manifest = json.loads((bundle / "bundle_manifest.json").read_text())
    for entry in manifest["files"]:
        if entry["relative_path"] == "runner/runner.py":
            entry.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size)
    (bundle / "bundle_manifest.json").write_text(json.dumps(manifest))
    result = BundleVerifier(bundle).verify()
    assert result["status"] == "FAIL", result
    assert any("EXECUTABLE" in error for error in result["errors"])


def test_required_output_substitution_is_detected(research_run):
    _, _, bundle, _, evidence = research_run()
    assert EvidenceVerifier(evidence, bundle).verify()["verified"]
    (evidence / "outputs/metrics.json").write_text('{"accuracy":1}')
    result = EvidenceVerifier(evidence, bundle).verify()
    assert not result["verified"]
    assert any("outputs/metrics.json" in error for error in result["errors"])


def test_verification_is_read_only(research_run):
    _, _, bundle, _, evidence = research_run()
    before = snapshot(evidence)
    EvidenceVerifier(evidence, bundle).verify()
    assert snapshot(evidence) == before


@pytest.mark.parametrize("relative", ["environment.json", "hashes.json", "results.json", "metrics/metrics.json"])
def test_complete_inventory_is_checked(research_run, relative):
    _, _, bundle, _, evidence = research_run()
    # results.json is not emitted by the fixture: exercise an unexpected addition.
    assert EvidenceVerifier(evidence, bundle).verify()["verified"]
    (evidence / relative).write_text('{"unexpected":"mutation"}')
    result = EvidenceVerifier(evidence, bundle).verify()
    assert not result["verified"], relative
    reason = {"results.json": "EVIDENCE_INVENTORY_MISMATCH", "hashes.json": "HASHES_MANIFEST_MISMATCH"}.get(relative, "CONTENT_HASH_MISMATCH")
    assert any(reason in error for error in result["errors"]), result


@pytest.mark.parametrize("relative", ["../outside", "/tmp/outside"])
def test_untrusted_bundle_paths_fail_closed(research_run, relative):
    _, _, bundle, _, _ = research_run()
    assert BundleVerifier(bundle).verify()["status"] == "PASS"
    manifest = json.loads((bundle / "bundle_manifest.json").read_text())
    manifest["files"][0]["relative_path"] = relative
    (bundle / "bundle_manifest.json").write_text(json.dumps(manifest))
    result = BundleVerifier(bundle).verify()
    assert result["status"] == "FAIL"
    assert any("UNSAFE_PATH" in error for error in result["errors"])


def test_expected_run_identity_is_required(research_run):
    _, _, bundle, run, evidence = research_run()
    assert EvidenceVerifier(evidence, bundle, expected_run=run).verify()["verified"]
    run.run_id = "different-run"
    result = EvidenceVerifier(evidence, bundle, expected_run=run).verify()
    assert not result["verified"]
    assert any("RUN_ID" in error for error in result["errors"])


def test_mutable_evidence_manifest_cannot_redefine_required_outputs(research_run):
    _, _, bundle, run, evidence = research_run()
    assert EvidenceVerifier(evidence, bundle, expected_run=run).verify()["verified"]
    path = evidence / "evidence_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["metrics"]["required_outputs"] = []
    path.write_text(json.dumps(manifest))
    (evidence / "outputs/metrics.json").unlink()
    result = EvidenceVerifier(evidence, bundle, expected_run=run).verify()
    assert not result["verified"]


def test_explicit_expected_bundle_identity(research_run):
    _, _, bundle, run, _ = research_run()
    assert BundleVerifier(bundle, expected_bundle_id=run.bundle_id).verify()["status"] == "PASS"
    result = BundleVerifier(bundle, expected_bundle_id="0" * 64).verify()
    assert result["status"] == "FAIL"


def test_registration_is_not_provenance_verification(tmp_path):
    from expcon.artifacts.artifact import ArtifactRegistry
    payload = tmp_path / "data.json"
    payload.write_text("{}")
    item = ArtifactRegistry(tmp_path / "run").register(payload, "metrics", "EX", "run")
    assert item.verification_state != "VERIFIED"


def test_untrusted_evidence_artifact_path_is_rejected(research_run):
    _, _, bundle, run, evidence = research_run()
    assert EvidenceVerifier(evidence, bundle, expected_run=run).verify()["verified"]
    path = evidence / "artifacts.json"
    payload = json.loads(path.read_text())
    payload["artifacts"][0]["path"] = "../outside"
    path.write_text(json.dumps(payload))
    result = EvidenceVerifier(evidence, bundle, expected_run=run).verify()
    assert not result["verified"]
    assert any("UNSAFE_PATH" in item for item in result["errors"])


def test_missing_bundle_cannot_be_verified(research_run):
    _, _, _, run, evidence = research_run()
    result = EvidenceVerifier(evidence, expected_run=run).verify()
    assert not result["verified"]
    assert "EXPECTED_BUNDLE_REQUIRED" in result["errors"]


def test_symlink_escape_is_rejected(research_run, tmp_path):
    _, _, bundle, _, evidence = research_run()
    assert EvidenceVerifier(evidence, bundle).verify()["verified"]
    target = tmp_path / "outside.json"
    target.write_text("{}")
    path = evidence / "outputs/metrics.json"
    path.unlink()
    path.symlink_to(target)
    result = EvidenceVerifier(evidence, bundle).verify()
    assert not result["verified"]
    assert any("UNSAFE_PATH" in item for item in result["errors"])


def test_packaging_refuses_different_scientific_metric_copy(research_run):
    from expcon.evidence.evidence import EvidenceError
    root, _, _, run, _ = research_run(metrics={"accuracy": 0.2})
    (root / "output/metrics/metrics.json").write_text('{"accuracy":0.99}')
    with pytest.raises(EvidenceError, match="METRIC_SOURCE_MISMATCH"):
        EvidenceVerifier(root / "different-evidence").package_evidence(
            run.run_id, run.experiment_id, run.contract_hash, run.bundle_id,
            root / "output", ["metrics.json"])
