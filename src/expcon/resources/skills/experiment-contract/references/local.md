# Local backend

Local is the reference execution backend, not a shortcut around control.

```bash
expcon run <experiment> --backend local
expcon status <run> --json
expcon fetch <run>
expcon verify <run>
expcon adjudicate <run>
```

Bundle verification, run registration, artifact provenance, evidence, and
adjudication remain required exactly as they do for remote execution.
