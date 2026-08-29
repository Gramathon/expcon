"""Hashing and canonicalisation module.

All identity-relevant operations live here.  The fundamental invariant:
canonical JSON must be deterministic regardless of key ordering, whitespace,
or YAML formatting differences.
"""

from expcon.hashing.canonical import canonical_json, canonical_dict, canonical_bytes
from expcon.hashing.digest import (
    sha256_bytes,
    sha256_file,
    sha256_text,
    sha256_hex,
    file_sha256,
    digest_file,
    DIGEST_BLOCK_SIZE,
)
from expcon.hashing.manifest import (
    ManifestEntry,
    compute_directory_manifest,
    verify_directory_manifest,
    manifest_hash,
)

__all__ = [
    "canonical_json",
    "canonical_dict",
    "canonical_bytes",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "sha256_hex",
    "file_sha256",
    "digest_file",
    "DIGEST_BLOCK_SIZE",
    "ManifestEntry",
    "compute_directory_manifest",
    "verify_directory_manifest",
    "manifest_hash",
]
