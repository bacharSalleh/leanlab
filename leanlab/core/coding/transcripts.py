"""Reads a task's Claude transcripts (under ~/.claude) — the agent chat + token/cost usage.

Holds a per-(name, mtime) parse cache so the board's SSE loop (which polls task detail every
second) doesn't re-parse every transcript file on each poll.
"""

from __future__ import annotations

from pathlib import Path


class Transcripts:
    def __init__(self, repo):
        self._repo = Path(repo)
        self._cache = {}

    def _dir(self, slug):
        """The Claude transcript dir for a task's worktree, or None."""
        wt = self._repo / ".leanlab" / "worktrees" / slug
        base = Path.home() / ".claude" / "projects"
        if not base.is_dir():
            return None
        d = base / str(wt.resolve()).replace("/", "-")
        if d.is_dir():
            return d
        matches = sorted(base.glob(f"*worktrees-{slug}"))   # specific tail — avoids other projects
        return matches[-1] if matches else None

    def _parsed(self, d):
        """[(path, events)] for every session in `d`, oldest first — parsed once, cached by sig."""
        sessions = sorted(d.glob("*.jsonl"))
        sig = tuple((p.name, p.stat().st_mtime) for p in sessions)
        cached = self._cache.get(str(d))
        if cached and cached[0] == sig:
            return cached[1]
        from ..monitor import Dashboard                # reuse the metric dashboard's parser
        parsed = [(p, Dashboard.parse_session(p)[1])
                  for p in sorted(sessions, key=lambda p: p.stat().st_mtime)]
        self._cache[str(d)] = (sig, parsed)
        return parsed

    def events(self, slug):
        """Every agent session's events, oldest first, with a `divider` marker per session."""
        d = self._dir(slug)
        if not d:
            return []
        runs = [events for _p, events in self._parsed(d) if events]
        out = []
        for i, events in enumerate(runs, 1):
            tok = sum((e.get("in_tok") or 0) + (e.get("out_tok") or 0) for e in events)
            out.append({"kind": "divider", "text": f"session {i}/{len(runs)}", "tokens": tok})
            out.extend(events)
        return out

    def usage(self, slug):
        """Total tokens + cost across ALL agent sessions for a task."""
        d = self._dir(slug)
        if not d:
            return {"tokens": 0, "cost": 0.0}
        tokens = cost = 0
        for _p, events in self._parsed(d):
            for e in events:
                tokens += (e.get("in_tok") or 0) + (e.get("out_tok") or 0)
                cost += e.get("cost") or 0
        return {"tokens": tokens, "cost": round(cost, 4)}
