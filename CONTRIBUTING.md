# Contributing

Thanks for your interest in EXPCON. The project is research infrastructure under
active development. Read the [README](README.md) for current capabilities and
limitations before proposing a change.

## Before opening an issue or pull request

- Search existing issues and pull requests for related work.
- For a bug, include the EXPCON version, Python version, operating system, a
  minimal reproduction, and the observed versus expected behavior.
- Do not attach credentials, private datasets, patient data, model weights, or
  experiment outputs that you are not authorised to share. Redact sensitive
  values from logs.
- For security vulnerabilities, follow [SECURITY.md](SECURITY.md); do not report
  them in a public issue.

## Development checks

The supported validation matrix is Python 3.10, 3.11, and 3.12 on Linux. From a
checkout with `uv` installed:

```bash
uv sync --locked --group dev --python 3.12
uv run --no-sync python -B tools/check_quality.py
PYTHONDONTWRITEBYTECODE=1 uv run --no-sync python -B -m pytest \
  -p no:cacheprovider --cov=src/expcon --cov-branch \
  --cov-report=term-missing
```

Keep changes focused. Add regression tests for behavior changes, especially for
trust, integrity, lifecycle, and scientific-adjudication paths. Integrity tests
should first establish that a valid fixture passes, then make one controlled
change and assert the specific rejection. Do not weaken an assertion just to
make a test pass. Tests and examples should use temporary output locations and
must not require paid or remote compute services.

## Pull requests

- Open changes against `main`, preferably from a topic branch or fork.
- Explain the problem, the approach, relevant compatibility effects, and checks
  run. State clearly when a check was not run.
- Keep generated caches, local run records, credentials, and unrelated formatting
  changes out of the diff.
- Do not silently change historical experiment records or scientific results.
- Expect automated checks and maintainer review before merge. Avoid force-pushing
  shared branches.

## Licensing

The project is distributed under the MIT License. Submit only material that you
have the right to contribute under that license. There is currently no separate
Contributor License Agreement process.
