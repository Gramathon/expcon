"""Expcon CLI commands."""

from __future__ import annotations

import json
import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

import click

from expcon.contract.contract import load_contract
from expcon.contract.operations import validate_experiment, freeze_experiment, diff_experiment
from expcon.contract.canonical import contract_identity
from expcon.lifecycle.experiment_state import ExperimentLifecycle
from expcon.bundle.bundle import BundleBuilder, BundleVerifier, verify_frozen_bundle_compatibility
from expcon.runner.runner import StageRunner, RunContext
from expcon.runner.observation import observe
from expcon.runner.invocation import resolve_invocation
from expcon.runner.environment import EnvironmentError, preflight_local_environment
from expcon.runner.backends import ExecutionBackend, LocalBackend, KaggleBackend, _valid_kaggle_ref
from expcon.backends.colab import ColabApiClient, ColabBackend, ColabClientError
from expcon.backends.kaggle import KaggleApiTransport, KaggleCliTransport, KaggleTransportError
from expcon.backends.tinker import TinkerBackend, TinkerCliTransport, TinkerSdkTransport
from expcon.evidence.evidence import EvidenceVerifier, bind_evidence
from expcon.evidence.collection import collect_outputs, locate_evidence
from expcon.util.json_io import atomic_json
from expcon.adjudication.adjudication import Adjudicator
from expcon.workspace.workspace import WorkspaceError, WorkspaceManager
from expcon.artifacts.artifact import ArtifactRegistry
from expcon.util.path import find_workspace_root

SKILL_REFERENCE_NAMES = (
    "lifecycle.md",
    "scientific-vs-operational.md",
    "artifacts-and-evidence.md",
    "backends.md",
    "local.md",
    "kaggle.md",
    "colab.md",
    "tinker.md",
)


def _skill_root():
    return files("expcon").joinpath("resources").joinpath("skills").joinpath("experiment-contract")


def _skill_health(root) -> dict[str, Any]:
    """Check deterministic completeness/compatibility of a skill bundle."""
    import expcon
    import yaml

    skill_file = root.joinpath("SKILL.md") if hasattr(root, "joinpath") else Path(root) / "SKILL.md"
    present = skill_file.is_file()
    metadata: dict[str, Any] = {}
    if present:
        text = skill_file.read_text(encoding="utf-8")
        if text.startswith("---"):
            metadata = yaml.safe_load(text.split("---", 2)[1]) or {}
    references = root.joinpath("references") if hasattr(root, "joinpath") else Path(root) / "references"
    missing = [name for name in SKILL_REFERENCE_NAMES if not references.joinpath(name).is_file()]
    minimum = str(metadata.get("metadata", {}).get("minimum_expcon_version", "0.0.0"))
    def version_tuple(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in value.split(".") if part.isdigit())
    compatible = present and not missing and version_tuple(expcon.__version__) >= version_tuple(minimum)
    return {"present": present, "references_present": not missing, "missing_references": missing,
            "skill_version": metadata.get("metadata", {}).get("skill_version"),
            "minimum_expcon_version": minimum, "supported_contract_schema": metadata.get("metadata", {}).get("supported_contract_schema"),
            "compatible": compatible}


def _output(data: Any, as_json: bool = False) -> None:
    """Output data in JSON or human-readable format."""
    if as_json:
        click.echo(json.dumps(data, indent=2, sort_keys=True, default=str))
    else:
        _print_human(data)


def _print_human(data: Any, indent: int = 0) -> None:
    """Pretty-print data for human consumption."""
    prefix = "  " * indent
    if isinstance(data, dict):
        for key, value in sorted(data.items()):
            if isinstance(value, (dict, list)) and value:
                click.echo(f"{prefix}{key}:")
                _print_human(value, indent + 1)
            elif isinstance(value, list):
                click.echo(f"{prefix}{key}: {value}")
            else:
                click.echo(f"{prefix}{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            _print_human(item, indent)
    else:
        click.echo(f"{prefix}{data}")


# ─── init ────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--name", help="Create an experiment contract with this ID (e.g. E13)")
@click.option("--version", default="v001", help="Version (default: v001)")
@click.option("--title", default=None, help="Human-readable title")
@click.option("--description", default="", help="Description")
@click.option("--output-dir", default="experiments", help="Output directory")
@click.option("--backend", default="local", help="Default backend")
@click.option("--hypothesis", default="...", help="Hypothesis statement")
@click.option("--primary-metric", default="accuracy", help="Primary metric")
@click.option("--required-output", multiple=True, help="Required output files")
@click.option("--python", default="3.12", help="Python version")
@click.option("--reproducibility-level", default="seeded", help="Reproducibility level")
@click.option("--seed", default=42, help="Random seed")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def init_cmd(name, version, title, description, output_dir, backend, hypothesis,
             primary_metric, required_output, python, reproducibility_level, seed, as_json):
    """Initialize an Expcon project, or create a contract with --name."""
    if name is None:
        root = Path.cwd()
        control = root / ".expcon"
        for child in ("runs", "artifacts", "state"):
            (control / child).mkdir(parents=True, exist_ok=True)
        config = control / "config.toml"
        if not config.exists():
            config.write_text("schema_version = 1\n", encoding="utf-8")
        (root / "experiments").mkdir(exist_ok=True)
        fragment = control / "AGENTS.fragment.md"
        if not fragment.exists():
            fragment.write_text(
                files("expcon").joinpath("resources").joinpath("templates").joinpath("AGENTS.fragment.md").read_text(),
                encoding="utf-8",
            )
        _output({"status": "INITIALIZED", "project": str(root), "control": str(control),
                 "agents_fragment": str(fragment), "agents_md_preserved": (root / "AGENTS.md").exists()}, as_json)
        return

    if title is None:
        raise click.UsageError("--title is required when creating an experiment; omit --name for project initialization")
    exp_dir = Path(output_dir) / f"{name.lower()}_{version}"
    exp_dir.mkdir(parents=True, exist_ok=True)

    contract = {
        "schema_version": 1,
        "experiment": {
            "id": name,
            "version": version,
            "title": title,
            "description": description,
        },
        "hypothesis": {
            "statement": hypothesis,
        },
        "source": {
            "repository": ".",
            "dirty_tree_allowed": False,
        },
        "execution": {
            "allowed_backends": [backend],
            "accelerator": {"type": "none"},
            "stages": [
                {
                    "id": "main",
                    "entrypoint": "scripts/run_experiment.py",
                    "requires": [],
                }
            ],
        },
        "environment": {
            "python": python,
            "dependency_lock": "uv.lock",
        },
        "evaluation": {
            "primary_metric": primary_metric,
            "threshold": None,
        },
        "outputs": {
            "required": list(required_output) if required_output else ["metrics.json"],
        },
        "reproducibility": {
            "level": reproducibility_level,
            "seed": seed,
        },
        "scientific_parameters": {
            "seed": seed,
            "metric": primary_metric,
        },
    }

    contract_path = exp_dir / "EXPERIMENT.yaml"
    import yaml

    contract_path.write_text(yaml.safe_dump(contract, default_flow_style=False, sort_keys=False), encoding="utf-8")

    result = {
        "status": "CREATED",
        "experiment_id": name,
        "version": version,
        "path": str(exp_dir),
        "contract_path": str(contract_path),
    }
    _output(result, as_json)


# ─── distribution health and skill ──────────────────────────────────────────

@click.command(name="doctor")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def doctor_cmd(as_json):
    """Report core, optional, skill, and project capabilities."""
    import expcon
    root = find_workspace_root()
    skill = _skill_root()
    checks: dict[str, Any] = {
        "core": {"expcon": expcon.__version__, "python": sys.version.split()[0]},
        "tools": {name: bool(shutil.which(name)) for name in ("git", "uv", "tmux", "kaggle", "tinker")},
        "skill": {**_skill_health(skill), "path": str(skill.joinpath("SKILL.md"))},
        "project": {"pyproject_toml": (root / "pyproject.toml").exists(), "expcon": (root / ".expcon").exists()},
    }
    checks["status"] = "READY" if checks["skill"]["compatible"] else "NOT_READY"
    _output(checks, as_json)


@click.group(name="colab")
def colab_cmd():
    """Inspect the official Google Colab Runtime API (allowlist required)."""


@colab_cmd.command(name="doctor")
@click.option("--json", "as_json", is_flag=True)
def colab_doctor_cmd(as_json):
    client = ColabApiClient()
    result: dict[str, Any] = {"api": "v1beta", "configured": client.configured, "allowlist": "required"}
    if client.configured:
        try:
            result["runtime_specs"] = len(client.runtime_specs())
            result["status"] = "READY"
        except ColabClientError as exc:
            result["status"] = "UNAVAILABLE"
            result["error"] = str(exc)
    else:
        result.update({"status": "NOT_CONFIGURED", "remediation": "Set EXPCON_COLAB_ACCESS_TOKEN with the Colaboratory OAuth scope."})
    _output(result, as_json)


@colab_cmd.command(name="specs")
@click.option("--json", "as_json", is_flag=True)
def colab_specs_cmd(as_json):
    specs = ColabApiClient().runtime_specs()
    _output({"runtime_specs": specs, "count": len(specs)}, as_json)


@colab_cmd.command(name="runtimes")
@click.option("--json", "as_json", is_flag=True)
def colab_runtimes_cmd(as_json):
    runtimes = ColabApiClient().runtimes()
    _output({"runtimes": runtimes, "count": len(runtimes)}, as_json)


@colab_cmd.command(name="inspect")
@click.argument("runtime")
@click.option("--json", "as_json", is_flag=True)
def colab_inspect_cmd(runtime, as_json):
    _output(ColabApiClient().runtime(runtime), as_json)


@click.group(name="kaggle")
def kaggle_cmd():
    """Operator tools for the hybrid Kaggle Public API and CLI adapter."""


@kaggle_cmd.command(name="doctor")
@click.option("--json", "as_json", is_flag=True)
def kaggle_doctor_cmd(as_json):
    api, cli = KaggleApiTransport(), KaggleCliTransport()
    api_caps, cli_caps = api.capabilities(), cli.capabilities()
    result: dict[str, Any] = {"cli": cli_caps, "public_api": api_caps,
                              "capabilities": {"kernel.inspect": "api", "kernel.push": "cli",
                                               "kernel.status": "api (cli fallback)", "output.fetch": "cli latest-only (not version-safe)",
                                               "dataset.inspect": "api", "competition.inspect": "api"}}
    if api.available:
        try:
            api.authenticate()
            result["public_api"]["authentication"] = "PASS"
        except KaggleTransportError as exc:
            result["public_api"]["authentication"] = str(exc)
    result["status"] = "READY" if cli_caps["installed"] and api.available else "PARTIAL"
    _output(result, as_json)


@kaggle_cmd.command(name="inspect")
@click.argument("kernel")
@click.option("--json", "as_json", is_flag=True)
def kaggle_inspect_cmd(kernel, as_json):
    if not _valid_kaggle_ref(kernel):
        raise click.ClickException("Invalid kernel ref; expected owner/slug")
    _output(KaggleApiTransport().inspect_kernel(kernel), as_json)


@kaggle_cmd.command(name="status")
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True)
def kaggle_status_cmd(run_id, as_json):
    root = find_workspace_root()
    run = ExperimentLifecycle(root).load_run(run_id)
    if run.backend != "kaggle":
        raise click.ClickException(f"Run {run_id} does not use the Kaggle backend")
    status = KaggleBackend(root).status(run_id)
    _output({"run_id": run_id, "remote_status": status.state, "details": status.details}, as_json)


@kaggle_cmd.group(name="dataset")
def kaggle_dataset_cmd():
    """Inspect datasets through the official Public API."""


@kaggle_dataset_cmd.command(name="inspect")
@click.argument("dataset")
@click.option("--json", "as_json", is_flag=True)
def kaggle_dataset_inspect_cmd(dataset, as_json):
    if not _valid_kaggle_ref(dataset):
        raise click.ClickException("Invalid dataset ref; expected owner/slug")
    _output(KaggleApiTransport().inspect_dataset(dataset), as_json)


@kaggle_cmd.group(name="competition")
def kaggle_competition_cmd():
    """Inspect competition metadata through the official Public API."""


@kaggle_competition_cmd.command(name="inspect")
@click.argument("competition")
@click.option("--json", "as_json", is_flag=True)
def kaggle_competition_inspect_cmd(competition, as_json):
    if not competition.replace("-", "").replace("_", "").isalnum():
        raise click.ClickException("Invalid competition ref")
    _output(KaggleApiTransport().competition_info(competition), as_json)


@click.group(name="tinker")
def tinker_cmd():
    """Operator tools for the optional managed Tinker LLM training backend."""


def _tinker_backend() -> TinkerBackend:
    return TinkerBackend(find_workspace_root())


@tinker_cmd.command(name="doctor")
@click.option("--json", "as_json", is_flag=True)
def tinker_doctor_cmd(as_json):
    """Report public SDK/CLI availability without exposing credentials."""
    sdk, cli = TinkerSdkTransport(), TinkerCliTransport()
    sdk_result = sdk.diagnostics()
    result = {"sdk": sdk_result, "cli": cli.capabilities(),
              "capabilities": _tinker_backend().capabilities(),
              "status": "READY" if sdk_result["authenticated"] else "NOT_READY"}
    _output(result, as_json)


@tinker_cmd.command(name="runs")
@click.option("--json", "as_json", is_flag=True)
def tinker_runs_cmd(as_json):
    _output({"training_runs": TinkerSdkTransport().list_training_runs()}, as_json)


@tinker_cmd.group(name="run")
def tinker_run_cmd():
    """Inspect Tinker training resources through RestClient."""


@tinker_run_cmd.command(name="inspect")
@click.argument("training_run")
@click.option("--json", "as_json", is_flag=True)
def tinker_run_inspect_cmd(training_run, as_json):
    _output(TinkerSdkTransport().get_training_run(training_run), as_json)


@tinker_cmd.command(name="sessions")
@click.option("--json", "as_json", is_flag=True)
def tinker_sessions_cmd(as_json):
    _output({"sessions": TinkerSdkTransport().list_sessions()}, as_json)


@tinker_cmd.group(name="session")
def tinker_session_cmd():
    """Inspect Tinker sessions through RestClient."""


@tinker_session_cmd.command(name="inspect")
@click.argument("session")
@click.option("--json", "as_json", is_flag=True)
def tinker_session_inspect_cmd(session, as_json):
    _output(TinkerSdkTransport().get_session(session), as_json)


@tinker_cmd.command(name="checkpoints")
@click.argument("training_run", required=False)
@click.option("--json", "as_json", is_flag=True)
def tinker_checkpoints_cmd(training_run, as_json):
    _output({"checkpoints": TinkerSdkTransport().list_checkpoints(training_run)}, as_json)


@tinker_cmd.group(name="checkpoint")
def tinker_checkpoint_cmd():
    """Inspect or safely download Tinker checkpoints; never publish/delete."""


@tinker_checkpoint_cmd.command(name="inspect")
@click.argument("tinker_path")
@click.option("--json", "as_json", is_flag=True)
def tinker_checkpoint_inspect_cmd(tinker_path, as_json):
    _output(TinkerSdkTransport().checkpoint_info(tinker_path), as_json)


@tinker_checkpoint_cmd.command(name="fetch")
@click.argument("tinker_path")
@click.option("--output-dir", type=click.Path(path_type=Path), required=True)
@click.option("--json", "as_json", is_flag=True)
def tinker_checkpoint_fetch_cmd(tinker_path, output_dir, as_json):
    _output(_tinker_backend().fetch_checkpoint(tinker_path, output_dir), as_json)


@tinker_cmd.command(name="trace")
@click.argument("session")
@click.option("--json", "as_json", is_flag=True)
def tinker_trace_cmd(session, as_json):
    _output(TinkerSdkTransport().export_session_trace(session), as_json)


@click.group(name="skill")
def skill_cmd():
    """Locate or install the bundled Experiment Contract skill."""


@skill_cmd.command(name="path")
def skill_path_cmd():
    """Print the canonical installed skill path."""
    click.echo(str(_skill_root().joinpath("SKILL.md")))


@skill_cmd.command(name="status")
@click.option("--target", type=click.Path(path_type=Path), default=None,
              help="Existing agent skills directory to inspect.")
@click.option("--json", "as_json", is_flag=True)
def skill_status_cmd(target, as_json):
    """Report bundled skill availability and a detected Codex installation."""
    source = _skill_root()
    if target is None and os.environ.get("CODEX_HOME"):
        target = Path(os.environ["CODEX_HOME"]) / "skills"
    installed_root = target / "experiment-contract" if target else None
    installed = _skill_health(installed_root) if installed_root and installed_root.exists() else None
    _output({"canonical_path": str(source.joinpath("SKILL.md")), "bundled": _skill_health(source),
             "installed": installed, "installed_path": str(installed_root) if installed_root else None}, as_json)


@skill_cmd.command(name="install")
@click.option("--target", type=click.Path(path_type=Path), default=None,
              help="Existing agent skills directory; defaults to $CODEX_HOME/skills when set.")
@click.option("--json", "as_json", is_flag=True)
def skill_install_cmd(target, as_json):
    """Install the skill only into a detected or explicitly selected target."""
    if target is None:
        codex_home = os.environ.get("CODEX_HOME")
        if not codex_home:
            raise click.ClickException("No agent skills directory detected; use expcon skill install --target <skills-dir>")
        target = Path(codex_home) / "skills"
    if not target.exists() or not target.is_dir():
        raise click.ClickException(f"Skill target must be an existing directory: {target}")
    destination = target / "experiment-contract"
    destination.mkdir(exist_ok=True)
    source = _skill_root()
    (destination / "SKILL.md").write_text(source.joinpath("SKILL.md").read_text(), encoding="utf-8")
    refs = destination / "references"
    refs.mkdir(exist_ok=True)
    for name in SKILL_REFERENCE_NAMES:
        refs.joinpath(name).write_text(source.joinpath("references", name).read_text(), encoding="utf-8")
    health = _skill_health(destination)
    _output({"status": "INSTALLED" if health["compatible"] else "INCOMPLETE", "path": str(destination / "SKILL.md"),
             "references": list(SKILL_REFERENCE_NAMES), "compatibility": health}, as_json)


# ─── inspect ─────────────────────────────────────────────────────────────────

@click.command(name="inspect")
@click.argument("experiment")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def inspect_cmd(experiment, as_json):
    """Inspect an experiment contract."""
    exp_path = _resolve_experiment(experiment)
    contract = load_contract(exp_path / "EXPERIMENT.yaml")

    # Get lifecycle state
    workspace_root = find_workspace_root(exp_path.parent)
    lifecycle = ExperimentLifecycle(workspace_root)
    state = lifecycle.get_experiment_state(exp_path)

    identity = contract_identity(contract.data)

    # Check if frozen
    lock_path = exp_path / "contract.lock.json"
    frozen = lock_path.exists()
    lock_info = {}
    if frozen:
        lock_info = json.loads(lock_path.read_text(encoding="utf-8"))

    result = {
        "experiment_id": contract.experiment_id,
        "version": contract.version,
        "title": contract.title,
        "state": state.value,
        "frozen": frozen,
        "contract_hash": identity["contract_hash"],
        "scientific_hash": identity["scientific_hash"],
        "execution_hash": identity["execution_hash"],
        "scientific_identity_algorithm": identity["scientific_identity_algorithm"],
        "scientific_design_hash": identity["scientific_design_hash"],
        "execution_identity_algorithm": identity["execution_identity_algorithm"],
        "hypothesis": contract.hypothesis,
        "stages": contract.get("execution", "stages", default=[]),
        "required_outputs": contract.get("outputs", "required", default=[]),
        "reproducibility_level": contract.get("reproducibility", "level", default="unknown"),
        "seed": contract.get("scientific_parameters", "seed", default=None),
        "primary_metric": contract.get("evaluation", "primary_metric", default=None),
        "allowed_backends": contract.get("execution", "allowed_backends", default=[]),
        "accelerator": contract.get("execution", "accelerator", "type", default="none"),
    }
    if lock_info:
        result["bundle_id"] = lock_info.get("identity", {}).get("bundle_id")
        result["frozen_at"] = lock_info.get("frozen_at")

    _output(result, as_json)


# ─── validate ────────────────────────────────────────────────────────────────

@click.command(name="validate")
@click.argument("experiment")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def validate_cmd(experiment, as_json):
    """Validate an experiment contract."""
    exp_path = _resolve_experiment(experiment)
    try:
        result = validate_experiment(exp_path)
        _output(result, as_json)
    except Exception as exc:
        _output({"status": "INVALID", "error": str(exc)}, as_json)
        sys.exit(1)


# ─── freeze ──────────────────────────────────────────────────────────────────

@click.command()
@click.argument("experiment")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def freeze_cmd(experiment, as_json):
    """Freeze an experiment: validate, resolve, compute identities, write lock."""
    exp_path = _resolve_experiment(experiment)
    workspace_root = find_workspace_root(exp_path.parent)
    try:
        result = freeze_experiment(exp_path, workspace_root)
        _output(result, as_json)
    except Exception as exc:
        _output({"status": "ERROR", "error": str(exc)}, as_json)
        sys.exit(1)


# ─── diff ────────────────────────────────────────────────────────────────────

@click.command()
@click.argument("experiment")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def diff_cmd(experiment, as_json):
    """Detect scientifically meaningful divergence in a frozen experiment."""
    exp_path = _resolve_experiment(experiment)
    result = diff_experiment(exp_path)

    if result["divergence_detected"]:
        if not as_json:
            click.secho("CONTRACT DIVERGENCE DETECTED", fg="red", bold=True)
            for d in result["divergences"]:
                click.secho(f"\n{d['field']}", fg="yellow")
                click.secho(f"  {d['message']}")
                if "frozen_value" in d:
                    click.secho(f"  frozen:  {d['frozen_value']}")
                if "current_value" in d:
                    click.secho(f"  current: {d['current_value']}")
            click.secho("\nScientific identity changed.", fg="red")
            click.secho("Do not execute as the current experiment version.", fg="yellow")
            click.secho("Create a successor experiment version.", fg="yellow")
        else:
            _output(result, as_json)
        sys.exit(1)
    else:
        if not as_json:
            click.secho("No scientific divergence detected.", fg="green")
        _output(result, as_json)


# ─── bundle ──────────────────────────────────────────────────────────────────

@click.command()
@click.argument("experiment")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def bundle_cmd(experiment, as_json):
    """Create a content-addressed bundle for an experiment."""
    exp_path = _resolve_experiment(experiment)
    divergence = diff_experiment(exp_path)
    if divergence.get("divergence_detected"):
        _output({"status": "ERROR", "error": "Frozen experiment diverged; create a successor version", "diff": divergence}, as_json)
        sys.exit(1)
    builder = BundleBuilder(exp_path)
    try:
        bundle_path, bundle_id = builder.build()
        result = {
            "status": "BUNDLED",
            "bundle_path": str(bundle_path),
            "bundle_id": bundle_id,
            "experiment_id": load_contract(exp_path / "EXPERIMENT.yaml").experiment_id,
        }
        _output(result, as_json)
    except Exception as exc:
        _output({"status": "ERROR", "error": str(exc)}, as_json)
        sys.exit(1)


@click.command(name="preflight")
@click.argument("experiment")
@click.option("--input", "input_bindings", multiple=True, metavar="NAME=PATH", help="Named candidate input binding")
@click.option("--env", "environment_bindings", multiple=True, metavar="NAME=VALUE", help="Named candidate environment binding")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def preflight_cmd(experiment, input_bindings, environment_bindings, as_json):
    """Build and verify an ephemeral candidate bundle without execution."""
    exp_path = _resolve_experiment(experiment)
    try:
        validate_experiment(exp_path)
        result = BundleBuilder(exp_path).preflight(
            input_bindings=_parse_named_bindings(input_bindings, "input"),
            environment_bindings=_parse_named_bindings(environment_bindings, "environment"),
        )
        _output(result, as_json)
        if result["status"] != "PASS":
            sys.exit(1)
    except Exception as exc:
        _output({"status": "ERROR", "error": str(exc)}, as_json)
        sys.exit(1)


# ─── verify-bundle ───────────────────────────────────────────────────────────

@click.command(name="verify-bundle")
@click.argument("bundle")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def verify_bundle_cmd(bundle, as_json):
    """Verify a bundle's integrity."""
    bundle_path = Path(bundle).resolve()
    if not bundle_path.exists():
        bundle_path = _resolve_experiment(bundle) / "bundle"

    verifier = BundleVerifier(bundle_path)
    result = verifier.verify()
    _output(result, as_json)
    if result["status"] != "PASS":
        sys.exit(1)


# ─── run ─────────────────────────────────────────────────────────────────────

@click.command()
@click.argument("experiment")
@click.option("--backend", default="local", help="Execution backend")
@click.option("--kernel", default=None, help="Kaggle kernel name")
@click.option("--accelerator", default="none", help="Accelerator type")
@click.option("--input", "input_bindings", multiple=True, metavar="NAME=PATH", help="Named runtime input binding")
@click.option("--env", "environment_bindings", multiple=True, metavar="NAME=VALUE", help="Named runtime environment binding")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def run_cmd(experiment, backend, kernel, accelerator, input_bindings, environment_bindings, as_json):
    """Run an experiment on a specified backend."""
    exp_path = _resolve_experiment(experiment)
    workspace_root = find_workspace_root(exp_path.parent)
    lifecycle = ExperimentLifecycle(workspace_root)

    # Check if frozen
    lock_path = exp_path / "contract.lock.json"
    if not lock_path.exists():
        _output({"status": "ERROR", "error": "Experiment must be frozen before running"}, as_json)
        sys.exit(1)

    lock = json.loads(lock_path.read_text(encoding="utf-8"))

    try:
        validate_experiment(exp_path)
        divergence = diff_experiment(exp_path)
        if divergence.get("divergence_detected"):
            raise RuntimeError("Frozen experiment diverged; execution is refused")
    except Exception as exc:
        _output({"status": "ERROR", "error": str(exc)}, as_json)
        sys.exit(1)

    # Verify allowed backend
    contract = load_contract(exp_path / "EXPERIMENT.yaml")
    allowed_backends = contract.get("execution", "allowed_backends", default=[])
    if backend not in allowed_backends:
        _output({"status": "ERROR", "error": f"Backend '{backend}' not allowed. Allowed: {allowed_backends}"}, as_json)
        sys.exit(1)

    # Create run record
    bundle_dir = exp_path / "bundle"
    if not bundle_dir.exists():
        _output({"status": "ERROR", "error": "Bundle not found. Run 'expcon bundle' first."}, as_json)
        sys.exit(1)
    bundle_check = BundleVerifier(bundle_dir, expected_bundle_id=lock["identity"]["bundle_id"]).verify()
    if bundle_check["status"] != "PASS":
        _output({"status": "ERROR", "error": "Bundle verification failed", "details": bundle_check["errors"]}, as_json)
        sys.exit(1)
    bundle_compatibility = verify_frozen_bundle_compatibility(exp_path, contract, lock)
    if bundle_compatibility["status"] != "PASS":
        _output({"status": "ERROR", "error": "Frozen bundle compatibility verification failed", "details": bundle_compatibility}, as_json)
        sys.exit(1)
    materialized_bundle_id = bundle_check["bundle_id"]
    if materialized_bundle_id != bundle_compatibility["materialized_bundle_id"]:
        _output({
            "status": "ERROR",
            "error": "Materialized bundle does not match the verified canonical bundle content identity",
            "details": bundle_compatibility,
        }, as_json)
        sys.exit(1)

    environment_attestation = {}
    interpreter = None
    if backend == "local":
        try:
            environment_attestation = preflight_local_environment(bundle_dir, workspace_root)
            interpreter = environment_attestation["python_executable"]
        except EnvironmentError as exc:
            _output({"status": "ERROR", "error": f"Local environment preflight failed: {exc}"}, as_json)
            sys.exit(1)

    # A provenance-incomplete Kaggle transport must never create a partial
    # experiment run.  This check is intentionally before lifecycle.create_run.
    if backend == "kaggle":
        try:
            KaggleBackend(workspace_root).preflight(bundle_dir)
        except Exception as exc:
            _output({"status": "BLOCKED", "reason": "BACKEND_CAPABILITY_MISMATCH", "error": str(exc)}, as_json)
            sys.exit(1)

    if backend == "colab":
        _output({"status": "BLOCKED", "reason": "PROVISIONING_ONLY",
                 "error": "Colab has no approved workload channel; no runtime allocated"}, as_json)
        sys.exit(1)

    named_inputs = _parse_named_bindings(input_bindings, "input")
    named_environment = _parse_named_bindings(environment_bindings, "environment")
    input_admission = []
    for stage in contract.get("execution", "stages", default=[]):
        resolved = resolve_invocation(
            stage.get("invocation", contract.get("execution", "invocation", default=None)),
            bundle_root=bundle_dir, output_root=bundle_dir / "candidate-output" / stage["id"],
            input_bindings=named_inputs, environment_bindings=named_environment,
        )
        input_admission.append(resolved.attestation)

    run = lifecycle.create_run(
        experiment_id=contract.experiment_id,
        version=contract.version,
        backend=backend,
        contract_hash=lock["contract_hash"],
        bundle_id=materialized_bundle_id,
        kernel=kernel,
        accelerator=accelerator,
        metadata={"bundle_compatibility": bundle_compatibility, "environment": environment_attestation,
                  "frozen_contract": contract.data, "frozen_lock": lock,
                  "input_admission": input_admission},
    )

    # Each new run retains its own verified snapshot. Existing history is untouched.
    snapshot = lifecycle.run_dir(run.run_id) / "bundle"
    shutil.copytree(bundle_dir, snapshot)
    if BundleVerifier(snapshot, expected_bundle_id=materialized_bundle_id).verify()["status"] != "PASS":
        raise click.ClickException("Run snapshot failed verification")
    bundle_dir = snapshot

    # Select backend
    if backend == "local":
        backend_impl: ExecutionBackend = LocalBackend(workspace_root)
    elif backend == "kaggle":
        backend_impl = KaggleBackend(workspace_root)
    elif backend == "colab":
        backend_impl = ColabBackend(workspace_root)
    elif backend == "tinker":
        backend_impl = TinkerBackend(workspace_root)
    else:
        _output({"status": "ERROR", "error": f"Unknown backend: {backend}"}, as_json)
        sys.exit(1)

    runner = StageRunner(backend_impl)

    context = RunContext(
        experiment_id=contract.experiment_id,
        version=contract.version,
        bundle_id=materialized_bundle_id,
        contract_hash=lock["contract_hash"],
        kernel=kernel,
        accelerator=accelerator,
        environment={"requirements": contract.get("execution", "requirements", default={})},
        input_bindings=named_inputs,
        environment_bindings=named_environment,
        interpreter=interpreter,
        environment_attestation=environment_attestation,
    )

    # State transitions are checked, never swallowed.
    for name in ("CONTRACT_VERIFIED", "BACKEND_SELECTED", "DATA_VERIFIED", "STAGE_STARTED"):
        lifecycle.update_run_state(run.run_id, lifecycle_run_state_from_run(run.run_id, name), name)

    # Set run_id in context so backend uses the same ID
    context.run_id = run.run_id

    # Submit
    try:
        runner.run(bundle_dir, context)
        backend_status = backend_impl.status(run.run_id)
        observed = observe(lifecycle, run.run_id, backend_status.state)
        if observed == "failed":
            _output({"status": "ERROR", "error": backend_status.message,
                     "run_id": run.run_id, "backend_status": backend_status.details}, as_json)
            sys.exit(1)
        result = {
            "status": "COMPLETED" if observed == "completed" else "SUBMITTED",
            "run_id": run.run_id,
            "experiment_id": contract.experiment_id,
            "version": contract.version,
            "backend": backend,
            "bundle_id": materialized_bundle_id,
            "frozen_bundle_id": lock["identity"]["bundle_id"],
            "kernel": kernel,
            "accelerator": accelerator,
        }
        _output(result, as_json)
    except Exception as exc:
        failure_state = "BLOCKED" if str(exc).startswith("BLOCKED:") else "FAILED_EXECUTION"
        if failure_state == "FAILED_EXECUTION":
            current = lifecycle.load_run(run.run_id).state
            if current.value == "STAGE_STARTED":
                lifecycle.update_run_state(run.run_id, lifecycle_run_state_from_run(run.run_id, "STAGE_FAILED"), str(exc))
        if failure_state == "BLOCKED" and lifecycle.load_run(run.run_id).state.value == "STAGE_STARTED":
            lifecycle.update_run_state(run.run_id, lifecycle_run_state_from_run(run.run_id, "STAGE_CANCELLED"), str(exc))
        lifecycle.update_run_state(run.run_id, lifecycle_run_state_from_run(run.run_id, failure_state), str(exc))
        _output({"status": "ERROR", "error": str(exc), "run_id": run.run_id}, as_json)
        sys.exit(1)


def lifecycle_run_state_from_run(run_id: str, state_name: str):
    from expcon.lifecycle.state import RunState

    return RunState(state_name)


def _parse_named_bindings(values, label: str) -> dict[str, str]:
    """Parse deterministic NAME=VALUE runtime bindings without shell expansion."""
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise click.BadParameter(f"{label} binding must use NAME=VALUE")
        name, value = item.split("=", 1)
        if not name or not value or name in result:
            raise click.BadParameter(f"invalid or duplicate {label} binding name")
        result[name] = value
    return result


# ─── ps ──────────────────────────────────────────────────────────────────────

@click.command(name="ps")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def ps_cmd(as_json):
    """List all runs."""
    workspace_root = find_workspace_root()
    lifecycle = ExperimentLifecycle(workspace_root)
    runs = lifecycle.list_runs()

    result = {
        "runs": [
            {
                "run_id": r.run_id,
                "experiment_id": r.experiment_id,
                "version": r.version,
                "state": r.state.value,
                "backend": r.backend,
                "created_at": r.created_at,
                "kernel": r.kernel,
            }
            for r in runs
        ],
        "count": len(runs),
    }
    _output(result, as_json)


# ─── status ──────────────────────────────────────────────────────────────────

@click.command()
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status_cmd(run_id, as_json):
    """Get status of a run."""
    workspace_root = find_workspace_root()
    lifecycle = ExperimentLifecycle(workspace_root)

    try:
        run = lifecycle.load_run(run_id)
    except KeyError:
        _output({"status": "ERROR", "error": f"Run not found: {run_id}"}, as_json)
        sys.exit(1)

    # Get backend status
    if run.backend == "local":
        backend: ExecutionBackend | None = LocalBackend(workspace_root)
    elif run.backend == "kaggle":
        backend = KaggleBackend(workspace_root)
    elif run.backend == "tinker":
        backend = TinkerBackend(workspace_root)
    else:
        backend = None

    backend_status = backend.status(run_id) if backend else None
    if backend_status:
        observe(lifecycle, run_id, backend_status.state)
        run = lifecycle.load_run(run_id)

    result = {
        "run_id": run.run_id,
        "experiment_id": run.experiment_id,
        "version": run.version,
        "state": run.state.value,
        "backend": run.backend,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "contract_hash": run.contract_hash,
        "bundle_id": run.bundle_id,
        "kernel": run.kernel,
        "accelerator": run.accelerator,
        "backend_status": backend_status.details if backend_status else None,
    }
    _output(result, as_json)


# ─── events ──────────────────────────────────────────────────────────────────

@click.command(name="events")
@click.argument("run_id")
@click.option("--follow", "-f", is_flag=True, help="Follow events in real-time")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def events_cmd(run_id, follow, as_json):
    """Show events for a run."""
    workspace_root = find_workspace_root()
    lifecycle = ExperimentLifecycle(workspace_root)

    if follow:
        from expcon.lifecycle.experiment_state import EventLedger

        run_dir = lifecycle.run_dir(run_id)
        ledger = EventLedger(run_dir)
        try:
            for line in lifecycle._follow_file(ledger.events_file, 0):
                event = json.loads(line)
                if as_json:
                    click.echo(json.dumps(event, sort_keys=True))
                else:
                    click.echo(f"[{event.get('timestamp', '?')}] {event.get('event', '?')}")
        except KeyboardInterrupt:
            pass
    else:
        events = lifecycle.get_run_events(run_id)
        result = {"run_id": run_id, "events": events, "count": len(events)}
        _output(result, as_json)


# ─── fetch ───────────────────────────────────────────────────────────────────

@click.command()
@click.argument("run_id")
@click.option("--output-dir", default=None, help="Output directory for evidence")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def fetch_cmd(run_id, output_dir, as_json):
    """Fetch evidence from a completed run."""
    workspace_root = find_workspace_root()
    lifecycle = ExperimentLifecycle(workspace_root)

    try:
        run = lifecycle.load_run(run_id)
    except KeyError:
        _output({"status": "ERROR", "error": f"Run not found: {run_id}"}, as_json)
        sys.exit(1)

    if output_dir is None:
        output_dir = workspace_root / ".expcon" / "fetched" / run_id

    if run.backend == "local":
        backend: ExecutionBackend = LocalBackend(workspace_root)
    elif run.backend == "kaggle":
        backend = KaggleBackend(workspace_root)
    elif run.backend == "tinker":
        backend = TinkerBackend(workspace_root)
    else:
        _output({"status": "ERROR", "error": f"Unknown backend: {run.backend}"}, as_json)
        sys.exit(1)

    import uuid
    from expcon.artifacts.artifact import ArtifactRegistry
    if run.state.value not in {"RESULTS_AVAILABLE", "EVIDENCE_FETCHED", "EVIDENCE_VERIFIED", "ADJUDICATED"}:
        raise click.ClickException("Fetch requires observed successful execution completion")
    attempt = uuid.uuid4().hex
    run_dir = lifecycle.run_dir(run_id)
    raw = run_dir / "fetches" / attempt
    report = {"attempt": attempt, "run_id": run_id, "status": "STARTED"}
    report_path = run_dir / "fetch_reports" / f"{attempt}.json"
    atomic_json(report_path, report)
    try:
        raw_path = backend.fetch(run_id, raw)
        bundle_dir = run_dir / "bundle"
        if not bundle_dir.is_dir():
            exp_dir = _find_experiment_dir(workspace_root, run.experiment_id, run.version)
            if exp_dir is None:
                raise RuntimeError("Frozen bundle unavailable")
            bundle_dir = exp_dir / "bundle"
        if BundleVerifier(bundle_dir, expected_bundle_id=run.bundle_id).verify()["status"] != "PASS":
            raise RuntimeError("Frozen bundle verification failed before collection")
        source = collect_outputs(lifecycle, run, bundle_dir, raw_path)
        evidence_path = run_dir / "evidence_versions" / attempt
        contract = json.loads((bundle_dir / "resolved_contract.json").read_text())
        EvidenceVerifier(evidence_path).package_evidence(
            run_id, run.experiment_id, run.contract_hash, run.bundle_id,
            source, contract["outputs"]["required"],
        )
        bind_evidence(lifecycle, run_id, evidence_path)
        registry = ArtifactRegistry(run_dir)
        for path in sorted((evidence_path / "outputs").rglob("*")):
            if path.is_file():
                relative = path.relative_to(evidence_path / "outputs").as_posix()
                registry.register(path, "output", run.experiment_id, run_id,
                    producer_stage=relative.split("/")[1] if relative.startswith("stages/") else "declared_output",
                    metadata={"bundle_id": run.bundle_id, "contract_hash": run.contract_hash,
                              "evidence_path": relative})
        run = lifecycle.load_run(run_id)
        run.metadata["evidence_path"] = str(evidence_path)
        lifecycle._save_run(run)
        if run.state.value == "RESULTS_AVAILABLE":
            lifecycle.update_run_state(run_id, lifecycle_run_state_from_run(run_id, "EVIDENCE_FETCHED"), "Evidence packaged and sealed")
        report.update(status="COMPLETED", evidence_path=str(evidence_path))
        atomic_json(report_path, report)
    except Exception as exc:
        report.update(status="FAILED", error=str(exc))
        atomic_json(report_path, report)
        raise click.ClickException(f"Evidence fetch/collection failed; partial bytes preserved: {exc}") from exc
    _output({"status": "FETCHED", "run_id": run_id, "evidence_path": str(evidence_path)}, as_json)


# ─── verify ──────────────────────────────────────────────────────────────────

@click.command()
@click.argument("run_id")
@click.option("--bundle", default=None, help="Bundle path for cross-verification")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def verify_cmd(run_id, bundle, as_json):
    """Verify evidence for a run."""
    workspace_root = find_workspace_root()
    lifecycle = ExperimentLifecycle(workspace_root)

    try:
        lifecycle.load_run(run_id)
    except KeyError:
        _output({"status": "ERROR", "error": f"Run not found: {run_id}"}, as_json)
        sys.exit(1)

    run_record = lifecycle.load_run(run_id)
    evidence_dir = locate_evidence(workspace_root, run_record)

    bundle_path = Path(bundle) if bundle else None

    # Auto-find bundle if not explicitly provided
    if bundle_path is None and (lifecycle.run_dir(run_id) / "bundle").is_dir():
        bundle_path = lifecycle.run_dir(run_id) / "bundle"
    if bundle_path is None:
        try:
            run_record = lifecycle.load_run(run_id)
            exp_dir = _find_experiment_dir(workspace_root, run_record.experiment_id, run_record.version)
            if exp_dir and (exp_dir / "bundle").exists():
                bundle_path = exp_dir / "bundle"
        except Exception:
            pass

    verifier = EvidenceVerifier(evidence_dir, bundle_path, expected_run=run_record)
    result = verifier.verify()
    import uuid
    atomic_json(lifecycle.run_dir(run_id) / "verification_reports" / f"{uuid.uuid4().hex}.json", result)

    # Update run state
    current = lifecycle.load_run(run_id).state.value
    if result["verified"] and current == "EVIDENCE_FETCHED":
        lifecycle.update_run_state(run_id, lifecycle_run_state_from_run(run_id, "EVIDENCE_VERIFIED"), "Evidence verified")
    elif not result["verified"] and current in {"EVIDENCE_FETCHED", "EVIDENCE_VERIFIED", "ADJUDICATED"}:
        lifecycle.update_run_state(run_id, lifecycle_run_state_from_run(run_id, "EVIDENCE_INVALID"), "; ".join(result["errors"]))

    _output(result, as_json)
    if not result["verified"]:
        sys.exit(1)


# ─── adjudicate ──────────────────────────────────────────────────────────────

@click.command()
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def adjudicate_cmd(run_id, as_json):
    """Adjudicate a run: determine execution, contract, and scientific status."""
    workspace_root = find_workspace_root()
    adjudicator = Adjudicator(workspace_root)
    result = adjudicator.adjudicate(run_id)

    if not as_json:
        click.secho("=" * 60, fg="cyan")
        click.secho("ADJUDICATION REPORT", fg="cyan", bold=True)
        click.secho("=" * 60, fg="cyan")
        click.echo(f"  Experiment: {result.experiment_id}/{result.version}")
        click.echo(f"  Run ID:     {result.run_id}")
        click.secho("-" * 60, fg="cyan")
        click.echo(f"  Execution:   {result.execution_status}")
        click.echo(f"  Contract:    {result.contract_status}")
        click.echo(f"  Evidence:    {result.evidence_status}")
        verdict_color = "green" if result.scientific_verdict == "SUPPORTED" else "yellow" if result.scientific_verdict == "NOT_SUPPORTED" else "red"
        click.secho(f"  Scientific:  {result.scientific_verdict}", fg=verdict_color, bold=True)
        click.secho("=" * 60, fg="cyan")
    else:
        _output(result.to_dict(), as_json)


# ─── artifacts ───────────────────────────────────────────────────────────────

@click.command(name="artifacts")
@click.argument("target")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def artifacts_cmd(target, as_json):
    """List artifacts for an experiment or run."""
    workspace_root = find_workspace_root()
    lifecycle = ExperimentLifecycle(workspace_root)

    # Check if target is a run ID
    try:
        run = lifecycle.load_run(target)
        registry = ArtifactRegistry(lifecycle.run_dir(run.run_id))
        artifacts = registry.list()
        result = {
            "run_id": run.run_id,
            "experiment_id": run.experiment_id,
            "artifacts": [a.to_dict() for a in artifacts],
            "count": len(artifacts),
        }
        _output(result, as_json)
    except KeyError:
        # Try as experiment path
        exp_path = _resolve_experiment(target)
        all_runs = lifecycle.list_runs()
        exp_runs = [r for r in all_runs if r.experiment_id == load_contract(exp_path / "EXPERIMENT.yaml").experiment_id]

        all_artifacts = []
        for r in exp_runs:
            registry = ArtifactRegistry(lifecycle.run_dir(r.run_id))
            all_artifacts.extend(registry.list())

        result = {
            "experiment_id": load_contract(exp_path / "EXPERIMENT.yaml").experiment_id,
            "artifacts": [a.to_dict() for a in all_artifacts],
            "count": len(all_artifacts),
        }
        _output(result, as_json)


# ─── workspace ───────────────────────────────────────────────────────────────

@click.command(name="workspace")
@click.argument("experiment")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def workspace_cmd(experiment, as_json):
    """Create a tmux workspace for an experiment."""
    workspace_root = find_workspace_root()
    manager = WorkspaceManager(workspace_root)
    try:
        result = manager.create_workspace(experiment)
        _output(result, as_json)
        if not as_json:
            click.secho(f"\nTo attach: tmux attach -t {result['session']}", fg="cyan")
    except WorkspaceError as exc:
        _output({"status": "ERROR", "error": str(exc)}, as_json)
        sys.exit(1)


# ─── attach ──────────────────────────────────────────────────────────────────

@click.command(name="attach")
@click.argument("experiment")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def attach_cmd(experiment, as_json):
    """Attach to an existing tmux workspace."""
    workspace_root = find_workspace_root()
    manager = WorkspaceManager(workspace_root)
    try:
        result = manager.attach_workspace(experiment)
        _output(result, as_json)
        if not as_json:
            click.secho(f"\nTo attach: tmux attach -t {result['session']}", fg="cyan")
    except WorkspaceError as exc:
        _output({"status": "ERROR", "error": str(exc)}, as_json)
        sys.exit(1)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _find_experiment_dir(workspace_root: Path, experiment_id: str, version: str) -> Path | None:
    """Find the experiment directory by searching for matching EXPERIMENT.yaml."""
    search_dirs = [
        workspace_root / "experiments",
        workspace_root / "examples",
    ]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for exp_dir in search_dir.iterdir():
            if exp_dir.is_dir() and (exp_dir / "EXPERIMENT.yaml").exists():
                try:
                    contract = load_contract(exp_dir / "EXPERIMENT.yaml")
                    if contract.experiment_id == experiment_id and contract.version == version:
                        return exp_dir
                except Exception:
                    pass
    return None


def _resolve_experiment(experiment: str) -> Path:
    """Resolve an experiment reference to a path."""
    # If it's already a path with EXPERIMENT.yaml
    exp_path = Path(experiment).resolve()
    if (exp_path / "EXPERIMENT.yaml").exists():
        return exp_path
    if exp_path.name == "EXPERIMENT.yaml":
        return exp_path.parent

    # Search in experiments/ directories
    workspace_root = find_workspace_root()
    search_dirs = [workspace_root / "experiments", workspace_root.parent / "experiments"]

    # Try exact match
    for search_dir in search_dirs:
        if search_dir.exists():
            candidate = search_dir / experiment
            if candidate.exists() and (candidate / "EXPERIMENT.yaml").exists():
                return candidate

    # Try fuzzy match (E13 -> e13_...)
    parts = experiment.replace("/", "_").split("_")
    for search_dir in search_dirs:
        if search_dir.exists():
            for exp_dir in search_dir.iterdir():
                if exp_dir.is_dir() and (exp_dir / "EXPERIMENT.yaml").exists():
                    dir_name = exp_dir.name.lower()
                    if experiment.lower() in dir_name or parts[0].lower() in dir_name:
                        return exp_dir

    # Try as a bare path
    if exp_path.exists():
        return exp_path

    raise click.ClickException(f"Experiment not found: {experiment}")
