"""Tests for contract validation, canonical identity, and scientific hashing."""

import json
from pathlib import Path

import pytest
import yaml

from expcon.contract.contract import ExperimentContract, ContractError, load_contract, validate_contract
from expcon.contract.canonical import (
    compute_contract_hash,
    compute_scientific_hash,
    compute_execution_hash,
    extract_scientific_parameters,
    contract_identity,
)
from expcon.hashing.canonical import canonical_json


@pytest.fixture
def valid_contract_data():
    return {
        "schema_version": 1,
        "experiment": {"id": "E00", "version": "v001", "title": "Test"},
        "hypothesis": {"statement": "Test hypothesis"},
        "execution": {
            "allowed_backends": ["local"],
            "accelerator": {"type": "none"},
            "stages": [{"id": "main", "entrypoint": "run.py", "requires": []}],
        },
        "evaluation": {"primary_metric": "accuracy", "threshold": 0.5},
        "outputs": {"required": ["metrics.json"]},
        "reproducibility": {"level": "seeded", "seed": 42},
        "scientific_parameters": {"seed": 42, "metric": "accuracy"},
    }


@pytest.fixture
def contract_file(tmp_path, valid_contract_data):
    path = tmp_path / "EXPERIMENT.yaml"
    path.write_text(yaml.safe_dump(valid_contract_data), encoding="utf-8")
    return path


class TestContractLoading:
    def test_load_valid_contract(self, contract_file):
        contract = load_contract(contract_file)
        assert contract.experiment_id == "E00"
        assert contract.version == "v001"
        assert contract.title == "Test"

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(ContractError):
            load_contract(tmp_path / "nonexistent.yaml")

    def test_invalid_schema_missing_required(self, tmp_path):
        data = {"experiment": {"id": "E00"}}
        path = tmp_path / "EXPERIMENT.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        with pytest.raises(ContractError):
            load_contract(path)

    def test_invalid_schema_bad_version(self, tmp_path, valid_contract_data):
        valid_contract_data["experiment"]["version"] = "001"  # invalid
        path = tmp_path / "EXPERIMENT.yaml"
        path.write_text(yaml.safe_dump(valid_contract_data), encoding="utf-8")
        with pytest.raises(ContractError):
            load_contract(path)


class TestScientificHashing:
    def test_scientific_hash_changes_with_seed(self, valid_contract_data):
        h1 = compute_scientific_hash(valid_contract_data)
        valid_contract_data["scientific_parameters"]["seed"] = 100
        h2 = compute_scientific_hash(valid_contract_data)
        assert h1 != h2

    def test_scientific_hash_changes_with_dataset(self, valid_contract_data):
        h1 = compute_scientific_hash(valid_contract_data)
        valid_contract_data["data"] = {"provider": "kaggle", "datasets": ["ds1"]}
        h2 = compute_scientific_hash(valid_contract_data)
        assert h1 != h2

    def test_scientific_hash_changes_with_metric(self, valid_contract_data):
        h1 = compute_scientific_hash(valid_contract_data)
        valid_contract_data["evaluation"]["primary_metric"] = "f1"
        h2 = compute_scientific_hash(valid_contract_data)
        assert h1 != h2

    def test_execution_hash_changes_with_backend(self, valid_contract_data):
        h1 = compute_execution_hash(valid_contract_data)
        valid_contract_data["execution"]["allowed_backends"] = ["kaggle"]
        h2 = compute_execution_hash(valid_contract_data)
        assert h1 != h2

    def test_scientific_hash_unchanged_by_execution(self, valid_contract_data):
        h1 = compute_scientific_hash(valid_contract_data)
        valid_contract_data["execution"]["allowed_backends"] = ["kaggle"]
        h2 = compute_scientific_hash(valid_contract_data)
        assert h1 == h2  # Execution changes don't affect scientific hash

    def test_contract_hash_changes_with_any_field(self, valid_contract_data):
        h1 = compute_contract_hash(valid_contract_data)
        valid_contract_data["experiment"]["title"] = "Changed"
        h2 = compute_contract_hash(valid_contract_data)
        assert h1 != h2

    def test_contract_hash_stable_for_same_data(self, valid_contract_data):
        h1 = compute_contract_hash(valid_contract_data)
        h2 = compute_contract_hash(dict(valid_contract_data))
        assert h1 == h2

    def test_no_latest_in_scientific_params(self, valid_contract_data):
        valid_contract_data["scientific_parameters"]["model"] = "latest"
        sci = extract_scientific_parameters(valid_contract_data)
        assert "latest" in canonical_json(sci)
