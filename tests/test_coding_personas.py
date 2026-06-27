"""Personas — resolve a role in a persona set to its prompt template text."""

import pytest

from leanlab.core.coding.personas import Personas


def test_resolves_coding_roles():
    assert "Reviewer" in Personas("coding").text("reviewer")
    assert "Engineer" in Personas("coding").text("engineer")


def test_resolves_metric_roles():
    assert Personas("metric").text("worker")            # CLAUDE.md worker persona, non-empty


def test_unknown_role_raises():
    with pytest.raises(KeyError):
        Personas("coding").text("nope")
