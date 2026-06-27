"""Spec a coding task — the spec-writer drafts a spec + acceptance tests in an isolated
git worktree, loops on the operator's feedback, then LOCKS the tests as the frozen
criteria the engineer is judged by (and can't change).

Realizes the spec-task use case. `runner` / `ui` are injected so it's testable without
Claude or a terminal.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from ..loop import make_runner
from .board import log_event
from .locks import LockStore


# Filler words dropped from slugs so the name leads with what matters.
_SLUG_STOP = {"a", "an", "the", "to", "of", "for", "in", "on", "and"}


def _slug(task: str, max_len: int = 50) -> str:
    """A short, readable, stable slug from a task description.

    Rules so the name stays meaningful (vs. a blind 40-char chop):
      1. Use only the first sentence/line — task briefs are often multi-sentence.
      2. Drop filler words ("a", "the", "to", …) so the slug leads with the verb/noun.
      3. Kebab-case and cut on a WORD boundary — never mid-word, never a trailing dash.
    Deterministic: the same task always yields the same slug.
    """
    first = re.split(r"[.\n!?]", task.strip(), maxsplit=1)[0]
    words = re.sub(r"[^a-z0-9]+", " ", first.lower()).split()
    meaningful = [w for w in words if w not in _SLUG_STOP] or words
    out = ""
    for w in meaningful:
        candidate = f"{out}-{w}" if out else w
        if len(candidate) > max_len:
            break
        out = candidate
    if not out and meaningful:                 # a single first word longer than max_len
        out = meaningful[0][:max_len]
    return out or "task"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _is_git_repo(repo) -> bool:
    return _git(repo, "rev-parse", "--is-inside-work-tree").returncode == 0


def _create_worktree(repo, slug):
    """Create (or reuse) an isolated worktree + branch for this task."""
    wt = Path(repo) / ".leanlab" / "worktrees" / slug
    branch = f"leanlab/{slug}"
    gi = Path(repo) / ".gitignore"
    line = ".leanlab/worktrees/"
    if not gi.exists() or line not in gi.read_text():
        with gi.open("a") as f:
            f.write(("" if not gi.exists() or gi.read_text().endswith("\n") else "\n") + line + "\n")
    if wt.exists():
        return wt, branch
    wt.parent.mkdir(parents=True, exist_ok=True)
    r = _git(repo, "worktree", "add", "-b", branch, str(wt))
    if r.returncode != 0:                       # branch may already exist — attach to it
        r2 = _git(repo, "worktree", "add", str(wt), branch)
        if r2.returncode != 0:
            raise RuntimeError("git worktree add failed: " + (r.stderr or r2.stderr).strip())
    return wt, branch


def _merged_branches(repo):
    # `git branch` marks the current branch with "* " and worktree-checked-out ones with "+ ";
    # the name is after the 2-char marker.
    out = _git(repo, "branch", "--merged").stdout
    return {ln[2:].strip() for ln in out.splitlines() if ln.strip()}


def clean_worktrees(repo, slug=None, *, remove_all=False) -> list[str]:
    """Remove task worktrees + branches. Bulk removes only merged ones unless remove_all."""
    repo = Path(repo).resolve()
    wtroot = repo / ".leanlab" / "worktrees"
    if not wtroot.is_dir():
        return []
    merged = _merged_branches(repo)
    if slug:
        targets = [slug] if (wtroot / slug).is_dir() else []
    else:
        all_slugs = [d.name for d in sorted(wtroot.iterdir()) if d.is_dir()]
        targets = all_slugs if remove_all else [s for s in all_slugs if f"leanlab/{s}" in merged]
    removed = []
    for s in targets:
        branch = f"leanlab/{s}"
        force_branch = remove_all or bool(slug) or branch not in merged
        # always --force the worktree: real task worktrees carry an untracked .leanlab-lock.json
        # that would otherwise block removal. Branch deletion stays safe (-d) unless forced.
        _git(repo, "worktree", "remove", "--force", str(wtroot / s))
        _git(repo, "branch", "-D" if force_branch else "-d", branch)
        (repo / ".leanlab" / "locks" / f"{s}.json").unlink(missing_ok=True)
        removed.append(s)
    return removed


def _spec_prompt(task: str, feedback: str | None) -> str:
    base = (
        "You are the SPEC-WRITER for a coding lab. Turn the task below into a precise spec and "
        "a set of ACCEPTANCE TESTS that define 'done'. A different agent (the engineer) will be "
        "judged ONLY by these tests and must not change them — so make them concrete, fair, and "
        "runnable.\n\n"
        f"TASK:\n{task}\n\n"
        "Study the repository in the current directory (read files) to match its language, test "
        "framework, and conventions. Do NOT create or edit any files — return everything in the "
        "JSON. Use one or more acceptance test files as needed. Reply with ONLY this JSON object: "
        '{"spec_md": "<the spec, as markdown>", '
        '"tests": [{"path": "<relative test file path>", "content": "<full file contents>"}]}'
    )
    if feedback:
        return (f"The operator gave feedback on your previous draft:\n\n{feedback}\n\n"
                f"Revise the spec and tests accordingly. {base}")
    return base


def spec_task(repo, task, *, runner=None, ui=None, yes=False):
    """Draft → approve → lock the acceptance tests for a task. Returns a dict or None.

    yes=True auto-approves the first draft (headless, for an agent driving leanlab).
    """
    repo = Path(repo).resolve()
    ui = ui or SpecUI()
    if not _is_git_repo(repo):
        ui.error("not a git repository — coding labs need git for worktree isolation")
        return None

    slug = _slug(task)
    wt, branch = _create_worktree(repo, slug)
    runner = runner or make_runner(wt)          # the spec-writer works inside the worktree

    feedback = None
    while True:
        with ui.status("Spec-writer is drafting the spec + acceptance tests…"):
            res = runner.run_structured(_spec_prompt(task, feedback), ["spec_md", "tests"])
        if not res.ok:
            ui.error("could not draft the spec — aborting.")
            return None
        files = [t for t in res.data["tests"]
                 if isinstance(t, dict) and t.get("path") and "content" in t]
        if not files:
            ui.error("the spec-writer returned no acceptance test files — aborting.")
            return None
        (wt / "SPEC.md").write_text(res.data["spec_md"])
        for t in files:
            p = wt / t["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                p.chmod(0o644)                   # a prior spec run may have locked this file
            p.write_text(t["content"])

        ui.spec(res.data["spec_md"])
        if yes:
            action, text = "approve", None
        else:
            action, text = ui.decide("\n\n".join(f"# {t['path']}\n{t['content']}" for t in files))
        if action == "approve":
            # Store the lock + a PRISTINE copy OUTSIDE the worktree, where the engineer (which
            # works inside the worktree) cannot reach it. The build step restores from here.
            locked = [{"path": t["path"], "content": t["content"],
                       "sha256": hashlib.sha256(t["content"].encode()).hexdigest()} for t in files]
            for t in files:
                (wt / t["path"]).chmod(0o444)    # in-tree lock is a cosmetic guardrail only
            LockStore(repo).write(slug, locked)
            log_event(repo, slug, {"event": "spec", "tests": [t["path"] for t in files]})
            break
        if action == "cancel":
            ui.note("Cancelled — worktree kept, tests not locked.")
            return None
        feedback = text

    ui.success(wt, branch)
    return {"worktree": str(wt), "branch": branch, "test_paths": [t["path"] for t in files]}


class SpecUI:
    """Terminal UI for `leanlab spec` — spinner, spec panel, arrow-key approve menu."""

    def __init__(self):
        from rich.console import Console
        self.console = Console()

    def status(self, message):
        return self.console.status(f"[bold cyan]{message}", spinner="dots")

    def note(self, message):
        self.console.print(message)

    def error(self, message):
        self.console.print(f"[bold red]{message}[/bold red]")

    def spec(self, spec_md):
        from rich.markdown import Markdown
        from rich.panel import Panel
        self.console.print(Panel(Markdown(spec_md), title="Proposed spec", border_style="magenta"))

    def decide(self, test_code):
        import questionary
        from rich.syntax import Syntax
        approve, view, feedback, cancel = (
            "✓ Approve & lock the acceptance tests", "👁 View the acceptance tests",
            "✍ Give feedback (revise)", "✖ Cancel")
        while True:
            choice = questionary.select("What now?", choices=[approve, view, feedback, cancel]).ask()
            if choice is None or choice == cancel:
                return ("cancel", None)
            if choice == view:
                self.console.print(Syntax(test_code, "python", theme="ansi_dark",
                                          line_numbers=True, word_wrap=True))
                continue
            if choice == approve:
                return ("approve", None)
            return ("feedback", questionary.text("Your feedback for the spec-writer:").ask() or "")

    def success(self, worktree, branch):
        from rich.panel import Panel
        self.console.print(Panel(
            f"Spec locked in [bold]{worktree}[/bold]\nbranch [bold]{branch}[/bold]\n\n"
            "Acceptance tests are frozen — the engineer will implement against them.",
            title="✓ Spec ready", border_style="green"))
