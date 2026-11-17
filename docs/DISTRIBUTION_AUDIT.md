# Distribution audit — 2026-11-17

Baseline: main 94134bc, following MCP PR #4. The repository has no release tags
or GitHub Releases at audit time. Package version was 0.1.0; propose 0.2.0 for
the first release containing both the Python and Pi distributions.

Working functionality: setuptools sdist/wheel builds; CLI and MCP entrypoints;
optional MCP/Kaggle/Tinker dependencies; bundled schemas/templates/agent skills;
Python 3.10–3.12 CI; positive/negative CPU study, corruption and replay checks.
The current suite contains 278 cases (276 passed, two live Kaggle skips on
Python 3.12). The older 268 count describes the earlier core-only scope.

Gaps: the clean-install checker exercised only the core CLI; it did not start
an installed MCP server. The project-local Pi extension injected source paths,
assumed a workload Python import, and had no distribution manifest or TypeScript
checks. No tag-gated release workflow, cross-package version gate, release asset
manifest or provenance publication existed.

Installed integration baseline: Pi 1.5.2, Node 22.23.5, SoL-Pi 0.1.1 at
219568034fa54ed121ede80961655e33dfb9d0e3. Pi's documented package manifest lists
extensions/skills, uses host peer dependencies and gives mcp.json precedence.
This task changes distribution and integration only; scientific algorithms and
backend behavior are preserved. Build/test environments are isolated from the
live research environment and its E01 lock.
