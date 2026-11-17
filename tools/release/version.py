"""Authoritative Python version -> synchronized Pi SemVer and release tag."""

import argparse
import json
import re
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]


def versions(root=ROOT):
    python = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    match = re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:rc([1-9]\d*))?", python
    )
    if not match:
        raise ValueError("Use X.Y.Z or X.Y.ZrcN Python versions")
    semver = ".".join(match.groups()[:3])
    if match[4]:
        semver += "-rc." + match[4]
    return python, semver


def check(root=ROOT, tag=None, sync=False):
    python, semver = versions(root)
    for relative in ["package.json", "integrations/pi-expcon/package.json"]:
        path = root / relative
        manifest = json.loads(path.read_text())
        if sync:
            manifest["version"] = semver
            path.write_text(json.dumps(manifest, indent=2) + "\n")
        elif manifest["version"] != semver:
            raise ValueError(f"Version mismatch: {relative}")
    if tag is not None and tag != "v" + semver:
        raise ValueError("Tag must match the package version: v" + semver)
    return {
        "python": python,
        "pi": semver,
        "tag": "v" + semver,
        "prerelease": "-rc." in semver,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(tag=args.tag, sync=args.sync)))
