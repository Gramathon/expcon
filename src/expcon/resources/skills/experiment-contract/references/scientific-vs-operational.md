# Scientific versus operational

Scientific identity can include dataset/split, preprocessing, model or tokenizer
revision, prompt, scientific hyperparameters, seed, evaluation cohort, metric,
and acceptance criteria. Execution observations include host, temporary path,
timestamp, backend run ID, kernel session ID, CPU count, and remote filesystem
path. Hardware is scientific only when the contract explicitly constrains it.

Do not classify a change by intuition. Run `expcon diff <experiment> --json` and
follow its deterministic classification. Frozen drift blocks the version; it does
not authorize a manual repair.
