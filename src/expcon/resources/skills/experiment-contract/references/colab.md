# Colab backend

Expcon uses the official allowlisted Google Colab Runtime API for runtime-spec
discovery, eligibility inspection, creation, inspection, deletion, and
long-running-operation observation.

```bash
expcon colab doctor --json
expcon colab specs --json
expcon colab runtimes --json
expcon colab inspect <runtime> --json
```

The current backend capability is conceptually `provision=true`, `execute=false`,
`status=true`, `fetch=false`, and `release=true`. The public Runtime API does not
provide an officially supported arbitrary workload-execution or artifact-fetch
channel. Therefore `expcon run <experiment> --backend colab` may safely end
`BLOCKED` with `BACKEND_CAPABILITY_MISMATCH`; provisioning is not experiment
execution and does not produce evidence.

Do not automate the Colab browser, use private browser endpoints, invent
undocumented notebook calls, fabricate outputs, or treat runtime creation as a
successful run. The API is v1beta and allowlist-gated: distinguish not configured,
not allowlisted, authenticated, and capability mismatch using Expcon output.

When runtime identity matters, consume Expcon's recorded actual image/version;
never substitute a guessed current image. Connection information can contain
short-lived credentials. Never expose connection tokens, bearer credentials, or
auth headers in contracts, events, evidence, bundles, logs, or agent messages.
