"""Independent stdlib-only byte/measurement checks; never imports EXPCON."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load(path):
    return json.loads(path.read_text())


def safe(root, relative):
    path = root / relative
    if (
        Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or not path.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("Unsafe input record")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("study", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError("Preserve existing independent check report")
    study = load(args.study)
    workspace = Path(study["workspace"])
    data = load(workspace / "data/dataset.json")
    rows = []
    for entry in study["runs"]:
        directory = workspace / ".expcon/runs" / entry["run_id"]
        journal = sorted((directory / "journal").glob("*.json"))
        run = load(journal[-1])["record"] if journal else load(directory / "run.json")
        bundle = load(directory / "bundle/bundle_manifest.json")
        identity = hashlib.sha256(
            json.dumps(
                {
                    "algorithm": bundle["bundle_identity_algorithm"],
                    "content": bundle["bundle_content"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
        payload_failures = [
            relative
            for relative, expected in bundle["bundle_content"]["payload_files"].items()
            if sha(safe(directory / "bundle", relative)) != expected
        ]
        evidence = Path(run["metadata"]["evidence_path"])
        manifest = load(evidence / "evidence_manifest.json")
        seals = run["metadata"]["evidence_seals"]
        anchored = {
            "evidence_id": manifest["evidence_id"],
            "manifest_sha256": sha(evidence / "evidence_manifest.json"),
        } in seals
        inventory = load(evidence / "hashes.json")["files"]
        failures = [
            relative
            for relative, expected in inventory.items()
            if sha(safe(evidence, relative)) != expected
        ]
        assert sha(evidence / "hashes.json") == manifest["hashes_sha256"]
        assert (
            identity == run["bundle_id"]
            and anchored
            and not payload_failures
            and not failures
        )
        stage = directory / "stages/train_evaluate"
        model = load(stage / "model.json")
        saved = load(stage / "metrics.json")
        probabilities = []
        for sample in data["test"]:
            score = (
                math.fsum(w * x for w, x in zip(model["weights"], sample["x"]))
                + model["bias"]
            )
            probabilities.append(1 / (1 + math.exp(-max(-40, min(40, score)))))
        accuracy = sum(
            int(p >= 0.5) == sample["y"]
            for p, sample in zip(probabilities, data["test"])
        ) / len(probabilities)
        loss = -math.fsum(
            sample["y"] * math.log(max(p, 1e-15))
            + (1 - sample["y"]) * math.log(max(1 - p, 1e-15))
            for p, sample in zip(probabilities, data["test"])
        ) / len(probabilities)
        assert (
            abs(accuracy - saved["accuracy"])
            <= study["protocol"]["replay_tolerances"]["accuracy_absolute"]
        )
        assert (
            abs(loss - saved["log_loss"])
            <= study["protocol"]["replay_tolerances"]["log_loss_absolute"]
        )
        rule = run["metadata"]["frozen_contract"]["evaluation"]["acceptance"]["all"]
        # Independent evaluation of this study's two preregistered numeric rules.
        assert rule == [
            {"metric": "accuracy", "operator": ">=", "threshold": 0.8},
            {"metric": "log_loss", "operator": "<=", "threshold": 0.55},
        ]
        verdict = "SUPPORTED" if accuracy >= 0.8 and loss <= 0.55 else "NOT_SUPPORTED"
        assert verdict == entry["adjudication"]["scientific_verdict"]
        rows.append(
            {
                "run_id": entry["run_id"],
                "payload_files_checked": len(bundle["bundle_content"]["payload_files"]),
                "evidence_files_checked": len(inventory),
                "anchored": anchored,
                "independent_accuracy": accuracy,
                "independent_log_loss": loss,
                "independent_verdict": verdict,
            }
        )
    report = {
        "status": "PASS",
        "study": str(args.study),
        "study_sha256": sha(args.study),
        "runs": rows,
        "scope": "Independent implementation of byte consistency and held-out metric recomputation from saved weights; not independent training execution or hostile-host attestation",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "runs_checked": len(rows)}))


if __name__ == "__main__":
    main()
