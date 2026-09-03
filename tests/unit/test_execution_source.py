"""Generic execution-source closure and DRAFT preflight tests."""

from pathlib import Path
import os
import subprocess

import pytest
import yaml

from expcon.bundle.bundle import BundleBuilder
from expcon.bundle.source import SourceResolutionError, resolve_source_closure
from expcon.contract.contract import load_contract
from expcon.contract.canonical import compute_execution_identity_hash_v2, compute_scientific_design_hash_v2
from expcon.contract.operations import freeze_experiment


def _contract(root: Path, include: list[str]) -> dict:
    return {
        "schema_version": 1,
        "experiment": {"id": "E00", "version": "v001", "title": "closure"},
        "hypothesis": {"statement": "fixed"},
        "source": {"repository": str(root)},
        "execution": {
            "allowed_backends": ["local"],
            "source": {"entrypoint": "runner.py", "include": include},
            "stages": [{"id": "main", "entrypoint": "runner.py"}],
        },
        "evaluation": {"primary_metric": "accuracy"},
        "outputs": {"required": ["metrics.json"]},
        "reproducibility": {"level": "seeded"},
        "scientific_parameters": {"fixed": True},
    }


def _experiment(tmp_path: Path, include: list[str] = ["src/pkg"]) -> tuple[Path, dict]:
    (tmp_path / "src/pkg/sub").mkdir(parents=True)
    (tmp_path / "src/pkg/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src/pkg/sub/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src/pkg/sub/helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "runner.py").write_text("from pkg.sub.helper import VALUE\nprint(VALUE)\n", encoding="utf-8")
    exp = tmp_path / "experiments/e00"
    exp.mkdir(parents=True)
    contract = _contract(tmp_path, include)
    (exp / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
    return exp, contract


def test_declared_package_closure_is_deterministic_and_importable(tmp_path):
    exp, _ = _experiment(tmp_path)
    closure = resolve_source_closure(exp, load_contract(exp / "EXPERIMENT.yaml"))
    assert [entry.repository_relative_path.as_posix() for entry in closure.entries] == [
        "src/pkg/__init__.py", "src/pkg/sub/__init__.py", "src/pkg/sub/helper.py"
    ]
    assert [entry.bundle_relative_path.as_posix() for entry in closure.entries] == [
        "source/pkg/__init__.py", "source/pkg/sub/__init__.py", "source/pkg/sub/helper.py"
    ]
    result = BundleBuilder(exp).preflight()
    assert result["status"] == "PASS"
    assert result["ephemeral"] is True
    assert not (exp / "bundle").exists()


def test_closure_bytes_change_execution_not_science(tmp_path):
    exp, contract = _experiment(tmp_path)
    first = resolve_source_closure(exp, load_contract(exp / "EXPERIMENT.yaml"))
    (tmp_path / "src/pkg/sub/helper.py").write_text("VALUE = 2\n", encoding="utf-8")
    second = resolve_source_closure(exp, load_contract(exp / "EXPERIMENT.yaml"))
    assert first.sha256 != second.sha256
    assert compute_scientific_design_hash_v2(contract) == compute_scientific_design_hash_v2(contract)
    assert compute_execution_identity_hash_v2(contract, "runner", first.sha256) != compute_execution_identity_hash_v2(contract, "runner", second.sha256)


def test_missing_traversal_and_symlink_escape_fail_closed(tmp_path):
    exp, _ = _experiment(tmp_path, ["missing"])
    with pytest.raises(SourceResolutionError, match="missing"):
        resolve_source_closure(exp, load_contract(exp / "EXPERIMENT.yaml"))
    exp, _ = _experiment(tmp_path / "traversal", ["../outside"])
    with pytest.raises(SourceResolutionError, match="safe repository-relative"):
        resolve_source_closure(exp, load_contract(exp / "EXPERIMENT.yaml"))
    exp, _ = _experiment(tmp_path / "symlink", ["linked"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escape.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "symlink/linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SourceResolutionError, match="escapes repository"):
        resolve_source_closure(exp, load_contract(exp / "EXPERIMENT.yaml"))


def test_detectable_undeclared_local_import_fails_preflight(tmp_path):
    exp, _ = _experiment(tmp_path, [])
    with pytest.raises(Exception, match="absent from declared execution.source.include"):
        BundleBuilder(exp).preflight()


def test_frozen_bundle_copies_exact_declared_source_bytes(tmp_path):
    exp, _ = _experiment(tmp_path)
    freeze_experiment(exp, tmp_path)
    bundle, _ = BundleBuilder(exp).build()
    source = tmp_path / "src/pkg/sub/helper.py"
    bundled = bundle / "source/pkg/sub/helper.py"
    assert bundled.read_bytes() == source.read_bytes()
    # The bundled import wins even after the checkout changes.
    source.write_text("VALUE = 99\n", encoding="utf-8")
    result = subprocess.run(
        ["python3", str(bundle / "runner/runner.py")],
        env={**os.environ, "PYTHONPATH": str(bundle / "source")},
        text=True, capture_output=True, check=True,
    )
    assert result.stdout.strip() == "1"
