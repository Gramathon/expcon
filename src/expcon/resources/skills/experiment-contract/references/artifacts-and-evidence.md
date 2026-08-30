# Artifacts and evidence

An output is a produced file. An artifact is a registered file with identity and
provenance. Evidence is the verified collection that binds outputs to a contract
and run. Important artifacts retain ID, SHA256, experiment/run IDs, producer
stage, backend identity, parent inputs where known, and verification state.

Use `expcon fetch <run>`, `expcon artifacts <run> --json`, and `expcon verify
<run>`. A remote console claim such as `AUC = 0.91` is not evidence by itself.
Never edit an evidence manifest, fabricate a missing artifact, or call an
incomplete run verified; report the missing requirement instead.
