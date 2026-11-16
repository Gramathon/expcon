"""Small, typed acceptance language. Observations never define their own rules."""

from __future__ import annotations

import math
import operator
from typing import Any


COMPARISONS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}


def numeric(value: Any) -> bool:
    try:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    except OverflowError:
        # JSON integers outside the supported finite measurement range fail closed.
        return False


def validate_acceptance(rule: Any) -> None:
    """A comparison or nonempty conjunction; no inferred operator/direction."""
    if not isinstance(rule, dict):
        raise ValueError("acceptance must be an object")
    if set(rule) == {"all"}:
        if not isinstance(rule["all"], list) or not rule["all"]:
            raise ValueError("acceptance.all must be a nonempty list")
        for child in rule["all"]:
            validate_acceptance(child)
        return
    if set(rule) != {"metric", "operator", "threshold"}:
        raise ValueError("acceptance requires metric, operator and threshold (or all)")
    if not isinstance(rule["metric"], str) or not rule["metric"]:
        raise ValueError("acceptance.metric must be a nonempty observation path")
    if rule["operator"] not in COMPARISONS or not numeric(rule["threshold"]):
        raise ValueError("acceptance requires a supported numeric comparison")


def evaluate_acceptance(rule: Any, observations: dict[str, Any]) -> str:
    """Return an exact verdict; incomplete observations make the result inconclusive."""
    try:
        validate_acceptance(rule)
    except (ValueError, TypeError):
        return "INCONCLUSIVE"
    if "all" in rule:
        results = [evaluate_acceptance(child, observations) for child in rule["all"]]
        if "INCONCLUSIVE" in results:
            return "INCONCLUSIVE"
        return (
            "SUPPORTED"
            if all(result == "SUPPORTED" for result in results)
            else "NOT_SUPPORTED"
        )
    value: Any = observations
    for key in rule["metric"].split("."):
        if not isinstance(value, dict) or key not in value:
            return "INCONCLUSIVE"
        value = value[key]
    if not numeric(value):
        return "INCONCLUSIVE"
    return (
        "SUPPORTED"
        if COMPARISONS[rule["operator"]](value, rule["threshold"])
        else "NOT_SUPPORTED"
    )
