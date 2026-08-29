"""JSON and YAML I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, data: Any, indent: int = 2) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, indent=indent, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_yaml(path: Path | str) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def write_yaml(path: Path | str, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=True), encoding="utf-8")
