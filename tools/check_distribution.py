"""Validate built metadata/resources without importing the working-tree package."""

import argparse
import email.parser
import json
import tarfile
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    (wheel,) = args.directory.glob("*.whl")
    (sdist,) = args.directory.glob("*.tar.gz")
    required = {
        "expcon/resources/schemas/experiment-v1.json",
        "expcon/resources/skills/experiment-contract/SKILL.md",
        "expcon/resources/skills/experiment-contract/references/local.md",
        "expcon/resources/templates/AGENTS.fragment.md",
    }
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert required <= names, required - names
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
        (metadata_name,) = (n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_name))
        (entries_name,) = (
            n for n in names if n.endswith(".dist-info/entry_points.txt")
        )
        assert "expcon = expcon.cli:main" in archive.read(entries_name).decode()
    with tarfile.open(sdist) as archive:
        members = archive.getnames()
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in members)
        prefix = members[0].split("/")[0]
        assert {f"{prefix}/src/{name}" for name in required} <= set(members)
        member = archive.extractfile(f"{prefix}/PKG-INFO")
        assert member is not None
        source_metadata = email.parser.BytesParser().parsebytes(member.read())
    for key in ["Name", "Version", "Requires-Python"]:
        assert metadata[key] and metadata[key] == source_metadata[key]
    assert metadata["Name"] == "expcon"
    assert metadata["Requires-Python"] == ">=3.10"
    assert metadata["License-Expression"] == "MIT"
    assert metadata["Description-Content-Type"] == "text/markdown"
    dependencies = metadata.get_all("Requires-Dist", [])
    assert any("tomli" in item and "3.11" in item for item in dependencies)
    print(
        json.dumps(
            {
                "status": "PASS",
                "wheel": wheel.name,
                "sdist": sdist.name,
                "resources_checked": sorted(required),
                "dependencies": dependencies,
            }
        )
    )


if __name__ == "__main__":
    main()
