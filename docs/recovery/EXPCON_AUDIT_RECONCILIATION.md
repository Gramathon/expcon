# Audit reconciliation

Recovery completed for the bounded local scope. Initial classifications, original failures, corrections and remaining external-validation boundaries are recorded below.

## Reproduced engineering findings

The audited HEAD and starting HEAD are identical, but the audited working tree
already contained uncommitted Kaggle/subprocess/stage-state changes. Those were
not clean-commit evidence and remain preserved. Checkpoint red XML reports are
the original failing reproductions; green XML reports are separate results.

| Finding | Classification | Reproduction/root cause | Correction/evidence | Remaining boundary |
|---|---|---|---|---|
| Output thresholds/verdict authority | CONFIRMED | Full adjudication returned false support | checkpoint2-red/green.xml; typed frozen evaluator | Metric correctness still depends on trusted measurement code |
| NOT_SUPPORTED substring | CONFIRMED | Full aggregate path returned SUPPORTED | test_negative_aggregate_is_never_positive | No arbitrary output verdict authority retained |
| Missing contract/failed execution/compliance | CONFIRMED | Positive verdict despite missing upstream facts | Full-path gate tests | Trusted host run root required |
| Payload+checksum mutation | CONFIRMED | Bundle verification PASS with altered runner | test_runner_and_mutable_file_checksum_cannot_preserve_identity | V1 historical inspection only; v2 notebook strict admission refused |
| Evidence mutation/omission/substitution | CONFIRMED | Mutable manifest, ignored hashes/environment and output copies | Complete valid baseline mutation tests, evidence v2 run seal | No authenticated attestation against a malicious host |
| Registration labelled VERIFIED | CONFIRMED | Registry registration immediately verified | REGISTERED semantics and run-bound registry | Metadata is not causal provenance proof |
| Async pending treated as failed | STATICALLY CONFIRMED; correction tested | CLI required immediate completed | Fake asynchronous CLI and observation tests | Live provider integration NEEDS EXTERNAL VALIDATION |
| Stage dependencies ignored | CONFIRMED | Reversed dependency declarations executed in list order | Stable topological ordering test | Sequential execution only |
| Persistence/concurrent transitions | CONFIRMED | Corrupt snapshot/racy repeated writes | Atomic journal, advisory lock, CAS, injected crash tests | POSIX local cooperating writers |
| False cancellation success | CONFIRMED | Unknown process returned true | Explicit unsupported false | No general process/provider cancellation |
| Runtime input/environment hashes ignored | CONFIRMED | Changed declared bytes accepted | Input file/tree and nonsecret env identity tests | No automatic external index/dynamic-code closure |
| Manifest/stage path escape | CONFIRMED | Unsafe paths were accessed/accepted | contained_path/safe_identifier and traversal tests | Trusted code is not sandboxed |
| Secret binding persistence | CONFIRMED | Sentinel value in context.json | Keys-only context and output redaction | Trusted code can still access explicitly supplied credentials |
| Ineffective metrics tamper test | STATICALLY CONFIRMED | Missing manifest returned before metric check | Renamed missing-manifest case plus complete baseline mutation | Existing bad test was not counted as proof |
| tomli dependency omission | STATICALLY CONFIRMED | Python 3.10 runtime import absent from dependencies | Packaging checkpoint pending | Dev dependencies previously masked it |
| Generic artifact auto-registration missing | CONFIRMED by integration | Two registries were disconnected | Fetch registers outputs with bundle/run metadata | Parent-role semantics remain author responsibility |
| Bytecode pollution possible | STATICALLY CONFIRMED and historical original found | Imports wrote protected files | Preflight/child bytecode suppression; extra-file tests | Other trusted code can still write to bundle |

## Bayzflow historical evidence reconciliation

Original directory: /data/dev/repos/VScode/bayzflow/research/structural_epistemics/phase8
Bayzflow HEAD observed: 30d18ff5792306a64aa53dd5e483bff292152a24.
No Bayzflow code was imported or executed. The independent read-only script is
reconcile_bayzflow.py and its raw output is evidence/bayzflow-reconciliation.json.
All consulted records retained their starting SHA-256. EXPCON source revision
and dirty diff were not pinned in the historical run records; a version label or
editable path does not establish exact controller implementation.

| Claim | Original evidence | Repository/version | Verification level | Limitations | Application suitability |
|---|---|---|---|---|---|
| Ten authoritative completed/compliant/verified runs | results/run_registry.json; .expcon/runs/<id>/{run,adjudication}.json; evidence_controls/*_verification.json | Bayzflow Phase8, Nov 10 2026; controller revision unpinned | Historical statuses cross-referenced; 207 registry entries and 86 evidence artifacts independently rehashed, zero mismatches | Old evidence has no new run seal; not independent execution re-attestation | Yes, explicitly historical and scoped |
| Four bytecode extras detected | evidence_controls/p8dev_verification.json; preserved results/operational_failures/p8dev_bytecode_bundle | Original run-P8DEV-fae9c38c | Failure record and four actual preserved extras independently inspected | Current historical package remains EVIDENCE_INVALID | Yes; useful failure investigation example |
| Corrected replay preserves evaluation/selection | Original run-P8DEV-fae9c38c and replay run-P8DEV-c4f2a2a4 stage outputs | Same frozen P8DEV/v001, operational bytecode correction | Fresh byte comparisons and SHA256: both output pairs identical | No new model execution; not a universal reproducibility result | Yes, identify exact files and operational correction |
| Dispatch control/preflight 0.65–0.98 s | results/expcon_sidecar.json run commands and original results.json stage durations | Seven local GPU dispatches | Arithmetic independently recomputed: min .651197, median .689138, max .976207 s | Wrapper-minus-stage; no direct baseline, kernel optimisation or scaling claim. Non-run command subtraction rows are not dispatch timings | Yes with methodology and historical qualifier |
| Success can remain inconclusive | All ten original adjudications | Phase8 | COMPLETED/COMPLIANT/VERIFIED/INCONCLUSIVE records inspected | External analysis reports NO-GO; not recomputed as EXPCON verdict | Yes; preserve distinct meanings |
| Transitive inputs required supplementary checks | control.py; results/confirmation_index.json | Phase8 | Script checks referenced SHA256; all 15 referenced files independently rehashed, zero mismatch | Input index hash alone insufficient | Yes as a limitation and recovery motivation |
| Artifact inventory/provenance correction | register_artifacts.py; initial/corrected registry reports and artifacts.json | Phase8 | Initial entries and superseding metadata preserved; content hashes checked | Hashes do not prove correct temporal input roles; initial authoring error was external script semantics | Yes, candidly |

This corrects the previous standalone-repository evidence gap. The historical
research records exist outside EXPCON; they were not available in its initial
inventory. Scientific summary NO-GO remains a reported external analysis, not
a freshly verified statistical conclusion. Phase7A/7B/7C reports and run
directories were located; their scientific results were not reanalysed.

## Additional recovery findings (all original failures retained)

- Cross-namespace equal-name states bypassed the no-op transition guard. CONFIRMED
  by checkpoint7-additional-red.xml; type-specific transition checks now reject it.
- Evidence invalidation erased known process completion in adjudication. CONFIRMED
  in the same red report; independent execution facts now remain COMPLETED while
  evidence is INVALID and science INCONCLUSIVE.
- Differing scientific output/convenience metric copies could be packaged. CONFIRMED
  by checkpoint7-metric-copy-red.xml; packaging/verification compare them and only
  the frozen declared output metric source is evaluated. The aggregate fixture was
  made internally consistent rather than relying on contradictory duplicate metrics.
- Timeout output bypassed normal redaction. CONFIRMED by a fake process emitting a
  sentinel (checkpoint7-timeout-red.xml); no untrusted process was executed.
- Retained frozen locks could be overwritten after state advancement/loss. CONFIRMED
  in both checkpoint7-freeze-red.xml cases; existing locks now block re-freeze and
  complete new lock publication is exclusive. No actual historical lock was modified.
- Source hashing walked unrelated directories, causing a parallel test to encounter
  a removed pytest garbage directory (attempt-python310-interference.xml: 225 passed,
  1 setup error). The failure was retained. Include-directory pruning and isolated
  interpreter basetemps address traversal/test isolation without omitting protected
  entries. checkpoint7-traversal-red.xml reproduces the unnecessary traversal.
- Initial pruning followed directory symlink prefixes differently from the old
  walk. A compatibility regression failed (checkpoint7-symlink-compat-red.xml);
  pruning now retains the legacy exclusion. No v1/v2 algorithm was migrated.

Deferred boundaries from the original audit: generic cancellation/resumption,
network filesystem durability, full causal provenance validation, large-data
performance, live remote identity correlation and complete transitive environment
closure. These are explicitly limited in EXPCON_RESEARCH_READINESS.md. The old
AGENTS unfreeze description is not an implemented authorisation to overwrite a
retained lock; use an explicit successor. No unfreeze/migration was performed.
