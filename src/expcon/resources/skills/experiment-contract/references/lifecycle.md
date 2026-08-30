# Lifecycle

Expcon, not file presence or provider console output, owns lifecycle state.
Conceptual states are `DRAFT`, `VALIDATED`, `FROZEN`, `READY`, `SUBMITTED`,
`RUNNING`, `RESULTS_AVAILABLE`, `EVIDENCE_VERIFIED`, `ADJUDICATED`, and `CLOSED`.
Exceptions include `BLOCKED`, `FAILED_EXECUTION`, `INVALID_RUN`,
`CONTRACT_VIOLATION`, and `EVIDENCE_INVALID`.

Never edit state files to advance a run. Use `expcon status <run> --json`,
`expcon events <run> --json`, and `expcon ps` after a restart; tmux and shell
history are operational aids, not scientific state.

Backend completion is not evidence verification: `Kaggle COMPLETE != EVIDENCE_VERIFIED`.
`COMPLETED / COMPLIANT / VERIFIED / NOT_SUPPORTED` is a
valid scientific result, not a failure to repair.
