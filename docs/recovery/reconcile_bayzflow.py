"""Read-only historical reconciliation. Writes only its requested local report."""
import argparse
import hashlib
import json
import statistics
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    base = args.source.resolve()
    report_path = args.report.resolve()
    if report_path.is_relative_to(base):
        raise ValueError("Never write into the historical research repository")
    consulted = {}
    def original(relative):
        path = base / relative
        consulted[str(path)] = digest(path)
        return read(path)
    registry = original("results/run_registry.json")
    report = {"source": str(base), "scope": "Independent read-only byte consistency; no research execution or scientific reanalysis",
              "implementation_version": "EXPCON source revision/dirty diff not independently pinned by these records",
              "runs": [], "limitations": ["Historical statuses are not upgraded to new anchored evidence verification",
                                               "SHA256 consistency is not authenticated execution provenance"]}
    for label, run_id in registry.items():
        relative = f".expcon/runs/{run_id}"
        run = original(relative + "/run.json")
        adjudication = original(relative + "/adjudication.json")
        verification = original(f"evidence_controls/{label.lower()}_verification.json" if label != "P8DEV"
                                else "evidence_controls/p8dev_replay_verification.json")
        artifacts = original(relative + "/artifacts.json")["artifacts"]
        failed = []
        for artifact in artifacts:
            path = Path(artifact["path"])
            if not path.is_file() or digest(path) != artifact["hash"]:
                failed.append(artifact["artifact_id"])
        evidence = base / ".expcon/fetched" / run_id / "evidence"
        manifest = original(str(evidence.relative_to(base)) + "/evidence_manifest.json")
        inventory = original(str(evidence.relative_to(base)) + "/artifacts.json")["artifacts"]
        evidence_failures = [entry["path"] for entry in inventory
                             if not (evidence / "artifacts" / entry["path"]).is_file()
                             or digest(evidence / "artifacts" / entry["path"]) != entry["hash"]]
        report["runs"].append({"experiment": label, "run_id": run_id,
             "contract_hash": run["contract_hash"], "bundle_id": run["bundle_id"],
             "backend": run["backend"], "accelerator": run["accelerator"],
             "record_state": run["state"], "historical_verification": verification,
             "historical_statuses": {key: adjudication[key] for key in
                 ["execution_status", "contract_status", "evidence_status", "scientific_verdict"]},
             "registry_entries_rehashed": len(artifacts), "registry_hash_failures": failed,
             "evidence_artifacts_rehashed": len(inventory), "evidence_hash_failures": evidence_failures,
             "evidence_identity_matches_record": all(manifest[key] == run[key] for key in
                 ["run_id", "experiment_id", "contract_hash", "bundle_id"]),
             "corrected_provenance_entries": sum(item.get("metadata", {}).get("source_input_scope") == "actual_frozen_bundle" for item in artifacts)})
    original_id = "run-P8DEV-fae9c38c"
    replay_id = registry["P8DEV"]
    comparisons = {}
    for name in ["evaluation.json", "selection.json"]:
        left = base / ".expcon/runs" / original_id / "stages/main" / name
        right = base / ".expcon/runs" / replay_id / "stages/main" / name
        comparisons[name] = {"original_sha256": digest(left), "replay_sha256": digest(right),
                             "byte_identical": left.read_bytes() == right.read_bytes()}
        consulted[str(left)] = digest(left)
        consulted[str(right)] = digest(right)
    report["replay"] = {"original": original_id, "replay": replay_id, "comparisons": comparisons}
    report["original_verification_failure"] = original("evidence_controls/p8dev_verification.json")
    report["original_run_state"] = original(f".expcon/runs/{original_id}/run.json")["state"]
    polluted = base / "results/operational_failures/p8dev_bytecode_bundle"
    bundle_manifest = original(str(polluted.relative_to(base)) + "/bundle_manifest.json")
    protected = {item["relative_path"] for item in bundle_manifest["files"]} | {"bundle_manifest.json", "hashes.json"}
    report["preserved_polluted_bundle_extras"] = sorted(str(path.relative_to(polluted)) for path in polluted.rglob("*")
                                                         if path.is_file() and str(path.relative_to(polluted)) not in protected)
    sidecar = original("results/expcon_sidecar.json")
    timings = []
    for command in sidecar["control_commands"]:
        argv = command.get("command", [])
        # Other commands also have a stage duration: their negative subtraction is not dispatch overhead.
        if len(argv) > 1 and argv[1] == "run" and "run_id" in command:
            record = original(f".expcon/runs/{command['run_id']}/run.json")
            if record.get("accelerator") == "gpu":
                stages = original(f".expcon/runs/{command['run_id']}/results.json")["stages"]
                duration = sum(stage["duration_seconds"] for stage in stages)
                timings.append({"run_id": command["run_id"], "wrapper_seconds": command["wall_seconds"],
                                "stage_seconds": duration, "control_seconds": command["wall_seconds"] - duration})
    values = [item["control_seconds"] for item in timings]
    report["historical_gpu_dispatch"] = {"rows": timings, "count": len(values), "min": min(values),
        "median": statistics.median(values), "max": max(values),
        "scope": "Local GPU wrapper minus stage duration; no direct-execution baseline, no GPU kernel optimisation claim"}
    index = original("results/confirmation_index.json")
    report["supplementary_input_rehash"] = {"files": len(index["file_sha256"]),
        "mismatches": [name for name, expected in index["file_sha256"].items()
                       if not Path(name).is_file() or digest(Path(name)) != expected]}
    report["consulted_records_sha256"] = consulted
    report["consulted_records_unchanged"] = all(digest(Path(name)) == expected for name, expected in consulted.items())
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        raise ValueError("Refusing to replace an existing reconciliation record")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"runs": len(report["runs"]), "replay": comparisons,
                      "gpu_dispatch": report["historical_gpu_dispatch"],
                      "consulted_records_unchanged": report["consulted_records_unchanged"]}, indent=2))


if __name__ == "__main__":
    main()
