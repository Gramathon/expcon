"""Detached execution entry point; never resubmits an uncertain dispatch."""

import json
import sys
from pathlib import Path
from expcon.service import operations
from expcon.util.json_io import atomic_json, file_lock


def main():
    root = Path(sys.argv[1]).resolve()
    key = sys.argv[2]
    from expcon.util.path import safe_identifier

    safe_identifier(key)
    path = root / ".expcon/requests" / f"{key}.json"
    with file_lock(path.with_suffix(".worker.lock")):
        payload = json.loads(path.read_text())
        if payload["status"] != "QUEUED":
            return
        payload["status"] = "DISPATCHING"
        atomic_json(path, payload)
        request = payload["request"]
        try:
            result = operations.run(
                root,
                root / request["experiment"],
                request["backend"],
                request["kernel"],
                "none",
                tuple(f"{k}={v}" for k, v in request["inputs"].items()),
                (),
                True,
                reserved_run_id=payload["run_id"],
            )
            payload.update(status=result["status"], result=result)
        except Exception as exc:
            payload.update(
                status="BLOCKED", reason="SUBMISSION_OUTCOME_UNKNOWN", error=str(exc)
            )
        atomic_json(path, payload)


if __name__ == "__main__":
    main()
