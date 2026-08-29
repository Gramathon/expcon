"""SHA-256 digest utilities.

Never hash ambiguous concatenated raw strings.  Always hash structured
canonical objects via :mod:`expcon.hashing.canonical`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

DIGEST_BLOCK_SIZE = 1024 * 1024  # 1 MiB


def sha256_bytes(data: bytes) -> str:
    """Return hex SHA-256 of *data*."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return hex SHA-256 of UTF-8 encoded *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_hex(obj) -> str:
    """Return hex SHA-256 of the canonical JSON representation of *obj*."""
    from expcon.hashing.canonical import canonical_bytes

    return sha256_bytes(canonical_bytes(obj))


def file_sha256(path: Path) -> str:
    """Stream a file and return its hex SHA-256."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(DIGEST_BLOCK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


# Alias for clarity
sha256_file = file_sha256


def digest_file(path: Path) -> str:
    """Alias for file_sha256."""
    return file_sha256(path)
