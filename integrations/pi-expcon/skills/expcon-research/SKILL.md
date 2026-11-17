---
name: expcon-research
description: Control scientific experiments through Expcon MCP in Pi and sol-pi; inspect, freeze, execute, verify, and recover research state.
---

# Expcon research

Use ordinary Pi tools to implement and test editable drafts. Scientific records
come from the Expcon controller, which runs on a trusted host.

1. Call expcon_doctor and research_history after starting or recovering a session.
2. Inspect and validate the draft. Use experiment_preflight to obtain the candidate_id.
3. Explicitly call experiment_freeze with that expected_candidate_id.
4. Call experiment_diff, experiment_bundle, and bundle_verify.
5. Call experiment_run with backend, declared input bindings, and a unique idempotency_key.
   Retry uncertain requests with the same key. Never create another key to bypass an uncertain dispatch.
6. Poll experiment_status; read experiment_events for diagnostics.
7. After successful execution, call experiment_fetch, experiment_verify, then experiment_adjudicate.
8. Read experiment_result and experiment_artifacts; record interpretation separately with research_record_decision.

Never infer scientific support from process completion. Preserve independent
execution, contract, evidence and scientific statuses. Missing or invalid evidence
means no scientific conclusion. Never change frozen science to satisfy a backend;
propose a successor with an explicit deviation and obtain authorization to create it.
Use MCP for controlled operations; do not fall back to shell commands.
