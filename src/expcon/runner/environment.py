"""Generic verification of a local execution interpreter.

The Expcon CLI environment is not automatically an experiment environment.
Before a local run, resolve a declared dependency lock to a verified existing
virtual environment and prove direct entrypoint imports without calling main.
"""

from __future__ import annotations

import ast
import json
import platform
import subprocess
import sys
import importlib

from pathlib import Path
from typing import Any

from expcon.hashing.canonical import canonical_bytes
from expcon.hashing.digest import file_sha256, sha256_bytes


tomllib = importlib.import_module("tomllib" if sys.version_info >= (3, 11) else "tomli")

class EnvironmentError(RuntimeError):
    """The declared execution environment cannot be verified."""


_STDLIB = set(getattr(sys, "stdlib_module_names", ()))


def _python_version_tuple(value: str) -> tuple[int, ...]:
    """Parse a concrete Python version without adding a launcher dependency."""
    parts = value.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise EnvironmentError(f"Unsupported Python version: {value!r}")
    return tuple(int(part) for part in parts)


def _python_requirement_satisfied(version: str, requirement: str) -> bool:
    """Conservatively evaluate the simple PEP 440 comparisons uv records.

    A preflight must fail closed rather than importing a third-party resolver
    from the Expcon launcher environment.  Unsupported constructs are rejected
    explicitly; the frozen lock remains the authority for dependency versions.
    """
    observed = _python_version_tuple(version)
    comparisons = ("<=", ">=", "==", "!=", "<", ">")
    for clause in (item.strip() for item in requirement.split(",")):
        operator = next((item for item in comparisons if clause.startswith(item)), None)
        if operator is None:
            raise EnvironmentError(f"Unsupported Python requirement clause: {clause!r}")
        target_text = clause[len(operator):].strip()
        if "*" in target_text:
            raise EnvironmentError(f"Unsupported Python requirement clause: {clause!r}")
        target = _python_version_tuple(target_text)
        width = max(len(observed), len(target))
        observed = observed + (0,) * (width - len(observed))
        target = target + (0,) * (width - len(target))
        if operator == "<=" and not observed <= target:
            return False
        if operator == ">=" and not observed >= target:
            return False
        if operator == "==" and not observed == target:
            return False
        if operator == "!=" and not observed != target:
            return False
        if operator == "<" and not observed < target:
            return False
        if operator == ">" and not observed > target:
            return False
    return True


def _lock_spec(contract: dict[str, Any]) -> tuple[str, str | None]:
    spec = contract.get("environment", {}).get("dependency_lock")
    if spec is None:
        spec = contract.get("source", {}).get("dependency_lock")
    if isinstance(spec, str):
        return spec, None
    if isinstance(spec, dict) and isinstance(spec.get("path"), str):
        return spec["path"], spec.get("sha256")
    raise EnvironmentError("Frozen contract does not declare a dependency lock")


def _direct_import_roots(script: Path, source_root: Path) -> list[str]:
    tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return sorted(root for root in roots if root not in _STDLIB)


def _root_dependencies(lock_path: Path) -> dict[str, str]:
    """Return direct project dependency distributions recorded in a uv lock."""
    payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = payload.get("package", [])
    project = next((
        item for item in packages
        if item.get("source", {}).get("virtual") == "." or item.get("source", {}).get("editable") == "."
    ), None)
    versions = {item["name"]: item["version"] for item in packages if "name" in item and "version" in item}
    if project is None:
        return {}
    return {
        item["name"]: versions[item["name"]]
        for item in project.get("dependencies", [])
        if item.get("name") in versions
    }


def preflight_local_environment(bundle_path: Path | str, workspace_root: Path | str) -> dict[str, Any]:
    """Resolve a lock-matched existing environment and check direct imports.

    This intentionally never installs packages and never imports the runner
    module itself, preventing runner ``main`` execution during preflight.
    """
    bundle = Path(bundle_path).resolve()
    workspace = Path(workspace_root).resolve()
    contract = json.loads((bundle / "resolved_contract.json").read_text(encoding="utf-8"))
    relative_lock, expected_sha = _lock_spec(contract)
    lock_path = (workspace / relative_lock).resolve()
    try:
        lock_path.relative_to(workspace)
    except ValueError as exc:
        raise EnvironmentError("Dependency lock path escapes workspace") from exc
    if not lock_path.is_file():
        raise EnvironmentError(f"Declared dependency lock is missing: {relative_lock}")
    observed_sha = file_sha256(lock_path)
    if expected_sha and observed_sha != expected_sha:
        raise EnvironmentError("Declared dependency lock SHA256 mismatch")

    executable = workspace / ".venv" / "bin" / "python"
    if not executable.is_file():
        raise EnvironmentError("No verified local .venv interpreter is available")
    stages = contract.get("execution", {}).get("stages", [])
    if not stages:
        raise EnvironmentError("Frozen contract contains no execution stages")
    entrypoint = bundle / "runner" / str(stages[0].get("entrypoint", ""))
    if not entrypoint.is_file():
        raise EnvironmentError("Bundled entrypoint is missing")
    imports = _direct_import_roots(entrypoint, bundle / "source")
    lock_payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    requires_python = lock_payload.get("requires-python")
    distributions = _root_dependencies(lock_path)
    probe = (
        "import importlib, importlib.metadata, json, sys; "
        f"mods={imports!r}; "
        f"dists={distributions!r}; "
        "[importlib.import_module(name) for name in mods]; "
        "print(json.dumps({'executable':sys.executable,'python_version':sys.version.split()[0],"
        "'imports':mods,'distributions':{name:importlib.metadata.version(name) for name in dists},"
        "'installed_distributions':{d.metadata['Name'].lower().replace('_','-'):d.version for d in importlib.metadata.distributions()}}))"
    )
    result = subprocess.run(
        [str(executable), "-c", probe], capture_output=True, text=True,
        env={"PYTHONPATH": str(bundle / "source"), "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60,
    )
    if result.returncode != 0:
        raise EnvironmentError(f"Frozen runner dependencies are not importable: {result.stderr.strip()}")
    runtime = json.loads(result.stdout)
    if requires_python and not _python_requirement_satisfied(runtime["python_version"], requires_python):
        raise EnvironmentError(f"Interpreter Python {runtime['python_version']} does not satisfy {requires_python}")
    if runtime["distributions"] != distributions:
        raise EnvironmentError("Installed direct dependency versions differ from frozen lock")
    expected_distributions = contract.get("environment", {}).get("distribution_versions")
    if expected_distributions is not None and expected_distributions != runtime["installed_distributions"]:
        raise EnvironmentError("Installed environment differs from declared distribution inventory")
    accelerator = contract.get("execution", {}).get("accelerator", {}).get("type", "none")
    if accelerator not in {"none", "cpu"}:
        raise EnvironmentError("Local accelerator environment attestation is not implemented; GPU/TPU dispatch refused")
    identity = sha256_bytes(canonical_bytes({
        "dependency_lock_sha256": observed_sha,
        "python_version": runtime["python_version"],
        "imports": runtime["imports"],
        "distributions": runtime["distributions"],
        "installed_distributions": runtime["installed_distributions"],
        "python_requires": requires_python,
        "platform": {"system": platform.system(), "machine": platform.machine()},
    }))
    return {
        "status": "PASS",
        "python_executable": runtime["executable"],
        "python_version": runtime["python_version"],
        "dependency_lock_path": relative_lock,
        "dependency_lock_sha256": observed_sha,
        "import_roots": runtime["imports"],
        "distribution_versions": runtime["distributions"],
        "installed_distributions": runtime["installed_distributions"],
        "distribution_inventory_enforced": expected_distributions is not None,
        "accelerator": {"type": "cpu", "cuda_runtime": None, "gpu_driver": None,
                        "torch_version": runtime["installed_distributions"].get("torch")},
        "python_requires": requires_python,
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "runtime_environment_identity": identity,
        "runtime_environment_matched": True,
    }
