"""The PLAYBOOK — project knowledge the tech-lead maintains and the engineer reads.

`.leanlab/PLAYBOOK.md` accumulates conventions, architecture notes, and pitfalls so each
task starts smarter — the coding lab's version of memory. The engineer reads it; after a
successful merge the tech-lead rewrites it. (The test "ratchet" is automatic: each merged
task's locked acceptance tests join the main branch's suite and stay.)
"""

from __future__ import annotations

from pathlib import Path

from ..loop import make_runner
from .events import EventLog
from .personas import Personas


class Playbook:
    """The project's accumulated conventions/pitfalls (`.leanlab/PLAYBOOK.md`) — the lab's memory."""

    def __init__(self, repo):
        self._repo = Path(repo)

    @property
    def path(self):
        return self._repo / ".leanlab" / "PLAYBOOK.md"

    def read(self):
        p = self.path
        return p.read_text().strip() if p.exists() else ""


class TechLead:
    """After a merge, studies the recent changes and rewrites the PLAYBOOK via Claude."""

    _TASK = (
        "Study the recent merged changes (use `git log -p -5` and read key files), then write a "
        "concise `.leanlab/PLAYBOOK.md`: conventions to follow, the architecture map, and "
        "pitfalls already hit, as guidance for the next tasks. Create the `.leanlab` directory if "
        "needed. Write ONLY that file, then stop."
    )

    def __init__(self, runner=None, ui=None, persona_set="coding"):
        self._runner = runner
        self._ui = ui
        self._personas = Personas(persona_set)

    def refresh(self, repo, slug=None):
        """Rewrite the playbook. `slug` ties it to the task so it shows on that task's timeline."""
        runner = self._runner or make_runner(Path(repo))
        prompt = self._personas.text("techlead") + "\n\n" + self._TASK
        if self._ui is not None:
            with self._ui.status("Tech-lead is updating the PLAYBOOK…"):
                runner.run_plain(prompt)
        else:
            runner.run_plain(prompt)
        if slug:
            EventLog(repo).log(slug, {"event": "playbook"})


