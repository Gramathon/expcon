# Expcon MCP implementation status

The controller exposes explicit lifecycle tools through the official MCP SDK over
stdio and loopback Streamable HTTP. CLI and MCP share lifecycle orchestration;
detached workers persist idempotent dispatch requests and retain run state.
Pi and sol-pi integration includes a research skill, extension and example config.
Copy `.pi/mcp.example.json` to `.pi/mcp.json` and set absolute host paths.

The earlier MCP baseline had 276 passing tests. Distribution validation now has
278 passing tests and two live Kaggle skips on Python 3.10–3.12. Ruff
and mypy pass across source files. Tests cover transport initialization, lifecycle
operations, positive and negative scientific outcomes, tampering and recovery.

Provider validation remains incomplete: Kaggle tests use mocks except for the
opt-in live tests. Pi extension TypeScript and packaged Pi/SoL-Pi lifecycle checks now pass.
See [release readiness](RELEASE_READINESS.md) for exact scopes and limitations.
Workers share the controller identity; OS isolation and resource quotas are not
implemented. Historical identity algorithms retain their meanings; bundle v3
provides the new materialized payload identity.
