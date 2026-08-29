"""Experiment contract module.

Defines the experiment contract schema, loading, validation, and canonical
identity computation.
"""

from expcon.contract.contract import ExperimentContract, ContractError, load_contract, validate_contract
from expcon.contract.canonical import (
    extract_scientific_parameters,
    compute_contract_hash,
    compute_scientific_hash,
    compute_execution_hash,
    contract_identity,
)

__all__ = [
    "ExperimentContract",
    "ContractError",
    "load_contract",
    "validate_contract",
    "extract_scientific_parameters",
    "compute_contract_hash",
    "compute_scientific_hash",
    "compute_execution_hash",
    "contract_identity",
]
