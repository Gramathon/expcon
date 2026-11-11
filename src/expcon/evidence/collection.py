"""Normalize local/fetched outputs without flattening stage namespaces."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from expcon.evidence.evidence import EvidenceError
from expcon.util.path import contained_path


def collect_outputs(lifecycle, run, bundle: Path, raw: Path) -> Path:
    source = lifecycle.run_dir(run.run_id) / "collections" / uuid.uuid4().hex
    source.mkdir(parents=True)
    contract = json.loads((bundle / "resolved_contract.json").read_text())
    shutil.copy2(bundle / "resolved_contract.json", source / "resolved_contract.json")
    environment = run.metadata.get("environment")
    if not environment:
        raise EvidenceError(
            "Execution environment attestation is missing; fetch host is not execution evidence"
        )
    (source / "environment.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n"
    )
    outputs = source / "outputs"
    outputs.mkdir()
    stages = [stage["id"] for stage in contract.get("execution", {}).get("stages", [])]
    for stage in stages:
        stage_root = contained_path(raw, stage)
        if stage_root.is_dir():
            for path in stage_root.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(stage_root).as_posix()
                    checked = contained_path(stage_root, relative)
                    destination = contained_path(source / "stages" / stage, relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(checked, destination)
                    if path.name not in {
                        "invocation.json",
                        "process.json",
                        "stdout.log",
                        "stderr.log",
                    }:
                        target = contained_path(outputs / "stages" / stage, relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(checked, target)
    for relative in contract["outputs"]["required"]:
        candidates = [contained_path(raw, relative)]
        candidates.extend(contained_path(raw / stage, relative) for stage in stages)
        candidates = [path for path in candidates if path.is_file()]
        if len(candidates) != 1:
            raise EvidenceError(f"Required output missing or ambiguous: {relative}")
        destination = contained_path(outputs, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], destination)
    metrics_relative = contract.get("evaluation", {}).get(
        "metrics_file", "metrics.json"
    )
    metrics_source = contained_path(outputs, metrics_relative)
    if metrics_source.is_file():
        destination = source / "metrics/metrics.json"
        destination.parent.mkdir()
        shutil.copy2(metrics_source, destination)
    for name in ("results.json", "artifact_custody.json"):
        if (raw / name).is_file():
            shutil.copy2(raw / name, source / name)
    return source


def locate_evidence(workspace: Path, run) -> Path:
    if run.metadata.get("evidence_path"):
        return Path(run.metadata["evidence_path"])
    for path in (
        workspace / ".expcon/runs" / run.run_id / "evidence",
        workspace / ".expcon/fetched" / run.run_id / "evidence",
    ):
        if path.is_dir():
            return path
    return workspace / ".expcon/fetched" / run.run_id
