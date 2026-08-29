"""Path safety utilities - archive traversal protection."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path


def find_workspace_root(start: Path | str | None = None) -> Path:
    """Find the workspace root by looking for pyproject.toml or .git."""
    if start is None:
        start = Path.cwd()
    path = Path(start).resolve()
    for parent in [path, *path.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return path


def is_path_safe(path: Path, base: Path) -> bool:
    """Check that *path* is inside *base* (no traversal)."""
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def safe_extract_zip(zip_path: Path | str, dest: Path | str) -> list[str]:
    """Safely extract a zip archive, preventing path traversal.

    Returns list of extracted file paths.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            member_path = (dest / member).resolve()
            if not is_path_safe(member_path, dest):
                raise ValueError(f"Path traversal detected in archive: {member}")
            # Also reject symlinks
            if member.endswith("/") or member.endswith(os.sep):
                continue
            zf.extract(member, dest)
            extracted.append(member)

    return extracted
