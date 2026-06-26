"""Configurable agent persona sets — which package template each role uses.

A lab picks a set ("metric" for the classic Worker/Director/Critic, "coding" for the
Engineer/Reviewer/Tech-lead). Selectable via lab config and a CLI flag.
"""

from __future__ import annotations

from importlib import resources

PERSONAS = {
    "metric": {"worker": "CLAUDE.md", "director": "director.md", "critic": "critic.md"},
    "coding": {"engineer": "engineer.md", "reviewer": "reviewer.md", "techlead": "techlead.md"},
}


def spec_text(role: str, persona_set: str = "coding") -> str:
    """Load the template text for a role in a persona set (shipped as package data)."""
    try:
        fname = PERSONAS[persona_set][role]
    except KeyError as e:
        raise KeyError(f"no persona '{role}' in set '{persona_set}'") from e
    return (resources.files("leanlab") / "templates" / "agents" / fname).read_text().strip()
