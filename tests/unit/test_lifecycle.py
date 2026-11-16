"""Tests for experiment and run state machine."""

import pytest

from expcon.lifecycle.state import (
    ExperimentState,
    RunState,
    StateError,
    is_valid_transition,
    transition,
    VALID_TRANSITIONS,
    RUN_VALID_TRANSITIONS,
)


class TestExperimentStateTransitions:
    def test_draft_to_validated(self):
        assert is_valid_transition(ExperimentState.DRAFT, ExperimentState.VALIDATED)

    def test_validated_to_frozen(self):
        assert is_valid_transition(ExperimentState.VALIDATED, ExperimentState.FROZEN)

    def test_draft_to_frozen_rejected(self):
        """DRAFT → FROZEN must not be allowed without validation."""
        assert not is_valid_transition(ExperimentState.DRAFT, ExperimentState.FROZEN)

    def test_frozen_to_ready(self):
        assert is_valid_transition(ExperimentState.FROZEN, ExperimentState.READY)

    def test_running_to_adjudicated_rejected(self):
        """RUNNING → ADJUDICATED without evidence verification must be rejected."""
        assert not is_valid_transition(ExperimentState.RUNNING, ExperimentState.ADJUDICATED)

    def test_results_available_to_adjudicated_rejected(self):
        assert not is_valid_transition(ExperimentState.RESULTS_AVAILABLE, ExperimentState.ADJUDICATED)

    def test_results_available_to_evidence_verified(self):
        assert is_valid_transition(ExperimentState.RESULTS_AVAILABLE, ExperimentState.EVIDENCE_VERIFIED)

    def test_evidence_verified_to_adjudicated(self):
        assert is_valid_transition(ExperimentState.EVIDENCE_VERIFIED, ExperimentState.ADJUDICATED)

    def test_adjudicated_to_closed(self):
        assert is_valid_transition(ExperimentState.ADJUDICATED, ExperimentState.CLOSED)

    def test_closed_is_terminal(self):
        assert len(VALID_TRANSITIONS[ExperimentState.CLOSED]) == 0

    def test_transition_raises_on_invalid(self):
        with pytest.raises(StateError):
            transition(ExperimentState.DRAFT, ExperimentState.RUNNING)

    def test_transition_same_state_ok(self):
        transition(ExperimentState.DRAFT, ExperimentState.DRAFT)  # no-op

    def test_failure_to_closed(self):
        assert is_valid_transition(ExperimentState.FAILED_EXECUTION, ExperimentState.CLOSED)


class TestRunStateTransitions:
    def test_created_to_contract_verified(self):
        assert is_valid_transition(RunState.CREATED, RunState.CONTRACT_VERIFIED)

    def test_contract_verified_to_backend_selected(self):
        assert is_valid_transition(RunState.CONTRACT_VERIFIED, RunState.BACKEND_SELECTED)

    def test_backend_selected_to_data_verified(self):
        assert is_valid_transition(RunState.BACKEND_SELECTED, RunState.DATA_VERIFIED)

    def test_data_verified_to_stage_started(self):
        assert is_valid_transition(RunState.DATA_VERIFIED, RunState.STAGE_STARTED)

    def test_stage_started_to_stage_completed(self):
        assert is_valid_transition(RunState.STAGE_STARTED, RunState.STAGE_COMPLETED)

    def test_stage_started_has_exact_terminal_outcomes(self):
        assert is_valid_transition(RunState.STAGE_STARTED, RunState.STAGE_FAILED)
        assert is_valid_transition(RunState.STAGE_STARTED, RunState.STAGE_CANCELLED)

    def test_stage_completed_to_running(self):
        assert is_valid_transition(RunState.STAGE_COMPLETED, RunState.RUNNING)

    def test_running_to_results_available(self):
        assert is_valid_transition(RunState.RUNNING, RunState.RESULTS_AVAILABLE)

    def test_results_available_to_evidence_fetched(self):
        assert is_valid_transition(RunState.RESULTS_AVAILABLE, RunState.EVIDENCE_FETCHED)

    def test_evidence_fetched_to_evidence_verified(self):
        assert is_valid_transition(RunState.EVIDENCE_FETCHED, RunState.EVIDENCE_VERIFIED)

    def test_evidence_verified_to_adjudicated(self):
        assert is_valid_transition(RunState.EVIDENCE_VERIFIED, RunState.ADJUDICATED)

    def test_adjudicated_to_completed(self):
        assert is_valid_transition(RunState.ADJUDICATED, RunState.COMPLETED)

    def test_completed_is_terminal(self):
        assert len(RUN_VALID_TRANSITIONS[RunState.COMPLETED]) == 0

    def test_invalid_run_to_closed(self):
        assert is_valid_transition(RunState.INVALID_RUN, RunState.COMPLETED)
