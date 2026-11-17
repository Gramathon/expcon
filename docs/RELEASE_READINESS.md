# Release readiness — proposed 0.2.0

The distribution implementation is under review in PR #5. No release tag, public
GitHub Release, PyPI upload or npm publication was created. Local validation ran
on Linux x86_64 in isolated environments, without modifying the live research
checkout, scientific dependency lock or retained research evidence.

## Executed validation

| Check | Result |
|---|---|
| Python 3.10.12 suite | 278 passed, two explicit live Kaggle skips |
| Python 3.11.16 suite | 278 passed, two explicit live Kaggle skips |
| Python 3.12.13 suite | 278 passed, two explicit live Kaggle skips |
| Ruff, scoped formatting, mypy | Passed on all three Python environments |
| Same wheel installed outside checkout on 3.10/3.11/3.12 | Passed core-only CLI/resources checks, optional MCP install, real stdio initialization and doctor tool |
| Sdist-to-wheel, resources and optional dependency metadata | Passed |
| Pi 1.5.2 / Node 22.23.5 strict TypeScript check | Passed |
| Extension configuration/discovery unit tests | Four passed |
| npm tarball contents and host dependency exclusion | Passed |
| Real Pi package install, skill, diagnostics, MCP and CPU lifecycle | Passed with the installed wheel and extracted package in an unrelated workspace |
| Pinned SoL-Pi 0.1.1, commit 2195680 | Passed the same scripted Pi SDK lifecycle, including mcp.json precedence |
| Client interruption/reconnect and repeated request key | Retained the same run ID; two cases produced two runs |
| Positive, negative, corrupted evidence | COMPLETED/SUPPORTED; COMPLETED/NOT_SUPPORTED; INVALID/INCONCLUSIVE |
| Existing CPU study and independent checker | Passed on Python 3.10/3.11/3.12; six runs independently checked per study |
| Installed-wheel CPU study and documented first example | Passed |
| Version/tag mismatch and immutable manifest regression tests | Two passed (included in the Python totals above) |
| GitHub workflow static validation | actionlint 1.7.7 passed |
| GitHub-hosted PR gates at cb257f9 | CI, Research integrity and Release validation all passed; runs 44049193273, 44049193349 and 44049193493 |

The earlier 268 total was the core-only scope; 276 was the MCP baseline. Two
packaging regression cases bring the current suite to 280 collected, 278 passing
and two skipped. No live remote provider execution was attempted.

Local artifacts and machine-readable reports are generated under
`/tmp/expcon-0.2.0-deliverables` and `/tmp/expcon-0.2.0-evidence`. These directories
are local validation output, not published release URLs. The release workflow
regenerates exact artifact hashes and attaches its own validation-summary.json,
release-notes.md and SHA256SUMS. It attests those exact files before publication.

## Remaining release gates

- GitHub-hosted workflow execution, OIDC attestations and actual publication have
  not been exercised by a release tag. The tag workflow fails if those checks fail.
- Main/tag protection and required-check rules must be configured by a repository
  administrator. Workflow code checks source ancestry but cannot enact rulesets.
- Other Pi/SoL-Pi versions, operating systems and Python versions are unverified.
  SoL-Pi was loaded and its hooks used by scripted Pi SDK calls; no live LLM or
  model-driven compaction/reduction behavior was tested.
- Remote backends remain at their existing mocked validation boundary. Execution
  shares the trusted host's identity and is not OS sandboxed.
- Git source installation passed end to end at immutable commit
  e089839c6165ef79d0ff1e50ef70eff57086833e. No version-tag installation was tested
  because no release tag was authorised. Extracted-archive installation also passed.
- The configured SoL-Pi test enables observationPack and onlineContextCompact,
  matching the existing research configuration; actionFusion and the reducer
  remain disabled. It performs no model requests.

See [installation](INSTALLATION.md), [release steps](RELEASING.md), and the
[initial audit](DISTRIBUTION_AUDIT.md). The release workflow intentionally refuses
to overwrite assets under an existing release version.
