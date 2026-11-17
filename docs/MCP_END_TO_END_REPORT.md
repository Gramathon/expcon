# MCP validation

The SDK-backed adapter has real stdio client and HTTP initialization/Origin tests.
The separate lifecycle tools execute a trained logistic-regression fixture with
fixed disjoint training and held-out samples. Positive and negative variants
produce SUPPORTED and NOT_SUPPORTED respectively after evidence verification.
Tampered evidence produces INCONCLUSIVE. Tests use disposable workspaces only.

The MCP baseline had 276 passing tests and two live Kaggle skips. The current
distribution suite has 278 passing tests and two skips on Python 3.10–3.12. Ruff and mypy
pass. A wheel builds and installs with the mcp extra in a clean Python 3.12 venv;
both CLI and MCP executable help/version checks pass.

Kaggle bootstrap execution is tested locally. Opt-in private-kernel tests cover
Python and notebook dispatch, fetch, verification and adjudication. Set
EXPCON_LIVE_KAGGLE_KERNEL only for a kernel authorized for test pushes. These tests
were not run: standard release tests do not use provider credentials or kernels.
The modern Kaggle API extra requires Python >=3.11. Exact-version retrieval after a later push
still requires live provider validation; no Kaggle certification is claimed.

The controller and worker share a trusted-host security model. OS isolation,
resource quotas and independent evidence protection are not attested.

Installed-wheel and independently packaged Pi/SoL-Pi validation is recorded in
[release readiness](RELEASE_READINESS.md). These scripted tests use the actual
Pi host and MCP controller without issuing model requests.
