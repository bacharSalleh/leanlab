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


class Personas:
    """A persona set; resolves a role to its prompt template text (shipped as package data)."""

    def __init__(self, persona_set: str = "coding"):
        self._set = persona_set

    def text(self, role: str) -> str:
        try:
            fname = PERSONAS[self._set][role]
        except KeyError as e:
            raise KeyError(f"no persona '{role}' in set '{self._set}'") from e
        return (resources.files("leanlab") / "templates" / "agents" / fname).read_text().strip()


