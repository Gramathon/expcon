"""CLI behavior tests."""

import json
import sys

import pytest
import yaml
from click.testing import CliRunner
from importlib.resources import files

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
            "stages": [{"id": "main", "entrypoint": "scripts/run.py", "requires": []}],
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

    def test_run_local_refuses_unprovisioned_frozen_environment(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        runner.invoke(main, ["freeze", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        runner.invoke(main, ["bundle", str(exp_dir / "EXPERIMENT.yaml"), "--json"])
        result = runner.invoke(main, ["run", str(exp_dir / "EXPERIMENT.yaml"), "--backend", "local", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "environment preflight failed" in data["error"].lower()

    def test_failed_child_records_stage_failed_before_terminal_run_failure(self, minimal_project, monkeypatch):
        tmp_path, exp_dir = minimal_project
        (exp_dir / "scripts/run.py").write_text("import sys; print('boom', file=sys.stderr); raise SystemExit(9)\n")
        monkeypatch.setattr(
            "expcon.cli.commands.preflight_local_environment",
            lambda *_: {"python_executable": sys.executable, "status": "PASS"},
        )
        runner = CliRunner()
        assert runner.invoke(main, ["freeze", str(exp_dir / "EXPERIMENT.yaml"), "--json"]).exit_code == 0
        assert runner.invoke(main, ["bundle", str(exp_dir / "EXPERIMENT.yaml"), "--json"]).exit_code == 0
        result = runner.invoke(main, ["run", str(exp_dir / "EXPERIMENT.yaml"), "--backend", "local", "--json"])
        assert result.exit_code == 1
        runs = sorted((tmp_path / ".expcon/runs").iterdir())
        events = [json.loads(line)["event"] for line in (runs[-1] / "events.jsonl").read_text().splitlines()]
        assert events[-2:] == ["STAGE_FAILED", "FAILED_EXECUTION"]

    def test_run_not_frozen(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        result = runner.invoke(main, ["run", str(exp_dir / "EXPERIMENT.yaml"), "--backend", "local", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "frozen" in data["error"].lower()

    def test_complete_local_fixture_workflow_preserves_repeat_attempts(self, minimal_project, monkeypatch):
        tmp_path, exp_dir = minimal_project
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("expcon.cli.commands.preflight_local_environment", lambda *_: {
            "python_executable": sys.executable, "python": sys.version, "status": "PASS"})
        # This is a synthetic CLI fixture, not the later real ML validation.
        data = yaml.safe_load((exp_dir / "EXPERIMENT.yaml").read_text())
        data["evaluation"]["acceptance"] = {"metric": "accuracy", "operator": ">=", "threshold": 0.8}
        (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(data))
        runner = CliRunner()
        for command in ("validate", "freeze", "bundle"):
            result = runner.invoke(main, [command, str(exp_dir), "--json"])
            assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["run", str(exp_dir), "--json"])
        assert result.exit_code == 0, result.output
        run_id = json.loads(result.output)["run_id"]
        for command in ("fetch", "verify", "verify", "adjudicate", "adjudicate"):
            result = runner.invoke(main, [command, run_id, "--json"])
            assert result.exit_code == 0, (command, result.output, result.exception)
        assert json.loads(result.output)["scientific_verdict"] == "SUPPORTED"
        run_dir = tmp_path / ".expcon/runs" / run_id
        assert len(list((run_dir / "verification_reports").glob("*.json"))) == 2
        assert len(list((run_dir / "adjudications").glob("*.json"))) == 2
        artifacts = runner.invoke(main, ["artifacts", run_id, "--json"])
        assert json.loads(artifacts.output)["count"] > 0

    def test_fake_remote_submission_pending_running_complete(self, minimal_project, monkeypatch):
        from expcon.runner.backends import RunStatus
        tmp_path, exp_dir = minimal_project
        monkeypatch.chdir(tmp_path)
        states = iter(["PENDING", "RUNNING", "COMPLETE"])
        class FakeBackend:
            def __init__(self, *_):
                pass
            def preflight(self, *_):
                return {"status": "READY"}
            def submit(self, bundle, context):
                return context.run_id
            def status(self, run_id):
                return RunStatus(run_id, next(states))
        monkeypatch.setattr("expcon.cli.commands.KaggleBackend", FakeBackend)
        data = yaml.safe_load((exp_dir / "EXPERIMENT.yaml").read_text())
        data["execution"]["allowed_backends"] = ["kaggle"]
        (exp_dir / "EXPERIMENT.yaml").write_text(yaml.safe_dump(data))
        runner = CliRunner()
        for command in ("freeze", "bundle"):
            result = runner.invoke(main, [command, str(exp_dir), "--json"])
            assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["run", str(exp_dir), "--backend", "kaggle", "--json"])
        assert result.exit_code == 0, result.output
        run_id = json.loads(result.output)["run_id"]
        for expected in ("RUNNING", "RESULTS_AVAILABLE"):
            result = runner.invoke(main, ["status", run_id, "--json"])
            assert result.exit_code == 0, result.output
            assert json.loads(result.output)["state"] == expected

    def test_ps(self, minimal_project):
        tmp_path, exp_dir = minimal_project
        runner = CliRunner()
        result = runner.invoke(main, ["ps", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "runs" in data

    def test_skill_resources_are_complete_and_safe(self):
        root = files("expcon").joinpath("resources", "skills", "experiment-contract")
        skill = root.joinpath("SKILL.md").read_text()
        assert "backend_playbooks" in skill
        for name in ("lifecycle.md", "scientific-vs-operational.md", "artifacts-and-evidence.md", "backends.md", "local.md", "kaggle.md", "colab.md", "tinker.md"):
            assert root.joinpath("references", name).is_file()
        assert "kaggle.json" not in skill.lower()
        assert "EXPCON_COLAB_ACCESS_TOKEN" not in skill

    def test_skill_playbooks_encode_backend_safety_rules(self):
        root = files("expcon").joinpath("resources", "skills", "experiment-contract", "references")
        kaggle = root.joinpath("kaggle.md").read_text()
        colab = root.joinpath("colab.md").read_text()
        backends = root.joinpath("backends.md").read_text()
        lifecycle = root.joinpath("lifecycle.md").read_text()
        scientific = root.joinpath("scientific-vs-operational.md").read_text()
        tinker = root.joinpath("tinker.md").read_text()

        assert "Public API" in kaggle and "Kaggle CLI" in kaggle
        assert "exact version" in kaggle
        assert "latest" in kaggle and "Never fetch" in kaggle
        assert "Kaggle COMPLETE != EVIDENCE_VERIFIED" in lifecycle
        assert "execute=false" in colab and "fetch=false" in colab
        assert "browser" in colab and "private" in colab
        assert "Transport fallback" in backends and "Backend fallback" in backends
        assert "expcon diff" in scientific
        assert "Tinker is a managed distributed LLM" in tinker
        assert "weights_and_optimizer" in tinker
        assert "provider=tinker" in tinker

    def test_skill_install_copies_references_and_status_detects_missing(self, tmp_path):
        runner = CliRunner()
        target = tmp_path / "skills"
        target.mkdir()
        result = runner.invoke(main, ["skill", "install", "--target", str(target), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["compatibility"]["compatible"]
        installed = target / "experiment-contract"
        assert (installed / "references" / "kaggle.md").exists()
        assert (installed / "references" / "tinker.md").exists()
        (installed / "references" / "colab.md").unlink()
        result = runner.invoke(main, ["skill", "status", "--target", str(target), "--json"])
        assert result.exit_code == 0
        assert "colab.md" in json.loads(result.output)["installed"]["missing_references"]
