# Release process

The proposed first release is **v0.2.0**. No tag, registry upload or public release
is created by this packaging change. Merge the PR and let all GitHub checks pass
before an authorised maintainer creates the tag.

## Versions and authority

`pyproject.toml` is authoritative. Run `python tools/release/version.py --sync`
after changing it, then regenerate the uv and npm lock metadata and commit all
changes. `python tools/release/version.py` rejects mismatched Python/root/Pi
manifests. Installed CLI and MCP diagnostics use Python distribution metadata.

Stable versions use `X.Y.Z` and tags `vX.Y.Z`. Release candidates use Python
`X.Y.ZrcN`, Pi `X.Y.Z-rc.N` and tags `vX.Y.Z-rc.N`. The gate rejects other forms.
Before 1.0, minor versions may change public APIs; patches preserve intended
interfaces and scientific identity semantics. Historical identities never gain
new semantics silently. Record breaking distribution/API changes in release notes.

## First release

1. Review/merge the distribution PR to `main`. Inspect all Python 3.10–3.12,
   CPU integrity, package and Pi/SoL-Pi jobs. Configure branch protection so these
   jobs are required. Restrict creation/deletion of `v*` tags to maintainers using
   a repository ruleset; workflow code cannot configure repository governance.
2. Confirm `python tools/release/version.py --tag v0.2.0` succeeds from that commit.
3. Fetch main and check out its reviewed commit, then:

   ```bash
   git tag -a v0.2.0 -m "Expcon 0.2.0"
   git push origin v0.2.0
   ```

4. Watch **Publish release**. It verifies exact tag/version and membership in
   main's history before invoking reusable validation workflows. All checks must
   succeed. No publication runs from PRs or normal main pushes.
5. The Python build runs once. The same wheel is installed on all three Python
   versions, then used by packaged Pi and pinned SoL-Pi tests. These use scripted
   Pi SDK calls; they send no LLM requests and use no provider credentials.
6. The workflow seals the wheel, sdist, npm tarball, validation summary and notes
   with SHA256SUMS. GitHub provenance is generated and verified before publication.
   A draft release receives all assets and is only then published. RCs are marked
   prerelease. If attestations are unavailable for the repository/account, the
   gate fails; enable support before retrying. It never silently drops provenance.

## Verification and reruns

Download all assets, then run `sha256sum --check SHA256SUMS`. Verify provenance:

```bash
gh attestation verify expcon-0.2.0-py3-none-any.whl \
  --repo Gramathon/expcon \
  --signer-workflow Gramathon/expcon/.github/workflows/publish-release.yml
```

No release rerun may replace published binaries. An existing release (including
a draft) makes publication fail safely. Investigate a failed draft manually;
release a new version if published bytes need to change. Never move an existing
published tag. Builds may include timestamps; byte equality across independent
rebuilds is not claimed. Future PyPI Trusted Publishing and npm publishing must
consume these already validated artifacts without rebuilding. Neither registry
is configured for publication here.

Validation jobs have read-only tokens. The provenance job alone receives OIDC
and attestation write permission; only the final publication job receives
contents write. That job checks out no source and executes no downloaded scripts.
All actions are pinned. Tag jobs are serialized per tag. Protect main and the
workflow files through normal review and repository rules.

## Local validation

Use an isolated checkout, not the live scientific environment. The root uv lock
is the development project lock; a research workspace keeps its own scientific
lock. Build outside the checkout:

```bash
uv sync --locked --group dev --python 3.12
uv run --no-sync python tools/check_quality.py
uv run --no-sync pytest
uv build --out-dir /tmp/expcon-release
uv run --no-sync python tools/check_distribution.py /tmp/expcon-release
uv run --no-sync python tools/validation/check_installation.py \
  --wheel /tmp/expcon-release/expcon-0.2.0-py3-none-any.whl \
  --interpreter current="$(uv run --no-sync python -c 'import sys; print(sys.executable)')" \
  --report /tmp/expcon-installation.json
cd integrations/pi-expcon
npm ci --ignore-scripts
npm run typecheck
npm test
npm pack --pack-destination /tmp/expcon-release
```

See the release-validation workflow for the complete clean Pi/MCP and SoL-Pi
procedure. `SOL_PI_PACKAGE` selects a local reviewed SoL-Pi package directory for
`integrations/pi-expcon/tests/installed.mjs`. The release fixture pins SoL-Pi
0.1.1 at 219568034fa54ed121ede80961655e33dfb9d0e3. It verifies loading, MCP tools,
skills, unrelated workspace discovery, positive/negative CPU results, corruption,
persistent history and retry after reconnect. It does not test model-driven
context reduction, inference quality or arbitrary interrupted process recovery.
