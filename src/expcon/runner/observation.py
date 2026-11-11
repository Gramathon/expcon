"""Provider status normalization and conservative local lifecycle reconciliation."""

from expcon.lifecycle.state import RunState


def normalise_status(value: str) -> str:
    value = str(value).strip().lower()
    aliases = {
        "complete": "completed",
        "success": "completed",
        "succeeded": "completed",
        "queued": "pending",
        "submitted": "pending",
        "initializing": "pending",
        "error": "failed",
        "failure": "failed",
        "cancelled": "failed",
        "canceled": "failed",
    }
    return aliases.get(
        value,
        value if value in {"pending", "running", "completed", "failed"} else "unknown",
    )


def observe(lifecycle, run_id: str, provider_state: str) -> str:
    state = normalise_status(provider_state)
    run = lifecycle.load_run(run_id)
    active = {
        RunState.STAGE_STARTED,
        RunState.SUBMITTED,
        RunState.PENDING,
        RunState.RUNNING,
    }
    if run.state not in active:
        return state  # Never undo verification/adjudication or a terminal failure.
    if state in {"pending", "running", "unknown"}:
        if run.state == RunState.STAGE_STARTED:
            lifecycle.update_run_state(
                run_id, RunState.SUBMITTED, "Submission accepted; completion unknown"
            )
        if state == "running" and lifecycle.load_run(run_id).state != RunState.RUNNING:
            lifecycle.update_run_state(
                run_id, RunState.RUNNING, "Provider reports running"
            )
        elif (
            state == "pending"
            and lifecycle.load_run(run_id).state == RunState.SUBMITTED
        ):
            lifecycle.update_run_state(
                run_id, RunState.PENDING, "Provider reports pending"
            )
    elif state == "completed":
        if run.state == RunState.STAGE_STARTED:
            lifecycle.update_run_state(
                run_id, RunState.STAGE_COMPLETED, "Execution completed"
            )
        lifecycle.update_run_state(
            run_id, RunState.RESULTS_AVAILABLE, "Provider/local completion observed"
        )
    elif state == "failed":
        if run.state == RunState.STAGE_STARTED:
            lifecycle.update_run_state(
                run_id, RunState.STAGE_FAILED, "Execution failed"
            )
        lifecycle.update_run_state(
            run_id, RunState.FAILED_EXECUTION, "Provider/local failure observed"
        )
    return state
