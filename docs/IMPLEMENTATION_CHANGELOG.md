# Expcon MCP implementation status

The controller exposes explicit lifecycle tools through the official MCP SDK over
stdio and loopback Streamable HTTP. CLI and MCP share lifecycle orchestration;
detached workers persist idempotent dispatch requests and retain run state.
Pi and sol-pi integration includes a research skill, extension and example config.
Copy `.pi/mcp.example.json` to `.pi/mcp.json` and set absolute host paths.

Validation on Python 3.12: 276 tests passed, two live Kaggle tests skipped. Ruff
and mypy pass across source files. Tests cover transport initialization, lifecycle
operations, positive and negative scientific outcomes, tampering and recovery.

Provider validation remains incomplete: Kaggle tests use mocks except for the
opt-in live tests. Pi extension TypeScript checking has not been performed.
Workers share the controller identity; OS isolation and resource quotas are not
implemented. Historical identity algorithms retain their meanings; bundle v3
provides the new materialized payload identity.
