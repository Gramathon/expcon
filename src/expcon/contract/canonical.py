"""Canonical identity computation for contracts.

This module computes deterministic hashes for:
  - the full contract (contract_hash)
  - scientific parameters only (scientific_parameters_hash)
  - execution requirements only (execution_hash)

Changing any scientific parameter changes the scientific hash and the
contract hash.  Changing only execution parameters changes the execution
hash but NOT the scientific hash.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from expcon.hashing.canonical import canonical_bytes, canonical_json
from expcon.hashing.digest import sha256_bytes
from expcon.contract.contract import ExperimentContract


# Fields that constitute scientific identity.
SCIENTIFIC_FIELDS = {
    "experiment.id",
    "experiment.version",
    "hypothesis.statement",
    "hypothesis.scientific_fingerprint",
    "data",
    "evaluation",
    "outputs",
    "reproducibility",
    "scientific_parameters",
}


def _get_nested(data: dict, dotted: str) -> Any:
    node = data
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def extract_scientific_parameters(data: dict[str, Any]) -> dict[str, Any]:
    """Extract the scientific-identity portion of a contract."""
    result = {}
    for field in sorted(SCIENTIFIC_FIELDS):
        val = _get_nested(data, field)
        if val is not None:
            result[field] = val
    return result


def compute_contract_hash(data: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the entire contract."""
    return sha256_bytes(canonical_bytes(data))


def compute_scientific_hash(data: dict[str, Any]) -> str:
    """SHA-256 of the scientific-identity portion only."""
    sci = extract_scientific_parameters(data)
    return sha256_bytes(canonical_bytes(sci))


def compute_execution_hash(data: dict[str, Any]) -> str:
    """SHA-256 of execution-related fields only."""
    exec_fields = {
        "execution",
        "environment",
    }
    result = {}
    for field in sorted(exec_fields):
        val = _get_nested(data, field)
        if val is not None:
            result[field] = val
    return sha256_bytes(canonical_bytes(result))


def contract_identity(data: dict[str, Any]) -> dict[str, str]:
    """Return the full identity bundle for a contract."""
    return {
        "contract_hash": compute_contract_hash(data),
        "scientific_hash": compute_scientific_hash(data),
        "execution_hash": compute_execution_hash(data),
    }
