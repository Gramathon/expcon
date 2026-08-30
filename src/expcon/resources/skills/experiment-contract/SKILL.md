---
name: experiment-contract
description: Operate Expcon-controlled scientific ML experiments safely; use when inspecting, freezing, running, verifying, or adjudicating experiment contracts.
metadata:
  skill_version: 0.1.0
  minimum_expcon_version: 0.1.0
  supported_contract_schema: 1
  backend_playbooks: [local, kaggle, colab, tinker]
---

# Experiment Contract

Expcon is the deterministic scientific control layer for agent-assisted ML
research. Agents reason; Expcon determines contract identity, freeze/diff,
lifecycle, provenance, artifact registration, evidence verification, and
adjudication. Remote compute executes; it does not define the experiment.

An agent or executor may fail to execute a frozen experiment, but must never
silently change it to succeed. OOM does not authorize a batch-size change;
missing data does not authorize substitution; a missing model revision does not
authorize `latest`; an incapable backend means `BLOCKED`.

## Procedure

Before an experiment operation, use machine-readable control state:

```bash
expcon inspect <experiment> --json
expcon validate <experiment> --json
```

For a DRAFT, you may implement code, repair non-scientific bugs, run tests,
propose parameters, and update the draft contract. Freeze only after validation:

```bash
expcon freeze <experiment>
```

For a FROZEN experiment, run `expcon diff <experiment> --json` before bundling
or dispatch. If it reports divergence, do not repair or execute that version;
propose a successor with its explicit scientific deviation.

For a clean frozen experiment, Expcon owns the workflow:

```bash
expcon bundle <experiment>
expcon verify-bundle <bundle>
expcon run <experiment> --backend <backend>
expcon status <run> --json
expcon fetch <run>
expcon artifacts <run> --json
expcon verify <run>
expcon adjudicate <run>
```

Discover installed capability before choosing a backend: `expcon doctor --json`;
use `expcon kaggle doctor --json`, `expcon colab doctor --json`, or
`expcon tinker doctor --json` when relevant.
Treat tool JSON as authoritative; do not overwrite `status`, `reason`,
capabilities, or blocking conditions with agent judgment.

## Permissions and routing

After freeze, you may inspect, diff, dispatch, monitor, fetch, verify, analyse,
adjudicate, and propose a successor. You must not modify scientific parameters,
datasets, split, model, evaluation, or acceptance criteria.

Read [lifecycle.md](references/lifecycle.md) for state meaning,
[scientific-vs-operational.md](references/scientific-vs-operational.md) for
identity boundaries, and [artifacts-and-evidence.md](references/artifacts-and-evidence.md)
before interpreting results. Read [backends.md](references/backends.md), then
only the selected backend playbook: [local.md](references/local.md),
[kaggle.md](references/kaggle.md), [colab.md](references/colab.md), or
[tinker.md](references/tinker.md).

Prefer Expcon CLI over raw provider calls. Direct provider API/CLI use is limited
to explicit diagnostics and must never mutate Expcon state or bypass its checks.
Never place credentials in contracts, bundles, evidence, events, logs, or agent
messages.
