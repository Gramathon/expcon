"""Deterministic canonicalisation.

Canonical JSON must:
  - sort all object keys recursively
  - use compact separators (no whitespace)
  - produce UTF-8 bytes
  - be independent of YAML formatting, comments, key order, whitespace
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any


def canonical_dict(obj: Any) -> Any:
    """Recursively sort dict keys and normalise container types.

    Returns a structure that json.dumps(sort_keys=True) will render deterministically.
    """
    if isinstance(obj, dict):
        return OrderedDict(
            (str(k), canonical_dict(v)) for k, v in sorted(obj.items(), key=lambda x: str(x[0]))
        )
    if isinstance(obj, (list, tuple)):
        return [canonical_dict(v) for v in obj]
    if isinstance(obj, set):
        return sorted(canonical_dict(v) for v in obj)
    if isinstance(obj, frozenset):
        return sorted(canonical_dict(v) for v in obj)
    # bool is subclass of int; keep as-is, json handles it
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        # Use repr to preserve precision deterministically
        return obj
    if obj is None:
        return None
    # strings, bytes, paths -> str
    if isinstance(obj, bytes):
        return obj.decode("utf-8")
    return str(obj)


def canonical_json(obj: Any) -> str:
    """Return deterministic JSON string for *obj*.

    Equivalent YAML formatting produces identical output.
    """
    canonicalised = canonical_dict(obj)
    return json.dumps(canonicalised, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_bytes(obj: Any) -> bytes:
    """Return deterministic UTF-8 bytes for *obj*."""
    return canonical_json(obj).encode("utf-8")
