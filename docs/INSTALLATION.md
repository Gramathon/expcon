# Installation and first experiment

Version 0.2.0 is proposed; these GitHub asset URLs become usable only after an
authorised release. Nothing has been published to PyPI or npm by this task.

## Python, without cloning

Download the wheel and SHA256SUMS from the versioned GitHub Release. Verify the
wheel's SHA-256 against the manifest (or download every asset and run
`sha256sum --check SHA256SUMS`). Create a separate controller environment:

```bash
uv venv --python 3.12 /absolute/controller
uv pip install --python /absolute/controller/bin/python \
  'expcon[mcp] @ https://github.com/Gramathon/expcon/releases/download/v0.2.0/expcon-0.2.0-py3-none-any.whl'
/absolute/controller/bin/expcon --version
/absolute/controller/bin/expcon doctor --json
/absolute/controller/bin/expcon-mcp --help
```

With pip in an activated virtual environment:

```bash
python -m pip install 'expcon[mcp] @ https://github.com/Gramathon/expcon/releases/download/v0.2.0/expcon-0.2.0-py3-none-any.whl'
```

For core-only use, omit `[mcp]`. Kaggle and Tinker are separate extras and are
never required by local CPU or MCP usage. An isolated CLI can also be installed
with `uv tool install https://github.com/Gramathon/expcon/releases/download/v0.2.0/expcon-0.2.0-py3-none-any.whl`.
After an authorised package-index publication, the intended equivalents are
`pip install expcon`, `uv tool install expcon`, and `pip install 'expcon[mcp]'`.
Until then, those names are not a verified installation source for this project.

## Pi and SoL-Pi

Download `pi-expcon-0.2.0.tgz`, verify its checksum, then:

```bash
mkdir pi-expcon
tar -xzf pi-expcon-0.2.0.tgz -C pi-expcon
pi install ./pi-expcon/package
export EXPCON_MCP_EXECUTABLE=/absolute/controller/bin/expcon-mcp
export EXPCON_EXECUTABLE=/absolute/controller/bin/expcon
export EXPCON_WORKSPACE=/absolute/research
pi
```

The package contains its extension and skill. It depends on a separately installed
Python controller. From a checkout, `pi install ./integrations/pi-expcon` is also
supported. The root manifest supports Git sources; see the readiness report for
the exact source installation actually tested. A version-tag Git installation
will only be available after that tag exists.

Use `/mcp` to inspect the actual connection and `/expcon-status` for executable
and workspace diagnostics. SoL-Pi is installed separately through its own package;
Expcon exposes the same tools when it is loaded. No model credentials are needed
for the scripted release integration tests.

Default transport is local stdio. To select HTTP, first start
`/absolute/controller/bin/expcon-mcp --workspace /absolute/research`, then set
`EXPCON_MCP_URL=http://127.0.0.1:7680/mcp` before starting Pi. The server binds
loopback; the adapter rejects public endpoints. A configured `expcon` entry in
mcp.json takes precedence over the extension. Remove stale entries when changing
controller settings, then restart Pi. The workspace must already exist.

## Complete first CPU experiment

Activate the controller environment containing the wheel and MCP extra. The
packaged example reuses the release CPU workload: fixed disjoint data, trained
logistic regression and a zero-epoch negative control. It creates a new directory
and refuses to overwrite an existing one. It never freezes automatically.

```bash
export PATH=/absolute/controller/bin:$PATH
python -m expcon.resources.examples.cpu.create_drafts /tmp/expcon-first --write-contracts
cd /tmp/expcon-first
expcon init
expcon inspect experiments/positive --json
expcon validate experiments/positive --json
expcon preflight experiments/positive --input "dataset=$PWD/data/dataset.json" --json
expcon freeze experiments/positive --json
expcon diff experiments/positive --json
expcon bundle experiments/positive --json
expcon verify-bundle experiments/positive/bundle --json
expcon run experiments/positive --backend local --input "dataset=$PWD/data/dataset.json" --json
```

Use the returned run ID for the remaining commands. Poll status until
RESULTS_AVAILABLE, stopping if execution is blocked or failed:

```bash
expcon status RUN_ID --json
expcon fetch RUN_ID --json
expcon verify RUN_ID --json
expcon artifacts RUN_ID --json
expcon adjudicate RUN_ID --json
```

The positive result should be SUPPORTED after evidence verification. Repeat the
same sequence for `experiments/negative`; its successful execution should yield
NOT_SUPPORTED. Scientific criteria are identical; the negative control declares
a zero-epoch ablation before freeze. Never modify a frozen example to change its
outcome. The automated release test additionally corrupts disposable evidence
and checks INVALID/INCONCLUSIVE; do not corrupt real research records.

Pi can initialise the same drafts from `cases.json` using `experiment_init`, then
follow the bundled research skill. Use the returned preflight candidate ID for
explicit freeze, and retry uncertain execution requests using the original key.

## Compatibility and limits

| Component | Validation target |
|---|---|
| Python | 3.10, 3.11, 3.12; other versions unverified |
| OS | Linux/POSIX; GitHub jobs use ubuntu-latest; macOS/Windows unverified |
| Node | 22.23.5 (package requires >=22.19.0) |
| Pi | @earendil-works/pi-coding-agent 1.5.2 |
| SoL-Pi | 0.1.1 at 219568034fa54ed121ede80961655e33dfb9d0e3 |
| MCP | Local stdio; loopback Streamable HTTP protocol/Origin tests |
| Local backend | CPU workload, positive/negative outcomes, corruption and reconnect |
| Remote backends | Mock tests; no live Kaggle/Tinker/Colab validation in this release |

The Pi/SoL-Pi test uses actual package loading and MCP tools with scripted assistant
messages. It does not exercise model inference or certify SoL-Pi's model-driven
compaction/reduction policies. Expcon is research tooling under active development,
not a security sandbox or production distributed execution platform.

## Troubleshooting

- **Python missing:** install a tested interpreter and recreate the controller
  environment. Keep the workload environment separate from the controller.
- **MCP executable missing:** install the wheel with `[mcp]`, check executable
  permissions, and set EXPCON_MCP_EXECUTABLE to its absolute path.
- **Workspace missing/wrong:** create the directory, set EXPCON_WORKSPACE, restart
  Pi, and compare the workspace in `expcon_doctor` with the intended path.
- **Duplicate or stale configuration:** mcp.json wins over extension registration.
  Keep one intended server definition and check `/mcp` after restarting.
- **Optional dependency missing:** install only the required extra. A missing
  provider capability must block execution rather than change frozen science.
- **Backend unverified:** consult the current backend boundary; use local CPU for
  the release example. No provider credentials are needed by standard tests.
- **Evidence verification failed:** retain the run and reports; do not adjudicate
  scientific support from invalid evidence or overwrite the frozen contract.
