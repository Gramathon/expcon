# Backends

Backend capability is discovered, not assumed. Conceptually providers may offer
provision, execute, status, logs, fetch, release, or submit. Local is the
reference full-execution backend. Kaggle uses API plus CLI transports. Colab can
provision/status/release but currently cannot execute arbitrary Expcon workloads
or fetch their artifacts.

If the frozen workflow requires unavailable capability, report
`BACKEND_CAPABILITY_MISMATCH` and leave it `BLOCKED`. Do not bypass Expcon,
invent a channel, weaken the contract, or silently switch provider.

**Transport fallback** (Kaggle API to permitted CLI fallback) stays within one
backend. **Backend fallback** (Kaggle to local/Colab) is a provider change and
requires policy/contract support; agents may propose it but must not do it
automatically.
