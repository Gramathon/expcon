"""Path-safe source and entrypoint discovery for experiment bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from expcon.contract.contract import ExperimentContract
from expcon.hashing.digest import file_sha256
from expcon.hashing.canonical import canonical_bytes
from expcon.hashing.digest import sha256_bytes
from expcon.hashing.manifest import DirectoryManifest, ManifestEntry, compute_directory_manifest
from expcon.util.path import find_workspace_root


class SourceResolutionError(ValueError):
    """A declared source path is not a safe repository-relative path."""


@dataclass(frozen=True)
class ResolvedEntrypoint:
    """A repository source file and its deterministic bundle representation."""

    declared_path: str
    source_path: Path
    bundle_relative_path: Path
    sha256: str


@dataclass(frozen=True)
class SourceClosureEntry:
    """One declared repository file needed by an execution entrypoint."""

    repository_relative_path: Path
    source_path: Path
    bundle_relative_path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SourceClosure:
    """Deterministic, explicitly declared executable repository source."""

    entrypoint: ResolvedEntrypoint
    entries: tuple[SourceClosureEntry, ...]

    def to_dict(self) -> dict:
        return {
            "entrypoint": {
                "declared_path": self.entrypoint.declared_path,
                "bundle_relative_path": self.entrypoint.bundle_relative_path.as_posix(),
                "sha256": self.entrypoint.sha256,
            },
            "files": [
                {
                    "repository_relative_path": entry.repository_relative_path.as_posix(),
                    "bundle_relative_path": entry.bundle_relative_path.as_posix(),
                    "sha256": entry.sha256,
                    "size_bytes": entry.size_bytes,
                }
                for entry in self.entries
            ],
        }

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical_bytes(self.to_dict()))


def repository_root(experiment_dir: Path, contract: ExperimentContract) -> Path:
    """Resolve the repository root for a contract without escaping the workspace."""
    declared = str(contract.get("source", "repository", default="."))
    if declared == ".":
        root = find_workspace_root(experiment_dir.parent)
        # Lightweight/test-only experiments may not live beneath a project marker.
        if root in {experiment_dir, experiment_dir.parent}:
            root = experiment_dir.parent.parent
    else:
        candidate = Path(declared)
        root = candidate.resolve() if candidate.is_absolute() else (experiment_dir / candidate).resolve()
    if not root.is_dir():
        raise SourceResolutionError(f"Repository root does not exist: {root}")
    return root


def _normalise_declared_path(value: object) -> Path:
    raw = str(value)
    path = Path(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SourceResolutionError(f"Entrypoint must be a safe repository-relative path: {raw!r}")
    return path


def _resolve_source_path(repo_root: Path, value: object) -> Path:
    """Resolve a declared source include without permitting checkout escape."""
    declared = _normalise_declared_path(value)
    candidate = repo_root / declared
    # Resolve follows symlinks, then require the destination remains in-repo.
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise SourceResolutionError(f"Source include escapes repository root: {declared.as_posix()!r}") from exc
    if not resolved.exists():
        raise SourceResolutionError(f"Declared execution source is missing: {declared.as_posix()}")
    return resolved


def resolve_entrypoint(experiment_dir: Path, contract: ExperimentContract, value: object) -> ResolvedEntrypoint:
    """Resolve an entrypoint from repository root, then legacy experiment root.

    The bundle path preserves the declared relative path beneath ``runner/``.
    This avoids collisions for nested source files while keeping the original
    repository-relative identity explicit in the source manifest.
    """
    declared = _normalise_declared_path(value)
    repo_root = repository_root(experiment_dir, contract)
    candidates = (repo_root / declared, experiment_dir / declared)
    for candidate in candidates:
        resolved = candidate.resolve()
        base = repo_root if candidate == candidates[0] else experiment_dir.resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise SourceResolutionError(f"Entrypoint escapes its source root: {value!r}") from exc
        if resolved.is_file():
            return ResolvedEntrypoint(
                declared_path=declared.as_posix(),
                source_path=resolved,
                bundle_relative_path=Path("runner") / declared,
                sha256=file_sha256(resolved),
            )
    raise SourceResolutionError(f"Entrypoint source file not found: {declared.as_posix()}")


def resolve_entrypoints(experiment_dir: Path, contract: ExperimentContract) -> list[ResolvedEntrypoint]:
    entries: list[ResolvedEntrypoint] = []
    seen_bundle_paths: set[Path] = set()
    for stage in contract.get("execution", "stages", default=[]):
        if not isinstance(stage, dict) or "entrypoint" not in stage:
            continue
        resolved = resolve_entrypoint(experiment_dir, contract, stage["entrypoint"])
        if resolved.bundle_relative_path in seen_bundle_paths:
            raise SourceResolutionError(f"Duplicate bundled entrypoint path: {resolved.bundle_relative_path}")
        seen_bundle_paths.add(resolved.bundle_relative_path)
        entries.append(resolved)
    return entries


def resolve_source_closure(experiment_dir: Path, contract: ExperimentContract) -> SourceClosure:
    """Resolve the declared execution source closure.

    ``execution.source.include`` is authoritative.  It accepts files and
    package directories rooted in the declared repository; automatic import
    discovery is intentionally not used to define the frozen closure.
    """
    spec = contract.get("execution", "source", default=None)
    entries = resolve_entrypoints(experiment_dir, contract)
    if spec is None:
        if len(entries) != 1:
            raise SourceResolutionError("execution.source is required for multiple or ambiguous entrypoints")
        return SourceClosure(entries[0], ())
    if not isinstance(spec, dict):
        raise SourceResolutionError("execution.source must be an object")
    declared_entrypoint = spec.get("entrypoint")
    if not isinstance(declared_entrypoint, str):
        raise SourceResolutionError("execution.source.entrypoint is required")
    matching = [entry for entry in entries if entry.declared_path == declared_entrypoint]
    if len(matching) != 1:
        raise SourceResolutionError("execution.source.entrypoint must identify exactly one declared stage entrypoint")
    includes = spec.get("include", [])
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        raise SourceResolutionError("execution.source.include must be an ordered list of repository-relative paths")
    repo_root = repository_root(experiment_dir, contract)
    resolved: dict[Path, SourceClosureEntry] = {}
    for declared in includes:
        path = _resolve_source_path(repo_root, declared)
        files = [path] if path.is_file() else sorted(
            item for item in path.rglob("*")
            if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
        )
        for file_path in files:
            # A symlink within an included directory can still point outside.
            final = file_path.resolve()
            try:
                repo_relative = final.relative_to(repo_root.resolve())
            except ValueError as exc:
                raise SourceResolutionError(f"Source include contains a symlink escape: {file_path}") from exc
            # Python src-layout packages must be importable directly from
            # bundle/source; non-src files retain their repository layout.
            bundle_relative = Path("source") / (Path(*repo_relative.parts[1:]) if repo_relative.parts[0] == "src" else repo_relative)
            existing = resolved.get(repo_relative)
            entry = SourceClosureEntry(
                repository_relative_path=repo_relative,
                source_path=final,
                bundle_relative_path=bundle_relative,
                sha256=file_sha256(final),
                size_bytes=final.stat().st_size,
            )
            if existing is not None and existing.sha256 != entry.sha256:
                raise SourceResolutionError(f"Ambiguous execution source inclusion: {repo_relative.as_posix()}")
            resolved[repo_relative] = entry
    closure = SourceClosure(matching[0], tuple(resolved[key] for key in sorted(resolved)))
    expected = spec.get("expected_sha256")
    if expected is not None and expected != closure.sha256:
        raise SourceResolutionError(
            f"Execution source closure SHA256 mismatch: expected {expected}, observed {closure.sha256}"
        )
    return closure


def source_manifest(experiment_dir: Path, contract: ExperimentContract) -> DirectoryManifest:
    """Compute generic repository source provenance and guarantee stage entries."""
    root = repository_root(experiment_dir, contract)
    manifest = compute_directory_manifest(root, skip_hidden=True, include=["src/", "scripts/", "configs/"])
    # Bytecode caches are host-runtime byproducts, never declared repository
    # source.  Keeping them out avoids transport-dependent source provenance.
    manifest.entries = [
        entry for entry in manifest.entries
        if "__pycache__" not in Path(entry.relative_path).parts and not entry.relative_path.endswith(".pyc")
    ]
    known = {entry.relative_path for entry in manifest.entries}
    for entrypoint in resolve_entrypoints(experiment_dir, contract):
        relative = str(entrypoint.source_path.relative_to(root))
        if relative not in known:
            manifest.entries.append(
                ManifestEntry(relative, entrypoint.source_path.stat().st_size, entrypoint.sha256)
            )
            known.add(relative)
    manifest.entries.sort(key=lambda item: item.relative_path)
    return manifest


def legacy_source_manifest(experiment_dir: Path, contract: ExperimentContract) -> DirectoryManifest:
    """Reproduce pre-v2 repository source discovery for historical locks.

    This intentionally retains every regular file the historical discovery
    algorithm included, including bytecode caches.  It exists only to verify
    old frozen identities; new v2 identities use :func:`source_manifest`.
    """
    root = repository_root(experiment_dir, contract)
    manifest = compute_directory_manifest(root, skip_hidden=True, include=["src/", "scripts/", "configs/"])
    known = {entry.relative_path for entry in manifest.entries}
    for entrypoint in resolve_entrypoints(experiment_dir, contract):
        relative = str(entrypoint.source_path.relative_to(root))
        if relative not in known:
            manifest.entries.append(
                ManifestEntry(relative, entrypoint.source_path.stat().st_size, entrypoint.sha256)
            )
    manifest.entries.sort(key=lambda item: item.relative_path)
    return manifest


def canonical_source_manifest(manifest: DirectoryManifest) -> dict:
    """Return transport-independent repository-source provenance.

    ``DirectoryManifest.to_dict()`` retains an absolute root for diagnostics.
    That root must not participate in a bundle-content identity because it is a
    host transport detail rather than executable content.
    """
    return {
        "entries": [
            {
                "relative_path": entry.relative_path,
                "size_bytes": entry.size_bytes,
                "sha256": entry.sha256,
            }
            for entry in sorted(manifest.entries, key=lambda item: item.relative_path)
        ]
    }
