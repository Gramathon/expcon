# Kaggle backend

KaggleBackend combines the official Kaggle Public API and official Kaggle CLI.
Expcon owns scientific semantics; API and CLI are transports. Start with:

```bash
expcon kaggle doctor --json
expcon run <experiment> --backend kaggle --kernel <owner/slug>
expcon status <run> --json
expcon kaggle status <run> --json
```

Use `expcon kaggle inspect <kernel>`, `expcon kaggle dataset inspect <dataset>`,
and `expcon kaggle competition inspect <competition>` for supported structured
diagnostics. Prefer the Public API state that Expcon exposes; use the CLI only
where Expcon designates it as the transport or fallback. Do not issue raw calls
to infer or alter Expcon lifecycle.

A kernel slug is not immutable. A controlled run must bind the exact kernel
version/session identity exposed by Expcon. An exact version is required:
`current`, `latest`, and a slug alone are insufficient. If Expcon returns
`REMOTE_IDENTITY_UNRESOLVED` or
`OUTPUT_VERSION_AMBIGUOUS`, do not claim provenance verification. Never fetch or
bind arbitrary latest output to an older run.

Backend states such as `QUEUED`, `RUNNING`, `COMPLETE`, `ERROR`, and `CANCELLED`
are observations. `Kaggle COMPLETE != EVIDENCE_VERIFIED`: fetch, artifact
registration, evidence construction, and `expcon verify <run>` are still needed.

If Expcon reports `KAGGLE_RATE_LIMITED`, respect its backoff; do not hammer the
provider manually or call the science failed until its retry/deadline policy is
exhausted. Kaggle credentials belong exclusively to Kaggle's configured OAuth or
API-token mechanism. Never print or persist API keys, tokens, `kaggle.json`,
Authorization headers, or cookies.

Competition submissions are permitted only through an implemented Expcon command
using registered artifacts. Do not submit arbitrary files as though they had
Expcon lineage. A valid lineage is submission ref → artifact SHA → predictions →
run → frozen experiment.
