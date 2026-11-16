"""Content identities for explicitly declared local file/tree inputs."""

from pathlib import Path

from expcon.hashing.canonical import canonical_bytes
from expcon.hashing.digest import file_sha256, sha256_bytes
from expcon.util.path import contained_path


def content_identity(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("Input symlinks are outside the content-tree boundary")
    if path.is_file():
        return {
            "algorithm": "sha256",
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
        }
    if not path.is_dir():
        raise ValueError("Input is not a regular file or directory")
    files = []
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            raise ValueError("Input tree symlinks are not supported")
        if child.is_file():
            relative = child.relative_to(path).as_posix()
            checked = contained_path(path, relative)
            files.append(
                {
                    "path": relative,
                    "sha256": file_sha256(checked),
                    "size_bytes": checked.stat().st_size,
                }
            )
    payload = {"algorithm": "expcon-input-tree-v1", "files": files}
    return {**payload, "sha256": sha256_bytes(canonical_bytes(payload))}
