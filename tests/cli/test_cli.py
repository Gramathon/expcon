"""CLI behavior tests."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from expcon.cli import main


@pytest.fixture
def minimal_project(tmp_path):
    """Create a minimal project with an experiment."""
    contract = {
        "schema_version": 1,
        "experiment": {"id": "E00", "version": "v001", "title": "Test"},
        "hypothesis": {"statement": "Test hypothesis"},
        "source": {"repository": ".", "dirty_tree_allowed": False},
        "execution": {
            "allowed_backends": ["local"],
            "accelerator": {"type": "none"},
            "stages": [{"id": "main", "entrypoint": "run.py", "requires": []}],
        },
        "environment": {"python": "3.10", "dependency_lock": "uv.lock"},
        "evaluation": {"primary_metric": "accuracy", "threshold": 0.5},
        "outputs": {"required": ["metrics.json"]},
        "reproducibility": {"level": "seeded", "seed": 42},
        "scientific_parameters": {"seed": 42, "metric": "accuracy"},
    }
    exp_dir = tmp_path / "experiments" / "e00_v001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")

    # Create a runner script
    scripts_dir = exp_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "run.py").write_text(
        '#!/usr/bin/env python3\nimport json, sys\nfrom pathlib import Path\n'
        'out = Path(sys.argv[sys.argv.index("--output-root") + 1]) if "--output-root" in sys.argv else Path.cwd()\n'
        'out.mkdir(parents=True, exist_ok=True)\n'
        'metrics = {"accuracy": 0.85, "threshold": 0.5, "primary_metric_value": 0.85, "verdict": "SUPPORTED"}\n'
        '(out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")\n'
        'print(json.dumps({"status": "completed", "metrics": metrics}, indent=2))\n',
        encoding="utf-8",
    )

    # Create pyproject.toml for workspace root
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"test-project\"\nversion = \"0.1.0\"\n", encoding="utf-8")

    return tmp_path, exp_dir


class TestCLI:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_inspect_json(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        result = runner.invoke(main, ["inspect", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["experiment_id"] == "E00"
        assert data["state"] == "DRAFT"

    def test_validate(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "VALID"

    def test_freeze(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        result = runner.invoke(main, ["freeze", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "FROZEN"
        assert (exp_dir / "contract.lock.json").exists()

    def test_diff_no_changes(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        runner.invoke(main, ["freeze", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        result = runner.invoke(main, ["diff", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert not data["divergence_detected"]

    def test_bundle(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        runner.invoke(main, ["freeze", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        result = runner.invoke(main, ["bundle", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "BUNDLED"

    def test_verify_bundle(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        runner.invoke(main, ["freeze", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        runner.invoke(main, ["bundle", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        result = runner.invoke(main, ["verify-bundle", str(exp_dir / "bundle"), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "PASS"

    def test_run_local(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        runner.invoke(main, ["freeze", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        runner.invoke(main, ["bundle", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        result = runner.invoke(main, ["run", str(exp_dir / "EXPERIMENT.yaml"), "--backend", "local", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "SUBMITTED"
        assert data["backend"] == "local"

    def test_run_not_frozen(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        result = runner.invoke(main, ["run", str(exp_dir / "EXPERIMENT.yaml"), "--backend", "local", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "frozen" in data["error"].lower()

    def test_ps(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        result = runner.invoke(main, ["ps", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "runs" in data
