"""Regression checks for version drift and immutable release payloads."""

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSION = runpy.run_path(str(ROOT / "tools/release/version.py"))


def test_version_gate_rejects_mismatches_and_syncs_rc(tmp_path):
    (tmp_path / "integrations/pi-expcon").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.2.0rc1"\n')
    for path in [
        tmp_path / "package.json",
        tmp_path / "integrations/pi-expcon/package.json",
    ]:
        path.write_text('{"version":"0.1.0"}')
    with pytest.raises(ValueError, match="Version mismatch"):
        VERSION["check"](tmp_path)
    result = VERSION["check"](tmp_path, sync=True)
    assert result["tag"] == "v0.2.0-rc.1"
    assert result["prerelease"] is True
    assert VERSION["check"](tmp_path, tag=result["tag"]) == result
    with pytest.raises(ValueError, match="Tag must match"):
        VERSION["check"](tmp_path, tag="v0.2.0")


def test_manifest_covers_exact_payload_and_refuses_rerun(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "fixture.json").write_text('{"status":"PASS"}')
    current = VERSION["check"]()
    for name in [
        f"expcon-{current['python']}-py3-none-any.whl",
        f"expcon-{current['python']}.tar.gz",
        f"pi-expcon-{current['pi']}.tgz",
    ]:
        (release / name).write_bytes(b"test fixture, not a distribution")
    command = [
        sys.executable,
        str(ROOT / "tools/release/manifest.py"),
        str(release),
        str(evidence),
        "--tag",
        current["tag"],
    ]
    subprocess.run(command, check=True)
    for line in (release / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((release / name).read_bytes()).hexdigest() == digest
    assert (
        json.loads((release / "validation-summary.json").read_text())["tag"]
        == current["tag"]
    )
    assert subprocess.run(command, capture_output=True).returncode != 0
