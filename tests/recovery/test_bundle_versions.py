import json

import yaml

from expcon.bundle.bundle import BundleBuilder, BundleVerifier, compute_bundle_identity
from expcon.contract.contract import load_contract
from expcon.contract.operations import freeze_experiment


def test_v3_opt_in_binds_payload_without_reinterpreting_v2(tmp_path):
    exp = tmp_path / "experiments/new"
    exp.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.0.0"\n')
    (tmp_path / "runner.py").write_text("# unexecuted fixture\n")
    contract = {"schema_version": 1, "bundle_identity_algorithm": "expcon-bundle-v3",
                "experiment": {"id": "V3", "version": "v001", "title": "new"},
                "hypothesis": {"statement": "fixed"}, "source": {"repository": str(tmp_path)},
                "execution": {"allowed_backends": ["local"], "stages": [{"id": "main", "entrypoint": "runner.py"}]},
                "evaluation": {"primary_metric": "accuracy"}, "outputs": {"required": ["metrics.json"]},
                "reproducibility": {"level": "seeded"}}
    (exp / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
    frozen = freeze_experiment(exp, tmp_path)
    bundle, identity = BundleBuilder(exp).build()
    assert identity == frozen["bundle_id"]
    assert BundleVerifier(bundle, expected_bundle_id=identity).verify()["status"] == "PASS"
    parsed = load_contract(exp / "EXPERIMENT.yaml")
    assert compute_bundle_identity(exp, parsed, algorithm="expcon-bundle-v2").bundle_id != identity
    before = (exp / "contract.lock.json").read_bytes()
    (bundle / "runner/extra.py").write_text("# undeclared\n")
    assert BundleVerifier(bundle, expected_bundle_id=identity).verify()["status"] == "FAIL"
    assert (exp / "contract.lock.json").read_bytes() == before


def test_v1_historical_manifest_remains_inspectable():
    from pathlib import Path
    original = Path(__file__).parents[2] / "examples/minimal/bundle"
    before = (original / "bundle_manifest.json").read_bytes()
    result = BundleVerifier(original).verify()
    assert result["bundle_id"] == json.loads(before)["bundle_id"]
    assert not result["trusted_identity"]
    assert (original / "bundle_manifest.json").read_bytes() == before
