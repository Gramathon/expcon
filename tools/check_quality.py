"""One explicit quality policy shared by local validation and CI."""

import subprocess
import re
from pathlib import Path

# Legacy formatting is tracked separately; no implicit whole-repository reformat.
FORMAT_PATHS = [
    "src/expcon/adjudication/acceptance.py",
    "src/expcon/evidence/collection.py",
    "src/expcon/runner/inputs.py",
    "src/expcon/runner/observation.py",
    "tests/integrity/test_release_regressions.py",
    "tools",
]


def main():
    for target in re.findall(r"\]\(([^)]+)\)", Path("README.md").read_text()):
        if not target.startswith(("https:", "http:", "#")):
            assert Path(target.split("#", 1)[0]).exists(), (
                f"Broken README link: {target}"
            )
    for command in [
        [
            "ruff",
            "check",
            "--no-cache",
            "src/",
            "tools/",
            "tests/integrity/test_release_regressions.py",
        ],
        ["ruff", "format", "--check", "--no-cache", *FORMAT_PATHS],
        ["mypy", "--cache-dir=/tmp/expcon-release-mypy", "src/"],
    ]:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
