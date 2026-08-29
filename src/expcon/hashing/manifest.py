"""Directory manifest computation and verification.

A manifest maps relative paths to (size, sha256) tuples.  It is used for
source trees, bundle contents, evidence packages, and artifact directories.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from expcon.hashing.digest import file_sha256


@dataclass(frozen=True)
class ManifestEntry:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass
class DirectoryManifest:
    root: Path
    entries: list[ManifestEntry] = field(default_factory=list)
    skip_hidden: bool = True
    follow_symlinks: bool = False

    def add(self, relative_path: str, size_bytes: int, sha256: str) -> None:
        self.entries.append(ManifestEntry(relative_path, size_bytes, sha256))

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "entries": [
                {"relative_path": e.relative_path, "size_bytes": e.size_bytes, "sha256": e.sha256}
                for e in self.entries
            ],
        }

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["relative_path", "size_bytes", "sha256"])
        for e in sorted(self.entries, key=lambda x: x.relative_path):
            writer.writerow([e.relative_path, e.size_bytes, e.sha256])
        return buf.getvalue()


def compute_directory_manifest(
    root: Path,
    skip_hidden: bool = True,
    follow_symlinks: bool = False,
    include: Optional[list[str]] = None,
) -> DirectoryManifest:
    """Walk *root* and compute a manifest of all regular files."""
    root = Path(root).resolve()
    manifest = DirectoryManifest(root=root, skip_hidden=skip_hidden, follow_symlinks=follow_symlinks)
    seen_paths: set[Path] = set()

    for path in sorted(root.rglob("*")):
        if path in seen_paths:
            continue
        seen_paths.add(path)

        if not path.is_file():
            continue
        if skip_hidden and any(part.startswith(".") for part in path.relative_to(root).parts):
            continue

        rel = path.relative_to(root)
        if include is not None:
            if not any(str(rel).startswith(prefix) for prefix in include):
                continue

        size = path.stat().st_size
        digest = file_sha256(path)
        manifest.add(str(rel), size, digest)

    return manifest


def verify_directory_manifest(
    root: Path,
    manifest: DirectoryManifest,
) -> dict:
    """Verify every entry in *manifest* exists and matches.

    Returns a dict:
      status: PASS | FAIL
      mismatches: list of {relative_path, reason}
    """
    mismatches = []
    root = Path(root).resolve()

    for entry in manifest.entries:
        target = root / entry.relative_path
        if not target.exists():
            mismatches.append({"relative_path": entry.relative_path, "reason": "MISSING"})
            continue
        if not target.is_file():
            mismatches.append({"relative_path": entry.relative_path, "reason": "NOT_A_FILE"})
            continue
        actual_size = target.stat().st_size
        if actual_size != entry.size_bytes:
            mismatches.append(
                {
                    "relative_path": entry.relative_path,
                    "reason": f"SIZE_MISMATCH expected={entry.size_bytes} actual={actual_size}",
                }
            )
            continue
        actual_sha = file_sha256(target)
        if actual_sha != entry.sha256:
            mismatches.append(
                {
                    "relative_path": entry.relative_path,
                    "reason": f"HASH_MISMATCH expected={entry.sha256} actual={actual_sha}",
                }
            )

    # Check for extra files not in manifest
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root))
        if not any(e.relative_path == rel for e in manifest.entries):
            mismatches.append({"relative_path": rel, "reason": "EXTRA_FILE"})

    return {
        "status": "PASS" if not mismatches else "FAIL",
        "mismatches": mismatches,
        "entry_count": len(manifest.entries),
    }


def manifest_hash(manifest: DirectoryManifest) -> str:
    """Return the SHA-256 of the canonical JSON of a manifest."""
    from expcon.hashing.canonical import canonical_bytes
    from expcon.hashing.digest import sha256_bytes

    return sha256_bytes(canonical_bytes(manifest.to_dict()))
