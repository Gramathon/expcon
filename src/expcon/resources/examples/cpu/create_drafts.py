"""Prepare editable drafts from the existing bundled CPU workload; never freeze."""

import hashlib
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path


def prepare(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "scripts").mkdir()
    resources = files("expcon").joinpath("resources/examples/cpu")
    for name in ("generate.py", "model.py", "protocol.json"):
        (root / "scripts" / name).write_bytes(resources.joinpath(name).read_bytes())
    protocol = json.loads((root / "scripts/protocol.json").read_text())
    (root / "pyproject.toml").write_text(
        '[project]\nname="installed-cpu"\nversion="1"\n'
    )
    (root / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    (root / "installed.lock.toml").write_text(
        'version=1\nrequires-python=">=3.10"\n[[package]]\nname="installed-cpu"\nversion="1"\nsource={virtual="."}\ndependencies=[]\n'
    )
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/generate.py"),
            str(root / "data/dataset.json"),
        ],
        check=True,
        capture_output=True,
    )
    digest = hashlib.sha256((root / "data/dataset.json").read_bytes()).hexdigest()
    cases = []
    for name, epochs, verdict in [
        ("positive", protocol["positive_epochs"], "SUPPORTED"),
        ("negative", protocol["negative_epochs"], "NOT_SUPPORTED"),
    ]:
        contract = {
            "schema_version": 1,
            "bundle_identity_algorithm": "expcon-bundle-v3",
            "experiment": {
                "id": name.upper(),
                "version": "v001",
                "title": "Installed CPU validation",
            },
            "hypothesis": {
                "statement": "Held-out accuracy and log loss meet the fixed protocol"
            },
            "source": {"repository": "."},
            "execution": {
                "allowed_backends": ["local"],
                "source": {
                    "entrypoint": "scripts/model.py",
                    "include": ["scripts/model.py", "scripts/generate.py"],
                },
                "stages": [{"id": "train_evaluate", "entrypoint": "scripts/model.py"}],
                "invocation": {
                    "inputs": {"dataset": {"kind": "file", "sha256": digest}},
                    "argv": [
                        "--dataset",
                        "${inputs.dataset.path}",
                        "--contract",
                        "${contract.path}",
                        "--output-root",
                        "${outputs.root}",
                    ],
                },
            },
            "environment": {"dependency_lock": "installed.lock.toml"},
            "evaluation": {
                "primary_metric": "accuracy",
                "acceptance": protocol["acceptance"],
            },
            "outputs": {"required": ["metrics.json", "model.json", "predictions.json"]},
            "reproducibility": {"level": "seeded", "seed": 1729},
            "scientific_parameters": {
                "epochs": epochs,
                "learning_rate": protocol["learning_rate"],
                "deviation": "trained model"
                if name == "positive"
                else protocol["negative_scientific_deviation"],
            },
        }
        cases.append(
            {
                "experiment": "experiments/" + name,
                "contract": contract,
                "expected": verdict,
            }
        )
    (root / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    return cases


if __name__ == "__main__":
    cases = prepare(sys.argv[1])
    if "--write-contracts" in sys.argv[2:]:
        import yaml

        root = Path(sys.argv[1]).resolve()
        for case in cases:
            experiment = root / case["experiment"]
            experiment.mkdir(parents=True)
            (experiment / "EXPERIMENT.yaml").write_text(
                yaml.safe_dump(case["contract"], sort_keys=False)
            )
