"""Frozen, symbolic runner invocation specifications.

The specification is part of ``execution`` identity. Runtime bindings supply
transport locations only; they never change symbolic argument order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from expcon.runner.inputs import content_identity
from expcon.hashing.digest import sha256_bytes
from expcon.util.env import SECRET_PATTERNS


class InvocationError(ValueError):
    """A frozen invocation specification or runtime binding is invalid."""


_INPUT = re.compile(r"^\$\{inputs\.([A-Za-z][A-Za-z0-9_-]*)\.(path|root)\}$")
_OUTPUT = "${outputs.root}"
_BUNDLE = "${bundle.root}"
_CONTRACT = "${contract.path}"
_ENV = re.compile(r"^\$\{environment\.([A-Za-z_][A-Za-z0-9_]*)\}$")


@dataclass(frozen=True)
class ResolvedInvocation:
    argv: list[str]
    environment: dict[str, str]
    attestation: dict[str, Any]


def validate_invocation_spec(spec: object) -> None:
    """Validate static syntax without consulting host-specific bindings."""
    if spec is None:
        return
    if not isinstance(spec, dict):
        raise InvocationError("execution.invocation must be an object")
    argv = spec.get("argv", [])
    if not isinstance(argv, list) or not all(isinstance(item, str) and item for item in argv):
        raise InvocationError("execution.invocation.argv must be an ordered list of nonempty strings")
    inputs = spec.get("inputs", {})
    if not isinstance(inputs, dict):
        raise InvocationError("execution.invocation.inputs must be an object")
    for name, declaration in inputs.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", str(name)) or not isinstance(declaration, dict):
            raise InvocationError("Invocation input declarations require safe names and object values")
        if declaration.get("kind", "file") not in {"file", "directory"}:
            raise InvocationError(f"Invocation input {name!r} kind must be file or directory")
        if "sha256" in declaration and not re.fullmatch(r"[0-9a-f]{64}", str(declaration["sha256"])):
            raise InvocationError("Input sha256 must be a lowercase SHA-256 digest")
    environment = spec.get("environment", {})
    if not isinstance(environment, dict):
        raise InvocationError("execution.invocation.environment must be an object")
    for name, value in environment.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)) or not isinstance(value, str) or not _ENV.fullmatch(value):
            raise InvocationError("Invocation environment values must be ${environment.NAME} references")
    for token in argv:
        match = _INPUT.fullmatch(token)
        if match and match.group(1) not in inputs:
            raise InvocationError(f"Invocation argv references undeclared input {match.group(1)!r}")
        if token.startswith("${") and token not in {_OUTPUT, _BUNDLE, _CONTRACT} and not match:
            raise InvocationError(f"Unsupported invocation symbol: {token}")
    for name, digest in spec.get("environment_sha256", {}).items():
        if name not in environment or any(pattern.search(name) for pattern in SECRET_PATTERNS):
            raise InvocationError("Only declared nonsecret environment values may be identity-bound")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise InvocationError("Environment sha256 must be a lowercase SHA-256 digest")


def resolve_invocation(
    spec: object,
    *,
    bundle_root: Path,
    output_root: Path,
    input_bindings: dict[str, str],
    environment_bindings: dict[str, str],
) -> ResolvedInvocation:
    """Expand frozen symbols into a deterministic argv without shell parsing."""
    if spec is None:
        default_argv = ["--bundle-root", str(bundle_root), "--output-root", str(output_root)]
        return ResolvedInvocation(default_argv, {}, {"protocol": "standard_v1", "argv": default_argv, "inputs": {}})
    validate_invocation_spec(spec)
    assert isinstance(spec, dict)
    declared = spec.get("inputs", {})
    unknown = sorted(set(input_bindings) - set(declared))
    if unknown:
        raise InvocationError(f"Undeclared runtime input binding(s): {unknown}")
    resolved_inputs: dict[str, str] = {}
    identities: dict[str, Any] = {}
    for name, declaration in declared.items():
        required = declaration.get("required", True)
        raw = input_bindings.get(name)
        if raw is None:
            if required:
                raise InvocationError(f"Missing required input binding: {name}")
            continue
        if raw.startswith("bundle:"):
            relative = Path(raw.removeprefix("bundle:"))
            if not str(relative) or relative.is_absolute() or ".." in relative.parts:
                raise InvocationError(f"Bundle input path traversal is forbidden: {name}")
            path = (bundle_root / relative).resolve()
            try:
                path.relative_to(bundle_root.resolve())
            except ValueError as exc:
                raise InvocationError(f"Bundle input escapes bundle root: {name}") from exc
        else:
            raw_path = Path(raw)
            if not raw_path.is_absolute() or ".." in raw_path.parts:
                raise InvocationError(f"Mounted input binding must be an absolute path without traversal: {name}")
            path = raw_path.resolve()
        if ".." in path.parts:
            raise InvocationError(f"Input binding path traversal is forbidden: {name}")
        if not path.exists():
            raise InvocationError(f"Input binding does not exist: {name}")
        if declaration.get("kind", "file") == "file" and not path.is_file():
            raise InvocationError(f"Input binding must be a file: {name}")
        if declaration.get("kind", "file") == "directory" and not path.is_dir():
            raise InvocationError(f"Input binding must be a directory: {name}")
        resolved_inputs[name] = str(path)
        try:
            identity = content_identity(path)
        except ValueError as exc:
            raise InvocationError(str(exc)) from exc
        expected = declaration.get("sha256")
        if expected is not None and identity["sha256"] != expected:
            raise InvocationError(f"CONTENT_IDENTITY_MISMATCH: {name}")
        identities[name] = {**identity, "expected_sha256": expected, "verified": expected is not None}

    argv: list[str] = []
    for token in spec.get("argv", []):
        match = _INPUT.fullmatch(token)
        if match:
            name = match.group(1)
            if name not in resolved_inputs:
                raise InvocationError(f"Unresolved input reference: {name}")
            argv.append(resolved_inputs[name])
        elif token == _OUTPUT:
            argv.append(str(output_root))
        elif token == _BUNDLE:
            argv.append(str(bundle_root))
        elif token == _CONTRACT:
            contract_snapshot = bundle_root / "resolved_contract.json"
            if not contract_snapshot.is_file():
                raise InvocationError("Bundle contract snapshot is missing")
            argv.append(str(contract_snapshot))
        else:
            argv.append(token)
    environment: dict[str, str] = {}
    for name, token in spec.get("environment", {}).items():
        match = _ENV.fullmatch(token)
        if match is None:
            raise InvocationError("Invalid environment symbol")
        key = match.group(1)
        if key not in environment_bindings:
            raise InvocationError(f"Missing required environment binding: {key}")
        environment[name] = environment_bindings[key]
        expected = spec.get("environment_sha256", {}).get(name)
        if expected is not None and sha256_bytes(environment[name].encode()) != expected:
            raise InvocationError(f"ENVIRONMENT_IDENTITY_MISMATCH: {name}")
    return ResolvedInvocation(argv, environment, {
        "protocol": "declared_v1", "argv": argv, "inputs": resolved_inputs,
        "contract_snapshot": str(bundle_root / "resolved_contract.json"),
        "environment_keys": sorted(environment),
        "input_identities": identities,
        "environment_identities": dict(spec.get("environment_sha256", {})),
    })
