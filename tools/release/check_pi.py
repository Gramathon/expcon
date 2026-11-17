"""Verify the npm archive contains only standalone Pi extension resources."""

import json
import sys
import tarfile
from pathlib import Path

from version import versions


def check(path):
    with tarfile.open(path) as archive:
        names = set(archive.getnames())
        required = {
            "package/package.json",
            "package/extensions/expcon.ts",
            "package/skills/expcon-research/SKILL.md",
            "package/README.md",
            "package/LICENSE",
        }
        if required != names:
            raise ValueError(f"Unexpected Pi resource set: {required ^ names}")
        for member in archive.getmembers():
            if (
                not member.isfile()
                or not member.name.startswith("package/")
                or ".." in Path(member.name).parts
                or "node_modules" in Path(member.name).parts
            ):
                raise ValueError("Unexpected archive member: " + member.name)
        manifest = json.load(archive.extractfile("package/package.json"))
        if manifest.get("dependencies") or manifest.get("bundledDependencies"):
            raise ValueError("The adapter must use host-provided runtime dependencies")
        assert manifest["name"] == "pi-expcon"
        assert manifest["version"] == versions()[1]
        assert Path(path).name == "pi-expcon-" + manifest["version"] + ".tgz"
        assert manifest["pi"] == {
            "extensions": ["./extensions/expcon.ts"],
            "skills": ["./skills"],
        }
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "version": manifest["version"],
                    "files": sorted(names),
                }
            )
        )


if __name__ == "__main__":
    check(sys.argv[1])
