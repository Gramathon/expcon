"""Seal the exact release payload and validation reports; never overwrite assets."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from version import check


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create(directory, evidence, tag):
    version = check(tag=tag)
    expected = {
        f"expcon-{version['python']}-py3-none-any.whl",
        f"expcon-{version['python']}.tar.gz",
        f"pi-expcon-{version['pi']}.tgz",
    }
    actual = {p.name for p in directory.iterdir() if p.is_file()}
    if actual != expected:
        raise ValueError(f"Unexpected release assets: {actual ^ expected}")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    reports = sorted(evidence.rglob("*.json"))
    if not reports:
        raise ValueError("Validation reports are required")
    summary = {
        "status": "PASS",
        "commit": sha,
        "tag": tag,
        "versions": version,
        "workflow": os.environ.get(
            "GITHUB_WORKFLOW_REF", "local-unpublished-validation"
        ),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "reports": {
            str(p.relative_to(evidence)): json.loads(p.read_text()) for p in reports
        },
        "artifacts": {name: digest(directory / name) for name in sorted(expected)},
    }
    (directory / "validation-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    (directory / "release-notes.md").write_text(
        f"# Expcon {tag}\n\nPython controller/CLI/MCP and standalone Pi integration.\n\n"
        f"Source: `{sha}`. Python: `{version['python']}`. Pi: `{version['pi']}`.\n\n"
        "Validation gates: Python 3.10–3.12 tests, CPU integrity, clean wheel installs, MCP, Pi 1.5.2 TypeScript/unit tests and packaged Pi/MCP lifecycle.\n"
        "See validation-summary.json for executed reports. Remote providers remain unverified; trusted-host execution is not sandboxed.\n"
    )
    payload = sorted(p for p in directory.iterdir() if p.is_file())
    (directory / "SHA256SUMS").write_text(
        "".join(f"{digest(p)}  {p.name}\n" for p in payload)
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    create(args.directory, args.evidence, args.tag)
