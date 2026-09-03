"""Tests for generic local runtime-environment admission."""

import pytest

from expcon.runner.environment import EnvironmentError, _python_requirement_satisfied


def test_python_requirement_uses_frozen_constraint_not_import_success():
    assert _python_requirement_satisfied("3.12.13", ">=3.12,<3.13")
    assert not _python_requirement_satisfied("3.11.9", ">=3.12,<3.13")


def test_python_requirement_supports_conjunctive_comparisons():
    assert _python_requirement_satisfied("3.12.13", ">=3.12,!=3.12.12")
    assert not _python_requirement_satisfied("3.12.12", ">=3.12,!=3.12.12")


def test_python_requirement_fails_closed_for_unsupported_syntax():
    with pytest.raises(EnvironmentError, match="Unsupported Python requirement clause"):
        _python_requirement_satisfied("3.12.13", "~=3.12")
