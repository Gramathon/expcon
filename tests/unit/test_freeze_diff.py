"""Tests for freeze and diff operations."""

import json

import pytest
import yaml

from expcon.contract.operations import validate_experiment, freeze_experiment, diff_experiment, ContractOperationError


@pytest.fixture
def minimal_experiment(tmp_path):
    """Create a minimal experiment for testing."""
    contract = {
        "schema_version": 1,
        "experiment": {"id": "E00", "version": "v001", "title": "Test"},
        "hypothesis": {"statement": "Test hypothesis"},
        "source": {"repository": str(tmp_path), "dirty_tree_allowed": False},
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
    (exp_dir / "run.py").write_text("print('freeze/diff test runner')\n", encoding="utf-8")
    return exp_dir, contract


class TestValidate:
    def test_validate_passes(self, minimal_experiment):
        exp_dir, _ = minimal_experiment
        result = validate_experiment(exp_dir)
        assert result["status"] == "VALID"

    def test_validate_detects_latest_alias(self, minimal_experiment):
        exp_dir, contract = minimal_experiment
        contract["scientific_parameters"]["model"] = "latest"
        (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
        with pytest.raises(ContractOperationError, match="latest"):
            validate_experiment(exp_dir)


class TestFreeze:
    def test_freeze_creates_lock(self, minimal_experiment):
        exp_dir, _ = minimal_experiment
        result = freeze_experiment(exp_dir, exp_dir.parent.parent)
        assert result["status"] == "FROZEN"
        assert (exp_dir / "contract.lock.json").exists()

    def test_freeze_computes_hashes(self, minimal_experiment):
        exp_dir, _ = minimal_experiment
        result = freeze_experiment(exp_dir, exp_dir.parent.parent)
        assert "contract_hash" in result
        assert "scientific_hash" in result
        assert "bundle_id" in result
        assert len(result["contract_hash"]) == 64

    def test_freeze_sets_state(self, minimal_experiment):
        exp_dir, _ = minimal_experiment
        freeze_experiment(exp_dir, exp_dir.parent.parent)
        state_file = exp_dir / ".expcon_state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["state"] == "FROZEN"

    def test_freeze_idempotent(self, minimal_experiment):
        exp_dir, _ = minimal_experiment
        freeze_experiment(exp_dir, exp_dir.parent.parent)
        with pytest.raises(ContractOperationError, match="already frozen"):
            freeze_experiment(exp_dir, exp_dir.parent.parent)


class TestDiff:
    def test_diff_no_changes(self, minimal_experiment):
        exp_dir, _ = minimal_experiment
        freeze_experiment(exp_dir, exp_dir.parent.parent)
        result = diff_experiment(exp_dir)
        assert not result["divergence_detected"]

    def test_diff_detects_scientific_change(self, minimal_experiment):
        exp_dir, contract = minimal_experiment
        freeze_experiment(exp_dir, exp_dir.parent.parent)
        # Change a scientific parameter
        contract["scientific_parameters"]["seed"] = 100
        (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
        result = diff_experiment(exp_dir)
        assert result["divergence_detected"]
        # The divergence should mention seed somewhere
        assert "seed" in str(result["divergences"])

    def test_diff_detects_source_change(self, minimal_experiment):
        exp_dir, _ = minimal_experiment
        freeze_experiment(exp_dir, exp_dir.parent.parent)
        # Add a repository source file covered by the frozen source manifest.
        scripts_dir = exp_dir.parent.parent / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        (scripts_dir / "new_file.py").write_text("# new", encoding="utf-8")
        result = diff_experiment(exp_dir)
        assert result["divergence_detected"]

    def test_diff_detects_frozen_invocation_change(self, minimal_experiment):
        exp_dir, contract = minimal_experiment
        contract["execution"]["invocation"] = {"argv": ["--output", "${outputs.root}"]}
        (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
        freeze_experiment(exp_dir, exp_dir.parent.parent)
        contract["execution"]["invocation"]["argv"] = ["--other", "${outputs.root}"]
        (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
        result = diff_experiment(exp_dir)
        assert result["divergence_detected"]
        assert any(item["field"] == "execution" for item in result["divergences"])

    def test_diff_not_frozen(self, minimal_experiment):
        exp_dir, _ = minimal_experiment
        result = diff_experiment(exp_dir)
        assert result["status"] == "NOT_FROZEN"
