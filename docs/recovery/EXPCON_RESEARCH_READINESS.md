# EXPCON research readiness after recovery

## Bounded conclusion

EXPCON is suitable for supervised, trusted-host, single-process local CPU
experiments with declared input hashes, a retained independent run/lock root and
explicit numeric acceptance criteria. This conclusion is backed by actual model
training/evaluation, negative outcomes, controlled corruption, replay and
independent metric recomputation. It is not production readiness, hostile-agent
containment, universal reproducibility or accelerator-runtime engineering.

Read EXPCON_TRUST_MODEL.md first. Exact commands, original failures, raw records,
identities and final interpreter results are in EXPCON_VALIDATION_REPORT.md and
its accompanying XML/JSON. Do not infer a passed capability from its class name.

## Requirements and evidence

| Capability | Original state | Final state | Supporting evidence | Remaining limitations |
|---|---|---|---|---|
| Experiment identity | Versioned hashes but lock replacement possible after state loss | VERIFIED for retained locks/new local experiments | Freeze-preservation tests; positive/negative locks and core-generated identities | Host must protect roots; no signature or external transparency service |
| Bundle integrity | Mutable file list not fully bound to executable bytes | VERIFIED for declared v3 payload; v2 declared executable checks | Payload+checksum attack rejected; v3 payload inventory; independent study check | V1 consistency only; v2 notebook metadata cannot acquire v3 assurance |
| Runtime input binding | Paths/types without enforced content identity | VERIFIED when explicit file/tree hashes declared | Mutated file/tree/environment tests and actual dataset admission records | Undeclared input/network/dynamic imports and references outside input trees excluded; TOCTOU not OS-enforced |
| Execution reliability | Synchronous assumptions, ignored dependencies, non-atomic snapshots | IMPLEMENTED BUT NOT FULLY VALIDATED generally; bounded local/fake async verified | Full CLI workflow, topological order, atomic journal, concurrent/idempotent transitions, injected snapshot failure | POSIX cooperating writers/local filesystem; no exactly-once remote submission, general resume or distributed scheduler |
| Evidence verification | Optional bundle/run binding, incomplete inventory, verifier wrote evidence | VERIFIED for new sealed local packages | Expected run seal, full inventory, required-copy checks, read-only tests | Protect run root independently; legacy evidence not retroactively upgraded |
| Artifact provenance | Registration conflated hashing and verification; generic registry disconnected | PARTIALLY IMPLEMENTED | REGISTERED semantics; automatic output registration with run/bundle metadata; historical correction preserved | Metadata is not verified causal lineage; parent-role/DAG/supersession semantics not fully enforced |
| Scientific adjudication | Output criteria/verdict authority and substring defect | VERIFIED for explicit numeric comparison/all rules | Full-path adversarial tests, real SUPPORTED and NOT_SUPPORTED, invalid evidence INCONCLUSIVE | Custom clustered/multiplicity-adjusted research gates remain external; unknown formats are inconclusive |
| Backend support | Adapters existed with incomplete workflow integration | PARTIALLY IMPLEMENTED | Local CPU actual runs; fake Kaggle async and provider tests; Colab block/cleanup tests | Kaggle/Tinker need live validation and approval; Colab generic execution unsupported |
| Reproducibility | Declared seed/hash metadata, fixed-output examples | VERIFIED level 4 only for the documented CPU toy study | Fixed disjoint split, full environment inventory, input/model hashes, independent replays and predefined tolerances | No general bitwise cross-hardware claim; no full transitive environment authenticity |
| Operational overhead | Standalone repository lacked measurements | VERIFIED for documented small study | Five paired trials with raw timings; separate validation/build/dispatch/fetch/verify | Shared host, small dataset, no scale extrapolation or GPU optimisation claim |
| Research usability | Synthetic examples and incomplete integration | PARTIALLY IMPLEMENTED | Real local workflow and Bayzflow historical reconciliation | Supervised use; large-data UX, archival policy and complex evaluator interfaces remain limited |
| Security boundaries | Some path guards, secret persistence and shell interpolation gaps | IMPLEMENTED BUT NOT FULLY VALIDATED | Manifest/stage containment, context redaction, timeout redaction, quoted tmux paths | Trusted Python/OS/provider assumptions; no sandbox; output memory/resource limits not generally enforced |

## Workflow-specific readiness

| Workflow | Classification | Evidence and boundary |
|---|---|---|
| Local empirical CPU research | VERIFIED in the scoped workflow | Logistic regression, real synthetic generation, fixed train/test, saved weights/predictions, negative/tamper/replay outcomes |
| Agent-controlled experimentation | PARTIALLY IMPLEMENTED | Structured CLI/skill and deterministic checks; unrestricted agent access to trust roots defeats the threat model |
| Medical imaging | PARTIALLY IMPLEMENTED | Generic contracts/artifacts transferable; E13 is a historical fixed-output fixture, not current imaging validation |
| Transformer interpretability | IMPLEMENTED BUT NOT FULLY VALIDATED for current recovery | Bayzflow Phase7/8 original records/reports exist; Phase8 byte consistency checked; no new transformer experiment |
| LLM fine-tuning | IMPLEMENTED BUT NOT FULLY VALIDATED | Historical Phase7 reports describe restricted GPT-2/LoRA work; Tinker driver boundary mocked; no new fine-tuning run |
| Kaggle workloads | IMPLEMENTED BUT NOT FULLY VALIDATED | Notebook payload/version handling and fake async transitions; live payload-to-version correlation/cancellation still unproven |
| Tinker workloads | IMPLEMENTED BUT NOT FULLY VALIDATED | Mocked SDK/driver identity, model/LoRA and resume declarations; provider state is externally attested |
| Colab generic execution | UNSUPPORTED | Provisioning-only API; CLI blocks before allocation; direct provisioning cleanup tested with a fake client |
| Local GPU attestation | DEFERRED | Current strict local admission refuses unverified GPU/TPU requirements; historical local GPU records are separate evidence |
| Distributed training infrastructure | UNSUPPORTED | Delegating to a managed service is not implementing distributed training, collectives, kernels or utilisation optimisation |

## Identity and compatibility

V1/v2 identity algorithms retain their definitions. V3 is an explicit draft
contract opt-in. Source traversal pruning preserves the selected entry set,
including legacy directory-symlink exclusion. Retained locks are never replaced
when state files disappear or advance. Freeze publishes a complete lock
exclusively, so a concurrent publication cannot overwrite it.

Old unsupported acceptance structures are not guessed. Existing adjudication.json
files and all initial .expcon/examples bytes are retained; new adjudication and
verification attempts have separate records. Historical evidence without a trusted
seal remains historical. A current refusal does not rewrite an old verdict.

## Operational and performance limits

- File hashing is chunked; tree inventory memory grows with file count. A hashed
  index alone does not bind references outside its declared tree.
- Source includes are pruned before traversal, avoiding unrelated directories and
  transient pytest garbage. No hash cache bypasses content verification.
- Full journal snapshots deliberately favour recovery simplicity. Their storage
  grows with event count times metadata size; archival/compaction is not implemented.
- Bundles, raw fetches, output/artifact copies and versioned evidence duplicate
  small payloads. Large checkpoints/data sets have not been benchmarked.
- Local stdout/stderr capture is buffered. General bounded streaming and robust
  descendant-process cancellation are not implemented.
- Submission markers prevent automatic retry of an uncertain stable run ID, but
  cannot make a provider API and local filesystem one transaction. Reconciliation
  is manual when provider identity cannot be durably retained.
- New CLI run invocations are new trials, not an implicit deduplication key.
- Parent roles and scientific metadata meaning require review. Hashes cannot prove
  that a selected input existed before a decision or that an evaluation is unbiased.

## Remaining work, in order

1. Obtain explicit approval for one narrow live provider integration study and
   establish payload-to-provider-version correlation and failure cleanup.
2. Add stronger artifact parent-role and explicit provenance supersession semantics
   if real research requires them; preserve initial records as the Phase8 example did.
3. Measure large-tree/checkpoint inventory/storage and streaming-log behaviour
   before extending claims beyond small single-process workflows.
4. Define a trusted versioned post-analysis interface for complex scientific gates;
   never infer a positive verdict from arbitrary report text.
5. Review removal of tracked generated caches/egg metadata separately. Their
   purpose and pre-existing modifications were identified and preserved; .gitignore
   prevents new generated files from becoming portfolio evidence accidentally.

The project now has stronger evidence for local research-infrastructure engineering.
It still does not independently establish frontier training, RL algorithms,
accelerator optimisation or the candidate's overall suitability for a Fellowship.
