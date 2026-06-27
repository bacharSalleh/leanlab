"""The coding lab's append-only event log — one jsonl per task, the board's timeline source."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class EventLog:
    def __init__(self, repo):
        self._repo = Path(repo)

    def _path(self, slug):
        return self._repo / ".leanlab" / "events" / f"{slug}.jsonl"

    def log(self, slug, rec):
        p = self._path(slug)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps({**rec, "ts": datetime.now(timezone.utc).isoformat()}) + "\n")

    def read(self, slug):
        p = self._path(slug)
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out
