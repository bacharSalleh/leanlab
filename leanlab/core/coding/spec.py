"""Spec a coding task — the spec-writer drafts a spec + acceptance tests in an isolated
git worktree, loops on the operator's feedback, then LOCKS the tests as the frozen
criteria the engineer is judged by (and can't change).

Realizes the spec-task use case. `runner` / `ui` are injected so it's testable without
Claude or a terminal.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..loop import make_runner
from .events import EventLog
from .git import Git
from .locks import LockStore

# Filler words dropped from slugs so the name leads with what matters.
_SLUG_STOP = {"a", "an", "the", "to", "of", "for", "in", "on", "and"}


class SpecWriter:
    """Drafts a spec + acceptance tests via Claude, loops on feedback, then locks the tests."""

    def __init__(self, runner=None, ui=None, git=None):
        self._runner = runner
        self._ui = ui or SpecUI()
        self._git = git or Git()

    @staticmethod
    def slug(task: str, max_len: int = 50) -> str:
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

    @staticmethod
    def _prompt(task: str, feedback: str | None) -> str:
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

    def spec(self, repo, task, *, yes=False):
        """Draft → approve → lock the acceptance tests for a task. Returns a dict or None.

        yes=True auto-approves the first draft (headless, for an agent driving leanlab).
        """
        repo = Path(repo).resolve()
        ui = self._ui
        if not self._git.is_repo(repo):
            ui.error("not a git repository — coding labs need git for worktree isolation")
            return None

        slug = self.slug(task)
        wt, branch = self._git.create_worktree(repo, slug)
        runner = self._runner or make_runner(wt)   # the spec-writer works inside the worktree
        locks, events = LockStore(repo), EventLog(repo)

        feedback = None
        while True:
            with ui.status("Spec-writer is drafting the spec + acceptance tests…"):
                res = runner.run_structured(self._prompt(task, feedback), ["spec_md", "tests"])
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
                    p.chmod(0o644)                  # a prior spec run may have locked this file
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
                    (wt / t["path"]).chmod(0o444)   # in-tree lock is a cosmetic guardrail only
                locks.write(slug, locked)
                events.log(slug, {"event": "spec", "tests": [t["path"] for t in files]})
                break
            if action == "cancel":
                ui.note("Cancelled — worktree kept, tests not locked.")
                return None
            feedback = text

        ui.success(wt, branch)
        return {"worktree": str(wt), "branch": branch, "test_paths": [t["path"] for t in files]}


# --- module shims (kept for the CLI, tests, and the trace recorder) ---------
_GIT = Git()


def _git(repo, *args):
    return _GIT.run(repo, *args)


def _is_git_repo(repo) -> bool:
    return _GIT.is_repo(repo)


def _create_worktree(repo, slug):
    return _GIT.create_worktree(repo, slug)


def _merged_branches(repo):
    return _GIT.merged_branches(repo)


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
        LockStore(repo).remove(s)
        removed.append(s)
    return removed


def spec_task(repo, task, *, runner=None, ui=None, yes=False):
    return SpecWriter(runner=runner, ui=ui).spec(repo, task, yes=yes)


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
