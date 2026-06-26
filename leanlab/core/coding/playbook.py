"""The PLAYBOOK — project knowledge the tech-lead maintains and the engineer reads.

`.leanlab/PLAYBOOK.md` accumulates conventions, architecture notes, and pitfalls so each
task starts smarter — the coding lab's version of memory. The engineer reads it; after a
successful merge the tech-lead rewrites it. (The test "ratchet" is automatic: each merged
task's locked acceptance tests join the main branch's suite and stay.)
"""

from __future__ import annotations

from pathlib import Path

from ..loop import make_runner
from .personas import spec_text


def playbook_path(repo) -> Path:
    return Path(repo) / ".leanlab" / "PLAYBOOK.md"


def read_playbook(repo) -> str:
    p = playbook_path(repo)
    return p.read_text().strip() if p.exists() else ""


def update_playbook(repo, *, slug=None, runner=None, ui=None) -> None:
    """Have the tech-lead study recent changes and rewrite .leanlab/PLAYBOOK.md.

    `slug` ties the update to the task that triggered it, so it shows on that task's
    timeline as the tech-lead's step in the loop.
    """
    runner = runner or make_runner(Path(repo))
    prompt = (
        spec_text("techlead", "coding") + "\n\n"
        "Study the recent merged changes (use `git log -p -5` and read key files), then write a "
        "concise `.leanlab/PLAYBOOK.md`: conventions to follow, the architecture map, and "
        "pitfalls already hit, as guidance for the next tasks. Create the `.leanlab` directory if "
        "needed. Write ONLY that file, then stop."
    )
    if ui is not None:
        with ui.status("Tech-lead is updating the PLAYBOOK…"):
            runner.run_plain(prompt)
    else:
        runner.run_plain(prompt)
    if slug:
        from .board import log_event          # lazy: board imports playbook, so import here
        log_event(repo, slug, {"event": "playbook"})
