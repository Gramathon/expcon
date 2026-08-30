# Tinker backend

Tinker is a managed distributed LLM post-training and sampling service. It is
not generic GPU compute and Expcon never uploads a bundle to a remote shell.
The frozen local driver contains the data, loss/reward, evaluation, and control
loop; it calls Tinker's public SDK while Expcon controls the contract, source,
lifecycle, and provenance.

Before use, inspect installed capabilities rather than relying on remembered
provider behaviour:

```bash
expcon tinker doctor --json
expcon run <experiment> --backend tinker
expcon status <run> --json
expcon artifacts <run>
expcon fetch <run>
expcon verify <run>
expcon adjudicate <run>
```

The public concepts are `ServiceClient` (entry point and capability discovery),
`TrainingClient` (forward/backward, optimizer, save/load), `SamplingClient`
(native controlled sampling), `RestClient` (read-only run/session/checkpoint
inspection), and the optional `tinker` CLI for operator diagnostics. Let Expcon
and the frozen driver select the documented operation; raw SDK/CLI use is
diagnostic-only unless that driver explicitly owns it.

## Frozen training semantics

Never silently change the base model, LoRA rank/config, trainable components,
loss/custom-loss source, optimizer or schedule, reward/RL algorithm, dataset,
seed, renderer, or training/evaluation sampling configuration. A Tinker model
or configuration incompatibility is `TINKER_MODEL_UNSUPPORTED` or
`TINKER_CAPABILITY_MISMATCH`, not permission to rewrite the experiment.

The driver must report stable remote identity (for example training run or
session ID) before Expcon can claim remote provenance. Tinker training completion
does not equal `EVIDENCE_VERIFIED`.

## Checkpoints and resume

Training-state checkpoints (`save_state`) and sampler-weights checkpoints
(`save_weights_for_sampler`) are distinct artifacts. A Tinker path alone is not
locally verified content: use Expcon-supported fetch/hash/registration before
claiming a local artifact is verified. Do not auto-publish checkpoints or push
them to Hugging Face.

`weights_only` and `weights_and_optimizer` resume are scientifically distinct.
Never fall back from full-state resume to weights-only, and never restart from
the base model if resume fails. Report `TINKER_RESUME_MODE_MISMATCH` or propose a
successor experiment instead.

## Sampling protocols

Use native `SamplingClient` for controlled training/evaluation sampling. Tinker
also has beta OpenAI-compatible and Anthropic-compatible inference protocols.
They remain `provider=tinker`, respectively `protocol=openai_compatible` and
`protocol=anthropic_compatible`—not OpenAI or Anthropic hosted inference.

Do not invisibly switch native/OpenAI/Anthropic protocols on failure. Message
rendering, templates, tools, thinking representations, and stops can change
scientific behaviour; a comparison must be an explicit experiment. Unsupported
reasoning or compatible-endpoint options are configuration/capability errors,
not a reason to guess defaults.

## Security and operator inspection

Tinker authentication uses its normal `TINKER_API_KEY` mechanism. Never print,
put in a contract, or persist that key, bearer/auth headers, compatible-endpoint
credentials, or signed checkpoint URLs. For read-only operations use
`expcon tinker runs`, `expcon tinker sessions`, `expcon tinker checkpoints`, or
`expcon tinker trace <session>` with `--json` where available. Do not edit run
state from provider output; return to Expcon for deterministic lifecycle work.
