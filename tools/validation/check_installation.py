"""Install a built wheel without development dependencies in isolated runtimes."""

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument(
        "--interpreter", action="append", required=True, metavar="LABEL=PATH"
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError("Refusing to replace a packaging report")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    wheel = args.wheel.resolve()
    report = {
        "wheel": str(wheel),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "checks": [],
    }
    environment = {
        **os.environ,
        "UV_CACHE_DIR": "/tmp/expcon-recovery-uv",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("PYTHONPATH", None)
    for declaration in args.interpreter:
        label, interpreter = declaration.split("=", 1)
        target = Path("/tmp") / ("expcon-clean-" + label + "-" + uuid.uuid4().hex[:8])
        events = []
        commands = [
            ["uv", "venv", str(target), "--python", interpreter],
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(target / "bin/python"),
                str(wheel),
            ],
            [
                str(target / "bin/python"),
                "-I",
                "-B",
                "-c",
                "import expcon,importlib.util,json,sys; from pathlib import Path; from importlib.resources import files; "
                "assert importlib.util.find_spec('pytest') is None; "
                "assert Path(expcon.__file__).is_relative_to(Path(sys.prefix)); "
                "assert files('expcon').joinpath('resources/schemas/experiment-v1.json').is_file(); "
                "assert files('expcon').joinpath('resources/skills/experiment-contract/SKILL.md').is_file(); "
                "print(json.dumps({'module':expcon.__file__,'no_pytest':True}))",
            ],
            [str(target / "bin/expcon"), "--version"],
            [str(target / "bin/expcon"), "--help"],
            [str(target / "bin/expcon"), "doctor", "--json"],
            [str(target / "bin/expcon"), "skill", "status", "--json"],
        ]
        for command in commands:
            result = subprocess.run(
                command, cwd="/tmp", env=environment, text=True, capture_output=True
            )
            events.append(
                {
                    "command": command,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            if result.returncode:
                report["checks"].append(
                    {"python": label, "status": "FAIL", "events": events}
                )
                args.report.write_text(json.dumps(report, indent=2) + "\n")
                raise RuntimeError("Isolated wheel check failed; report preserved")
        report["checks"].append(
            {
                "python": label,
                "environment": str(target),
                "status": "PASS",
                "events": events,
            }
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({row["python"]: row["status"] for row in report["checks"]}))


if __name__ == "__main__":
    main()
