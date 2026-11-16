"""Explicit experiment and run state machines.

States and transitions are the deterministic control plane.  No code outside
this module should mutate state directly; always use the transition functions.
"""

from __future__ import annotations

from enum import Enum


class ExperimentState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    FROZEN = "FROZEN"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    RESULTS_AVAILABLE = "RESULTS_AVAILABLE"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    ADJUDICATED = "ADJUDICATED"
    CLOSED = "CLOSED"
    # Failure states
    BLOCKED = "BLOCKED"
    FAILED_EXECUTION = "FAILED_EXECUTION"
    INVALID_RUN = "INVALID_RUN"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"


class RunState(str, Enum):
    """Run-level states track execution progress."""

    CREATED = "CREATED"
    CONTRACT_VERIFIED = "CONTRACT_VERIFIED"
    BACKEND_SELECTED = "BACKEND_SELECTED"
    DATA_VERIFIED = "DATA_VERIFIED"
    STAGE_STARTED = "STAGE_STARTED"
    STAGE_COMPLETED = "STAGE_COMPLETED"
    STAGE_FAILED = "STAGE_FAILED"
    STAGE_CANCELLED = "STAGE_CANCELLED"
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RESULTS_AVAILABLE = "RESULTS_AVAILABLE"
    EVIDENCE_FETCHED = "EVIDENCE_FETCHED"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    ADJUDICATED = "ADJUDICATED"
    COMPLETED = "COMPLETED"
    # Failure states
    BLOCKED = "BLOCKED"
    FAILED_EXECUTION = "FAILED_EXECUTION"
    INVALID_RUN = "INVALID_RUN"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"


# Valid experiment-level transitions.
VALID_TRANSITIONS: dict[ExperimentState, list[ExperimentState]] = {
    ExperimentState.DRAFT: [ExperimentState.VALIDATED, ExperimentState.BLOCKED],
    ExperimentState.VALIDATED: [ExperimentState.FROZEN, ExperimentState.DRAFT, ExperimentState.BLOCKED],
    ExperimentState.FROZEN: [ExperimentState.READY, ExperimentState.BLOCKED],
    ExperimentState.READY: [ExperimentState.SUBMITTED, ExperimentState.BLOCKED],
    ExperimentState.SUBMITTED: [ExperimentState.RUNNING, ExperimentState.FAILED_EXECUTION],
    ExperimentState.RUNNING: [ExperimentState.RESULTS_AVAILABLE, ExperimentState.FAILED_EXECUTION],
    ExperimentState.RESULTS_AVAILABLE: [ExperimentState.EVIDENCE_VERIFIED, ExperimentState.EVIDENCE_INVALID],
    ExperimentState.EVIDENCE_VERIFIED: [ExperimentState.ADJUDICATED],
    ExperimentState.ADJUDICATED: [ExperimentState.CLOSED],
    # Failure states can transition to CLOSED after diagnosis
    ExperimentState.BLOCKED: [ExperimentState.CLOSED, ExperimentState.DRAFT],
    ExperimentState.FAILED_EXECUTION: [ExperimentState.CLOSED],
    ExperimentState.INVALID_RUN: [ExperimentState.CLOSED],
    ExperimentState.CONTRACT_VIOLATION: [ExperimentState.CLOSED],
    ExperimentState.EVIDENCE_INVALID: [ExperimentState.CLOSED, ExperimentState.ADJUDICATED],
    # CLOSED is terminal
    ExperimentState.CLOSED: [],
}

# Valid run-level transitions.
RUN_VALID_TRANSITIONS: dict[RunState, list[RunState]] = {
    RunState.CREATED: [RunState.CONTRACT_VERIFIED, RunState.BLOCKED],
    RunState.CONTRACT_VERIFIED: [RunState.BACKEND_SELECTED, RunState.BLOCKED],
    RunState.BACKEND_SELECTED: [RunState.DATA_VERIFIED, RunState.FAILED_EXECUTION],
    RunState.DATA_VERIFIED: [RunState.STAGE_STARTED, RunState.BLOCKED],
    RunState.STAGE_STARTED: [RunState.STAGE_COMPLETED, RunState.STAGE_FAILED, RunState.STAGE_CANCELLED, RunState.SUBMITTED],
    RunState.SUBMITTED: [RunState.PENDING, RunState.RUNNING, RunState.RESULTS_AVAILABLE, RunState.FAILED_EXECUTION, RunState.BLOCKED],
    RunState.PENDING: [RunState.RUNNING, RunState.RESULTS_AVAILABLE, RunState.FAILED_EXECUTION, RunState.BLOCKED],
    RunState.STAGE_COMPLETED: [RunState.RUNNING, RunState.RESULTS_AVAILABLE, RunState.FAILED_EXECUTION],
    RunState.STAGE_FAILED: [RunState.FAILED_EXECUTION],
    RunState.STAGE_CANCELLED: [RunState.FAILED_EXECUTION, RunState.BLOCKED],
    RunState.RUNNING: [RunState.RESULTS_AVAILABLE, RunState.FAILED_EXECUTION, RunState.BLOCKED],
    RunState.RESULTS_AVAILABLE: [RunState.EVIDENCE_FETCHED, RunState.FAILED_EXECUTION],
    RunState.EVIDENCE_FETCHED: [RunState.EVIDENCE_VERIFIED, RunState.EVIDENCE_INVALID],
    RunState.EVIDENCE_VERIFIED: [RunState.ADJUDICATED, RunState.EVIDENCE_INVALID],
    RunState.ADJUDICATED: [RunState.COMPLETED, RunState.EVIDENCE_INVALID],
    RunState.COMPLETED: [],
    RunState.BLOCKED: [RunState.CREATED, RunState.COMPLETED],
    RunState.FAILED_EXECUTION: [RunState.COMPLETED],
    RunState.INVALID_RUN: [RunState.COMPLETED],
    RunState.EVIDENCE_INVALID: [RunState.ADJUDICATED],
}


class StateError(Exception):
    """Raised when a state transition is invalid."""


def is_valid_transition(current: ExperimentState | RunState, target: ExperimentState | RunState) -> bool:
    """Check whether *target* is a valid successor of *current*."""
    if isinstance(current, ExperimentState):
        return isinstance(target, ExperimentState) and target in VALID_TRANSITIONS.get(current, [])
    elif isinstance(current, RunState):
        return isinstance(target, RunState) and target in RUN_VALID_TRANSITIONS.get(current, [])
    return False


def transition(current: ExperimentState | RunState, target: ExperimentState | RunState) -> None:
    """Validate and allow a state transition, raising StateError on violation."""
    if type(current) is not type(target):
        raise StateError("Experiment and run state namespaces cannot be mixed")
    if current == target:
        return  # No-op transitions are allowed

    if not is_valid_transition(current, target):
        raise StateError(
            f"Invalid state transition: {current.value} -> {target.value}. "
            f"Allowed targets from {current.value}: "
            f"{[s.value for s in VALID_TRANSITIONS.get(current, [])] if isinstance(current, ExperimentState) else [s.value for s in RUN_VALID_TRANSITIONS.get(current, [])]}"
        )
