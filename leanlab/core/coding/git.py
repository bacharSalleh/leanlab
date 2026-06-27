"""Thin adapter over the `git` CLI: worktrees, branches, staging, merge.

Coding tasks run in isolated git worktrees so the engineer can't touch the rest of the repo;
this owns all the git plumbing behind one object.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class Git:
    def run(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)

    def is_repo(self, repo):
        return self.run(repo, "rev-parse", "--is-inside-work-tree").returncode == 0

    def create_worktree(self, repo, slug):
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
        r = self.run(repo, "worktree", "add", "-b", branch, str(wt))
        if r.returncode != 0:                       # branch may already exist — attach to it
            r2 = self.run(repo, "worktree", "add", str(wt), branch)
            if r2.returncode != 0:
                raise RuntimeError("git worktree add failed: " + (r.stderr or r2.stderr).strip())
        return wt, branch

    def merged_branches(self, repo):
        # `git branch` marks the current branch "* " and worktree-checked-out ones "+ ";
        # the name is after the 2-char marker.
        out = self.run(repo, "branch", "--merged").stdout
        return {ln[2:].strip() for ln in out.splitlines() if ln.strip()}

    def stage(self, wt):
        """Stage all changes except gate caches and the lock file."""
        ep = self.run(wt, "rev-parse", "--git-path", "info/exclude").stdout.strip()
        epath = Path(ep) if Path(ep).is_absolute() else Path(wt) / ep
        try:
            epath.parent.mkdir(parents=True, exist_ok=True)
            cur = epath.read_text() if epath.exists() else ""
            for pat in ("__pycache__/", ".pytest_cache/", ".leanlab-lock.json"):
                if pat not in cur:
                    cur += pat + "\n"
            epath.write_text(cur)
        except Exception:  # noqa: BLE001
            pass
        self.run(wt, "add", "-A")

    def merge(self, repo, wt, branch, slug):
        """Commit the worktree and merge its branch into the repo. Returns (ok, error)."""
        self.stage(wt)
        # The engineer may have committed its own work, so a "nothing to commit" here is fine;
        # what matters is whether the branch actually carries changes to merge (checked below).
        self.run(wt, "commit", "-m", f"leanlab: {slug}")
        r = self.run(repo, "merge", "--no-ff", "-m", f"leanlab: merge {slug}", branch)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout).strip()
        if "up to date" in (r.stdout + r.stderr).lower():
            # Nothing was merged — the branch had no changes over the base. Not a success.
            return False, "nothing to merge — the branch carried no changes"
        return True, ""
