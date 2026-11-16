"""Transport and application regressions use disposable workspaces only."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from expcon.service.controller import ExperimentService
from expcon_mcp.server import create_server, create_app


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="1"\n')
    (tmp_path / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    (tmp_path / "installed.lock.toml").write_text(
        'version=1\nrequires-python=">=3.10"\n[[package]]\nname="fixture"\nversion="1"\nsource={virtual="."}\ndependencies=[]\n'
    )
    return tmp_path


def draft(root, name="trial"):
    path = root / "experiments" / name
    path.mkdir(parents=True)
    contract = {
        "schema_version": 1,
        "bundle_identity_algorithm": "expcon-bundle-v3",
        "experiment": {"id": name.upper(), "version": "v001", "title": "Disposable"},
        "hypothesis": {"statement": "Accuracy exceeds gate"},
        "source": {"repository": "."},
        "execution": {
            "allowed_backends": ["local"],
            "stages": [{"id": "main", "entrypoint": "run.py"}],
        },
        "environment": {"dependency_lock": "installed.lock.toml"},
        "evaluation": {
            "primary_metric": "accuracy",
            "acceptance": {"metric": "accuracy", "operator": ">=", "threshold": 0.5},
        },
        "outputs": {"required": ["metrics.json"]},
        "reproducibility": {"level": "functional"},
    }
    (path / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
    (path / "run.py").write_text(
        'import sys,json\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index("--output-root")+1]); p.mkdir(exist_ok=True,parents=True); (p/"metrics.json").write_text(json.dumps({"accuracy":.9}))\n'
    )
    return f"experiments/{name}"


async def test_sdk_registry_and_validation(workspace):
    server = create_server(str(workspace))
    names = {tool.name for tool in await server.list_tools()}
    assert {"experiment_run", "experiment_verify", "artifact_read"} <= names
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        await server.call_tool("research_propose", {})


async def test_real_stdio_client(workspace):
    async with stdio_client(
        StdioServerParameters(
            command=sys.executable,
            args=["-m", "expcon_mcp.server", "--stdio", "--workspace", str(workspace)],
        )
    ) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert any(t.name == "experiment_freeze" for t in tools.tools)
            result = await session.call_tool("research_propose", {"hypothesis": "Test"})
            assert not result.isError


def test_http_initialize_and_origin(workspace):
    with TestClient(create_app(str(workspace))) as client:
        headers = {"Accept": "application/json, text/event-stream"}
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        response = client.post("/mcp", json=request, headers=headers)
        assert response.status_code == 200, response.text
        assert "result" in response.json()
        response = client.post(
            "/mcp", json=request, headers={**headers, "Origin": "https://evil.example"}
        )
        assert response.status_code == 403


def test_freeze_rejects_edits_and_escape(workspace):
    service = ExperimentService(workspace)
    reference = draft(workspace)
    candidate = service.preflight(reference)["candidate_id"]
    (workspace / reference / "run.py").write_text('print("changed")')
    with pytest.raises(ValueError, match="CANDIDATE_CHANGED"):
        service.freeze(reference, candidate)
    with pytest.raises(ValueError):
        service.path("../" + workspace.name + "-sibling")


@pytest.mark.parametrize("epochs, verdict", [(10, "SUPPORTED"), (0, "NOT_SUPPORTED")])
async def test_complete_lifecycle_and_restart(workspace, epochs, verdict):
    expected_verdict = verdict
    server = create_server(str(workspace))

    async def invoke(name, **arguments):
        response = await server.call_tool(name, arguments)
        if isinstance(response, tuple):
            return response[1]
        return json.loads(response[0].text)

    service = ExperimentService(workspace)
    reference = draft(workspace)
    path = workspace / reference
    contract = yaml.safe_load((path / "EXPERIMENT.yaml").read_text())
    contract["scientific_parameters"] = {"epochs": epochs}
    contract["evaluation"]["acceptance"]["threshold"] = 0.8
    (path / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
    (path / "run.py").write_text(ML_RUNNER)
    preflight = await invoke("experiment_preflight", experiment=reference)
    frozen = await invoke(
        "experiment_freeze",
        experiment=reference,
        expected_candidate_id=preflight["candidate_id"],
    )
    assert frozen["status"] == "FROZEN"
    await invoke("experiment_bundle", experiment=reference)
    request = await invoke(
        "experiment_run", experiment=reference, idempotency_key="unique-request"
    )
    assert service.run(reference, "unique-request")["run_id"] == request["run_id"]
    run_id = request["run_id"]
    for _ in range(200):
        try:
            state = service.status(run_id)
            if state.get("state") == "RESULTS_AVAILABLE":
                break
            assert state.get("status") not in {"ERROR", "BLOCKED"}, state
        except KeyError:
            pass
        await asyncio.sleep(0.05)
    else:
        pytest.fail(str(service.status(run_id)))
    service = ExperimentService(workspace)
    fetched = await invoke("experiment_fetch", run_id=run_id)
    assert service.fetch(run_id) == fetched
    assert (await invoke("experiment_verify", run_id=run_id))["verified"]
    verdict = await invoke("experiment_adjudicate", run_id=run_id)
    assert verdict["scientific_verdict"] == expected_verdict
    assert service.result(run_id)["adjudication"] == verdict
    artifacts = service.artifacts(run_id)["items"]
    assert artifacts
    assert service.artifact_read(run_id, artifacts[0]["artifact_id"])["text"]
    service.record("proposals", {"hypothesis": "Next experiment"})
    assert service.history()["proposals"]["count"] == 1
    evidence = Path(fetched["evidence_path"])
    (evidence / "outputs/metrics.json").write_text('{"accuracy":0}')
    assert not service.verify(run_id)["verified"]
    assert service.adjudicate(run_id)["scientific_verdict"] == "INCONCLUSIVE"


ML_RUNNER = """import json,sys,math
from pathlib import Path
bundle=Path(sys.argv[sys.argv.index('--bundle-root')+1])
out=Path(sys.argv[sys.argv.index('--output-root')+1]); out.mkdir(parents=True,exist_ok=True)
contract=json.loads((bundle/'resolved_contract.json').read_text())
# Disjoint fixed training and held-out samples; train logistic regression.
train=[(i/100, int(i>0)) for i in range(-100,101) if i]
test=[((i+.5)/100, int(i>=0)) for i in range(-80,80)]
w=0.0
for epoch in range(contract['scientific_parameters']['epochs']):
    gradient=sum((1/(1+math.exp(-w*x))-y)*x for x,y in train)/len(train)
    w-=gradient
accuracy=sum(int(w*x>=0)==y for x,y in test)/len(test)
(out/'metrics.json').write_text(json.dumps({'accuracy':accuracy}))
"""


def test_generic_kaggle_bundle_and_bootstrap(workspace):
    import subprocess

    service = ExperimentService(workspace)
    reference = draft(workspace)
    path = workspace / reference
    contract = yaml.safe_load((path / "EXPERIMENT.yaml").read_text())
    contract["scientific_parameters"] = {"epochs": 10}
    contract["execution"]["kaggle"] = {
        "metadata": {"id": "owner/private-kernel"},
        "inputs": {},
    }
    (path / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
    (path / "run.py").write_text(ML_RUNNER)
    service.freeze(reference, service.preflight(reference)["candidate_id"])
    bundled = service.bundle(reference)
    bundle = workspace / bundled["bundle_path"]
    from expcon.runner.backends import KaggleBackend

    backend = KaggleBackend(workspace)
    from expcon.bundle.bundle import BundleVerifier

    assert BundleVerifier(bundle, bundled["bundle_id"]).verify()["status"] == "PASS"
    output = workspace / "remote-output"
    result = subprocess.run(
        [
            sys.executable,
            str(bundle / "runner/_expcon_kaggle.py"),
            str(bundle),
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((output / "main/metrics.json").read_text())["accuracy"] >= 0.8
    assert json.loads((output / "environment.json").read_text())["provider"] == "kaggle"
    assert backend.name == "kaggle"


def test_admission_rejects_conflict_and_missing_input_identity(workspace):
    service = ExperimentService(workspace)
    reference = draft(workspace)
    path = workspace / reference
    contract = yaml.safe_load((path / "EXPERIMENT.yaml").read_text())
    contract["execution"]["invocation"] = {
        "inputs": {"data": {"kind": "file"}},
        "argv": ["${inputs.data.path}"],
    }
    (path / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
    with pytest.raises(ValueError, match="SCIENTIFIC_INPUT_IDENTITY_REQUIRED"):
        service.freeze(reference, service.preflight(reference)["candidate_id"])
    conflict = workspace / "experiments/trial_v001"
    conflict.mkdir()
    contract["execution"].pop("invocation")
    contract["hypothesis"]["statement"] = "Existing different hypothesis"
    (conflict / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
    (conflict / "run.py").write_text('print("existing")')
    with pytest.raises(ValueError, match="EXPERIMENT_IDENTITY_CONFLICT"):
        service.import_draft(reference)


@pytest.mark.parametrize("notebook", [False, True])
async def test_live_kaggle_opt_in(workspace, notebook):
    """Explicit opt-in; uses only the private test kernel supplied by the operator."""
    import os
    import time

    kernel = os.environ.get("EXPCON_LIVE_KAGGLE_KERNEL")
    if not kernel:
        pytest.skip(
            "Set EXPCON_LIVE_KAGGLE_KERNEL to an authorized private test kernel"
        )
    service = ExperimentService(workspace)
    reference = draft(workspace)
    path = workspace / reference
    contract = yaml.safe_load((path / "EXPERIMENT.yaml").read_text())
    contract["scientific_parameters"] = {"epochs": 10}
    contract["execution"]["allowed_backends"] = ["kaggle"]
    contract["execution"]["kaggle"] = {
        "metadata": {
            "id": kernel,
            "title": "Expcon live validation",
            "is_private": True,
            "enable_gpu": False,
            "enable_internet": False,
        },
        "inputs": {},
    }
    if notebook:
        contract["execution"]["stages"][0]["entrypoint"] = "run.ipynb"
        source = (
            "import os,sys\nsys.argv=['runner','--bundle-root',os.environ['EXPCON_BUNDLE_ROOT'],'--output-root',os.environ['EXPCON_OUTPUT_ROOT']]\n"
            + ML_RUNNER
        )
        (path / "run.ipynb").write_text(
            json.dumps(
                {
                    "nbformat": 4,
                    "nbformat_minor": 5,
                    "metadata": {
                        "kernelspec": {
                            "name": "python3",
                            "display_name": "Python 3",
                            "language": "python",
                        }
                    },
                    "cells": [
                        {
                            "cell_type": "code",
                            "metadata": {},
                            "source": source,
                            "outputs": [],
                            "execution_count": None,
                        }
                    ],
                }
            )
        )
        (path / "kernel-metadata.json").write_text(
            json.dumps({"id": kernel, "code_file": "run.ipynb"})
        )
    else:
        (path / "run.py").write_text(ML_RUNNER)
    (path / "EXPERIMENT.yaml").write_text(yaml.safe_dump(contract))
    service.freeze(reference, service.preflight(reference)["candidate_id"])
    service.bundle(reference)
    run = service.run(
        reference, "live-" + str(notebook), backend="kaggle", kernel=kernel
    )
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        state = service.status(run["run_id"])
        assert state.get("status") not in {"ERROR", "BLOCKED"}, state
        assert state.get("state") not in {"FAILED_EXECUTION", "BLOCKED"}, state
        if state.get("state") == "RESULTS_AVAILABLE":
            break
        await asyncio.sleep(5)
    else:
        pytest.fail("Kaggle completion timeout; retained run requires reconciliation")
    # Advance the same kernel before retrieving the historical output.
    later_reference = draft(workspace, "later")
    later_path = workspace / later_reference
    later_contract = dict(contract)
    later_contract["experiment"] = {
        "id": "LATER",
        "version": "v001",
        "title": "Later negative fixture",
    }
    later_contract["scientific_parameters"] = {"epochs": 0}
    (later_path / "EXPERIMENT.yaml").write_text(yaml.safe_dump(later_contract))
    if notebook:
        (later_path / "run.ipynb").write_bytes((path / "run.ipynb").read_bytes())
        (later_path / "kernel-metadata.json").write_bytes(
            (path / "kernel-metadata.json").read_bytes()
        )
    else:
        (later_path / "run.py").write_text(ML_RUNNER)
    service.freeze(later_reference, service.preflight(later_reference)["candidate_id"])
    service.bundle(later_reference)
    later = service.run(
        later_reference, "later-version", backend="kaggle", kernel=kernel
    )
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        state = service.status(later["run_id"])
        assert state.get("status") not in {"ERROR", "BLOCKED"}, state
        assert state.get("state") not in {"FAILED_EXECUTION", "BLOCKED"}, state
        if state.get("state") == "RESULTS_AVAILABLE":
            break
        await asyncio.sleep(5)
    else:
        pytest.fail("Later Kaggle version did not complete")
    service.fetch(later["run_id"])
    assert service.verify(later["run_id"])["verified"]
    assert service.adjudicate(later["run_id"])["scientific_verdict"] == "NOT_SUPPORTED"
    service.fetch(run["run_id"])
    assert service.verify(run["run_id"])["verified"]
    assert service.adjudicate(run["run_id"])["scientific_verdict"] == "SUPPORTED"
