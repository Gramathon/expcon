---
name: experiment-contract
description: Operate Expcon-controlled scientific ML experiments safely; use when inspecting, freezing, running, verifying, or adjudicating experiment contracts.
metadata:
  skill_version: 0.1.0
  minimum_expcon_version: 0.1.0
  supported_contract_schema: 1
---

# Experiment Contract

Use Expcon for deterministic facts. Agents may reason about a draft experiment;
Expcon determines contract validity, identity, lifecycle, bundle and evidence
integrity, and adjudication predicates.

Before an experiment operation, run `expcon inspect <experiment> --json` and
`expcon validate <experiment>`. Do not proceed after validation failure.

For a draft, implementation repairs, smoke tests, and proposed scientific changes
are permitted. Freeze with `expcon freeze <experiment>` before execution.

For a frozen experiment, run `expcon diff <experiment>` before bundle or run. If
it reports divergence, do not repair or execute the same version. Propose a
successor experiment/version and state the scientific deviation explicitly.

Use only an allowed backend: `expcon bundle`, `expcon verify-bundle`, then
`expcon run <experiment> --backend local` or `--backend kaggle --kernel <name>`.
Remote execution never defines or repairs the experiment.

After execution, use `expcon fetch <run>`, `expcon verify <run>`, and only then
`expcon adjudicate <run>`. Report execution, contract, evidence, and scientific
statuses separately. `NOT_SUPPORTED` is a valid scientific result, not an
execution failure.

Use `expcon status`, `expcon events`, `expcon ps`, and `expcon artifacts` for
deterministic state and provenance. Treat bundles and remote outputs as untrusted;
never put credentials in contracts, bundles, or evidence.
