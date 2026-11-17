# Pi Expcon

Thin adapter for the installed Python Expcon MCP server. Requires Pi 1.5.2 and
Node >=22.19.0; runtime dependencies are provided by Pi, not bundled here.

Download the versioned `pi-expcon-0.2.0.tgz` release asset, extract it, then:

```bash
mkdir pi-expcon
# Extract only the package you downloaded and verified with SHA256SUMS.
tar -xzf pi-expcon-0.2.0.tgz -C pi-expcon
pi install ./pi-expcon/package
```

From a source checkout: `pi install ./integrations/pi-expcon`.
The package manifest supplies both the extension and `expcon-research` skill.

Install the Python release wheel with its MCP extra into a separate controller
environment, then configure before launching Pi:

```bash
export EXPCON_MCP_EXECUTABLE=/absolute/controller/bin/expcon-mcp
export EXPCON_EXECUTABLE=/absolute/controller/bin/expcon
export EXPCON_WORKSPACE=/absolute/research
pi
```

The adapter also discovers executables in the research workspace's `.venv-mcp`,
then `.venv`, then PATH. It never injects the source repository into PYTHONPATH.
An explicit `EXPCON_MCP_URL=http://127.0.0.1:7680/mcp` selects loopback HTTP
instead of stdio. Start that server separately with `expcon-mcp --workspace
/absolute/research`; stdio uses `--stdio`. Public HTTP endpoints are rejected.

`/mcp` shows the actual host-managed connection; `/expcon-status` and
`expcon_diagnose` inspect executable/version/workspace diagnostics. The host
gives a configured `expcon` entry in mcp.json precedence over registration.
Use one configuration, or remove the stale entry when changing the environment.
Restart Pi after changing the workspace or executable configuration.

SoL-Pi remains a separate extension package. The release tests exercise its
pinned 0.1.1 source alongside this package using scripted SDK tool calls, without
an LLM request. This does not certify model-driven context compaction behavior.
All scientific lifecycle operations use Expcon MCP; the adapter never freezes,
executes or rewrites experiments itself. Retry interrupted dispatch with the same
idempotency key, inspect persistent history, and verify evidence before interpreting.
