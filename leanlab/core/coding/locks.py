"""Out-of-worktree store for the LOCKED acceptance tests — the frozen 'done' criteria.

The lock lives at `.leanlab/locks/<slug>.json` (outside the worktree the engineer edits),
so the gate can always restore the pristine tests and detect tampering by sha256.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class LockStore:
    def __init__(self, repo):
        self._repo = Path(repo)

    def _path(self, slug):
        return self._repo / ".leanlab" / "locks" / f"{slug}.json"

    def write(self, slug, tests):
        """Persist the locked tests: a list of {path, content, sha256}."""
        p = self._path(slug)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"tests": tests}))

    def load(self, slug):
        """The lock dict, or None if the task wasn't spec'd."""
        p = self._path(slug)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None

    def is_pristine(self, slug, wt):
        """Did the engineer leave the locked tests untouched? (missing or changed = tampered)."""
        lock = self.load(slug)
        if lock is None:
            return True
        for it in lock.get("tests", []):
            f = Path(wt) / it["path"]
            if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != it["sha256"]:
                return False
        return True

    def restore(self, slug, wt):
        """Rewrite each locked test's pristine content into the worktree."""
        lock = self.load(slug)
        if lock is None:
            return
        for it in lock.get("tests", []):
            f = Path(wt) / it["path"]
            f.parent.mkdir(parents=True, exist_ok=True)
            if f.exists():
                f.chmod(0o644)
            f.write_text(it["content"])
            f.chmod(0o444)          # re-lock read-only, like the original restore

    def remove(self, slug):
        self._path(slug).unlink(missing_ok=True)
