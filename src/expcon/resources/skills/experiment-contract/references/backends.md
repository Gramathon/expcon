# Backends

Backend capability is discovered, not assumed. Conceptually providers may offer
provision, execute, status, logs, fetch, release, or submit. Local is the
reference full-execution backend. Kaggle uses API plus CLI transports. Colab can
provision/status/release but currently cannot execute arbitrary Expcon workloads
or fetch their artifacts. Tinker is a specialised managed LLM training and
sampling service; it is not generic GPU or remote-shell execution.

Tinker capability namespaces include managed training (forward/backward and
optimizer steps in the frozen driver), native sampling, checkpoint handling, and
read-only observability. Its OpenAI-compatible and Anthropic-compatible beta
surfaces are distinct inference protocols, never OpenAI- or Anthropic-hosted
providers. Read [tinker.md](tinker.md) only when `backend=tinker`.

If the frozen workflow requires unavailable capability, report
`BACKEND_CAPABILITY_MISMATCH` and leave it `BLOCKED`. Do not bypass Expcon,
invent a channel, weaken the contract, or silently switch provider.

**Transport fallback** (Kaggle API to permitted CLI fallback) stays within one
backend. **Backend fallback** (Kaggle to local/Colab) is a provider change and
requires policy/contract support; agents may propose it but must not do it
automatically.
