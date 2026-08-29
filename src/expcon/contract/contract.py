"""Experiment contract data model, loading, and structural validation."""

from __future__ import annotations

import json
from importlib.resources import files
import re
from pathlib import Path
from typing import Any

import jsonschema
import yaml

# Schemas ship inside the distribution.  The legacy repository-level schemas
# remain useful for contributors, but installed wheels must not depend on them.
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"


class ContractError(Exception):
    """Raised when a contract is structurally invalid or fails validation."""


def _load_schema(name: str) -> dict:
    resource_name = {
        "experiment.schema.json": "experiment-v1.json",
        "frozen_contract.schema.json": "frozen-contract-v1.json",
        "run.schema.json": "run-v1.json",
        "artifact.schema.json": "artifact-v1.json",
        "evidence.schema.json": "evidence-v1.json",
    }.get(name, name)
    try:
        return json.loads(files("expcon").joinpath("resources", "schemas", resource_name).read_text())
    except (FileNotFoundError, ModuleNotFoundError):  # source-tree compatibility
        return json.loads((SCHEMA_DIR / name).read_text())


def load_contract(path: Path | str) -> "ExperimentContract":
    """Load a contract from a YAML or JSON file."""
    path = Path(path)
    if not path.exists():
        raise ContractError(f"Contract file not found: {path}")

    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif path.suffix == ".json":
        data = json.loads(text)
    else:
        # Try YAML first, then JSON
        try:
            data = yaml.safe_load(text)
        except Exception:
            data = json.loads(text)

    if not isinstance(data, dict):
        raise ContractError("Contract root must be a mapping/dict")

    return ExperimentContract(data, source_path=path)


def validate_contract(contract: dict | "ExperimentContract") -> None:
    """Validate a contract dict against the JSON schema."""
    if isinstance(contract, ExperimentContract):
        data = contract.data
    else:
        data = contract

    schema = _load_schema("experiment.schema.json")
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ContractError(f"Contract schema validation failed: {exc.message} (at {list(exc.path)})") from exc


class ExperimentContract:
    """In-memory experiment contract with validated data."""

    def __init__(self, data: dict[str, Any], source_path: Path | None = None):
        self.data = data
        self.source_path = source_path
        validate_contract(self)

    @property
    def experiment_id(self) -> str:
        return self.data["experiment"]["id"]

    @property
    def version(self) -> str:
        return self.data["experiment"]["version"]

    @property
    def title(self) -> str:
        return self.data["experiment"]["title"]

    @property
    def hypothesis(self) -> str:
        return self.data["hypothesis"]["statement"]

    @property
    def schema_version(self) -> int:
        return self.data.get("schema_version", 1)

    def to_canonical_json(self) -> str:
        """Return canonical JSON of the contract (deterministic)."""
        from expcon.hashing.canonical import canonical_json

        return canonical_json(self.data)

    def get(self, *path: str, default: Any = None) -> Any:
        """Safely navigate nested contract keys."""
        node = self.data
        for key in path:
            if not isinstance(node, dict):
                return default
            node = node.get(key, default)
            if node is None:
                return default
        return node

    def resolve_path(self, *parts: str) -> Path:
        """Resolve a path relative to the contract's source directory."""
        base = self.source_path.parent if self.source_path else Path.cwd()
        return base.joinpath(*parts)
