# Re-architecture Increment 1 — Shared entities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the coding lab's four shared low-level concerns into injectable classes — `EventLog`, `LockStore`, `Git`, `Transcripts` — without changing any behavior.

**Architecture:** Each becomes a class that holds its target (the repo path, or nothing for `Git`) and exposes methods. The existing module-level functions (`log_event`, `read_events`, `_load_lock`, `_create_worktree`, `_task_usage`, …) become thin shims that delegate to the new classes, so every current caller and all 86 tests keep working unchanged. Later increments inject these classes into `SpecWriter` / `Engineer` / `Board`; the shims are removed in the final cleanup increment.

**Tech Stack:** Python 3.11+, stdlib only (`pathlib`, `json`, `hashlib`, `subprocess`, `datetime`). Tests: `pytest` via `uv run`.

## Global Constraints

- Behavior-preserving: no feature, CLI, or archik use-case changes. `uv run pytest` → **86 passed** at every task boundary.
- Constructor injection only; no new runtime dependencies; no DI framework.
- Value objects stay `@dataclass`; pure helpers become `@staticmethod`.
- `npx archik validate`, `npx archik drift`, and `npx archik trace` (11 full) stay clean.
- New nodes added to archik only via `npx archik suggest set` (never hand-edit `.archik/main.archik.yaml`).

---

### Task 1: `EventLog`

**Files:**
- Create: `leanlab/core/coding/events.py`
- Modify: `leanlab/core/coding/board.py` (replace `_events_path`/`log_event`/`read_events` bodies with shims)
- Test: `tests/test_coding_events.py`

**Interfaces:**
- Produces: `EventLog(repo: Path|str)` with `.log(slug: str, rec: dict) -> None` (appends `rec` + ISO `ts` to `.leanlab/events/<slug>.jsonl`) and `.read(slug: str) -> list[dict]` (parsed events, `[]` if none).
- Consumed by: `board.log_event`/`read_events` shims now; `SpecWriter`/`Engineer`/`TechLead`/`Board` in later increments.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coding_events.py
from leanlab.core.coding.events import EventLog


def test_log_appends_with_timestamp_and_reads_back(tmp_path):
    log = EventLog(tmp_path)
    log.log("demo", {"event": "attempt", "n": 1})
    log.log("demo", {"event": "merged", "merged": True})
    evs = log.read("demo")
    assert [e["event"] for e in evs] == ["attempt", "merged"]
    assert evs[0]["ts"]                       # ISO timestamp stamped on
    assert evs[0]["n"] == 1


def test_read_missing_is_empty(tmp_path):
    assert EventLog(tmp_path).read("nope") == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_coding_events.py -q`
Expected: FAIL — `ModuleNotFoundError: leanlab.core.coding.events`

- [ ] **Step 3: Implement `EventLog`**

```python
# leanlab/core/coding/events.py
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
```

- [ ] **Step 4: Point the board's functions at it (shims)**

In `leanlab/core/coding/board.py`, add `from .events import EventLog` and replace the three function bodies:

```python
def _events_path(repo, slug):
    return EventLog(repo)._path(slug)

def log_event(repo, slug, rec):
    EventLog(repo).log(slug, rec)

def read_events(repo, slug):
    return EventLog(repo).read(slug)
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — **86 passed** (existing `test_coding_board.py::test_log_and_read_events` still green via the shim) plus the 2 new tests = 88.

- [ ] **Step 6: Commit**

```bash
git add leanlab/core/coding/events.py leanlab/core/coding/board.py tests/test_coding_events.py
git commit -m "refactor: extract EventLog class (board events delegate to it)"
```

---

### Task 2: `LockStore`

**Files:**
- Create: `leanlab/core/coding/locks.py`
- Modify: `leanlab/core/coding/engineer.py` (`_load_lock`, `_is_pristine`, `_restore_tests` → shims), `leanlab/core/coding/spec.py` (lock-writing in `spec_task` → `LockStore.write`)
- Test: `tests/test_coding_locks.py`

**Interfaces:**
- Produces: `LockStore(repo)` with:
  - `.write(slug, tests: list[dict]) -> None` — writes `.leanlab/locks/<slug>.json` as `{"tests": [{path, content, sha256}]}`.
  - `.load(slug) -> dict | None` — the lock, or `None`.
  - `.is_pristine(slug, wt) -> bool` — every locked test exists in `wt` with a matching sha256.
  - `.restore(slug, wt) -> None` — rewrite each locked test's pristine content into `wt` (chmod 0o644 then write).
  - `.remove(slug) -> None` — unlink the lock file (`missing_ok=True`).
- Consumed by: `engineer.py` shims now; `SpecWriter`/`Engineer` later.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coding_locks.py
import hashlib
from leanlab.core.coding.locks import LockStore


def _wt(tmp_path, content):
    wt = tmp_path / "wt"; (wt / "tests").mkdir(parents=True)
    (wt / "tests" / "t.py").write_text(content)
    return wt


def test_write_load_pristine_and_tamper(tmp_path):
    src = "def test_x():\n    assert True\n"
    wt = _wt(tmp_path, src)
    store = LockStore(tmp_path)
    store.write("demo", [{"path": "tests/t.py", "content": src,
                          "sha256": hashlib.sha256(src.encode()).hexdigest()}])
    assert store.load("demo")["tests"][0]["path"] == "tests/t.py"
    assert store.is_pristine("demo", wt) is True
    (wt / "tests" / "t.py").write_text("def test_x():\n    assert False\n")  # tamper
    assert store.is_pristine("demo", wt) is False
    store.restore("demo", wt)                                                # restore pristine
    assert store.is_pristine("demo", wt) is True


def test_load_missing_is_none(tmp_path):
    assert LockStore(tmp_path).load("nope") is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_coding_locks.py -q`
Expected: FAIL — `ModuleNotFoundError: leanlab.core.coding.locks`

- [ ] **Step 3: Implement `LockStore`**

```python
# leanlab/core/coding/locks.py
"""Out-of-worktree store for the LOCKED acceptance tests — the frozen 'done' criteria."""

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
        p = self._path(slug)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"tests": tests}))

    def load(self, slug):
        p = self._path(slug)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None

    def is_pristine(self, slug, wt):
        lock = self.load(slug)
        if lock is None:
            return True
        for it in lock.get("tests", []):
            f = Path(wt) / it["path"]
            if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != it["sha256"]:
                return False
        return True

    def restore(self, slug, wt):
        lock = self.load(slug)
        if lock is None:
            return
        for it in lock.get("tests", []):
            f = Path(wt) / it["path"]
            f.parent.mkdir(parents=True, exist_ok=True)
            if f.exists():
                f.chmod(0o644)
            f.write_text(it["content"])

    def remove(self, slug):
        self._path(slug).unlink(missing_ok=True)
```

- [ ] **Step 4: Delegate the engineer helpers (shims)**

In `engineer.py`, add `from .locks import LockStore` and rewrite the helpers to delegate (note the signature shift — these took `(lock, wt)`; keep them working by re-loading through the store where the current code passes a `lock` dict):

```python
def _load_lock(repo, slug):
    return LockStore(repo).load(slug)

def _is_pristine(lock, wt):
    # lock is the dict already loaded by build_task; check it directly
    import hashlib
    from pathlib import Path
    for it in lock.get("tests", []):
        p = Path(wt) / it["path"]
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != it["sha256"]:
            return False
    return True

def _restore_tests(lock, wt):
    from pathlib import Path
    for it in lock.get("tests", []):
        p = Path(wt) / it["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            p.chmod(0o644)
        p.write_text(it["content"])
```

> Note: `_is_pristine`/`_restore_tests` keep their `(lock, wt)` signature for now (build_task already holds the loaded lock), so no call-site changes. The class is the single source of the logic going forward; `Engineer` will use `LockStore` directly in Increment 5 and these shims are deleted then.

In `spec.py`, replace the inline lock write in `spec_task` with `LockStore(repo).write(slug, locked)`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — 88 + 2 new = 90 passed.

- [ ] **Step 6: Commit**

```bash
git add leanlab/core/coding/locks.py leanlab/core/coding/engineer.py leanlab/core/coding/spec.py tests/test_coding_locks.py
git commit -m "refactor: extract LockStore class (lock + honesty logic)"
```

---

### Task 3: `Git`

**Files:**
- Create: `leanlab/core/coding/git.py`
- Modify: `spec.py` (`_git`, `_is_git_repo`, `_create_worktree`, `_merged_branches`, `clean_worktrees` → delegate), `engineer.py` (`_git`, `_stage`, `_merge` → delegate)
- Test: `tests/test_coding_git.py`

**Interfaces:**
- Produces: `Git()` (stateless adapter over the `git` CLI) with:
  - `.run(repo, *args) -> CompletedProcess` (the current `_git`)
  - `.is_repo(repo) -> bool`
  - `.create_worktree(repo, slug) -> tuple[Path, str]` (worktree path, branch)
  - `.merged_branches(repo) -> set[str]`
  - `.stage(wt) -> None`, `.merge(repo, wt, branch, slug) -> bool`
- Consumed by: `spec.py`/`engineer.py` shims now; `SpecWriter`/`Engineer` later.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coding_git.py
import subprocess
from leanlab.core.coding.git import Git


def _repo(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@e.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    (r / "README").write_text("x")
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "init"], check=True, capture_output=True)
    return r


def test_is_repo_and_create_worktree(tmp_path):
    git = Git()
    r = _repo(tmp_path)
    assert git.is_repo(r) is True
    assert git.is_repo(tmp_path / "nope") is False
    wt, branch = git.create_worktree(r, "demo")
    assert wt.is_dir() and branch == "leanlab/demo"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_coding_git.py -q`
Expected: FAIL — `ModuleNotFoundError: leanlab.core.coding.git`

- [ ] **Step 3: Implement `Git`**

Port the existing bodies verbatim into methods. Move `spec.py`'s `_git`, `_is_git_repo`, `_create_worktree`, `_merged_branches`, and the worktree/branch removal loop of `clean_worktrees`, plus `engineer.py`'s `_stage` and `_merge`, into a `Git` class (replace the leading `repo`/`wt` parameter with a method arg; the class is stateless). Keep `clean_worktrees`'s lock-unlink via `LockStore(repo).remove(slug)`.

```python
# leanlab/core/coding/git.py
"""Thin adapter over the `git` CLI: worktrees, branches, staging, merge."""

from __future__ import annotations

import subprocess
from pathlib import Path


class Git:
    def run(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)

    def is_repo(self, repo):
        return self.run(repo, "rev-parse", "--is-inside-work-tree").returncode == 0

    def create_worktree(self, repo, slug):
        # ... port the body of spec._create_worktree (gitignore + worktree add) ...
        ...

    def merged_branches(self, repo):
        out = self.run(repo, "branch", "--merged").stdout
        return {ln[2:].strip() for ln in out.splitlines() if ln.strip()}

    def stage(self, wt):
        # ... port engineer._stage (git add with the .git/info/exclude carve-outs) ...
        ...

    def merge(self, repo, wt, branch, slug):
        # ... port engineer._merge; returns bool ...
        ...
```

> The implementer copies the exact existing bodies from `spec.py`/`engineer.py` into these methods (they are unchanged logic). Then the module functions become one-line shims: `def _git(repo, *a): return Git().run(repo, *a)`, etc.

- [ ] **Step 4: Delegate the module functions (shims)** — point `spec._git`, `_create_worktree`, `_merged_branches`, and `engineer._git`, `_stage`, `_merge` at a shared `Git()` instance. `clean_worktrees` keeps its signature, using `Git()` + `LockStore`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — 90 + 1 new = 91 passed.

- [ ] **Step 6: Commit**

```bash
git add leanlab/core/coding/git.py leanlab/core/coding/spec.py leanlab/core/coding/engineer.py tests/test_coding_git.py
git commit -m "refactor: extract Git adapter (worktree/branch/merge)"
```

---

### Task 4: `Transcripts`

**Files:**
- Create: `leanlab/core/coding/transcripts.py`
- Modify: `board.py` (`_transcript_dir`, `_parsed_sessions`, `_task_transcript_events`, `_task_usage`, `_SESSIONS_CACHE` → delegate)
- Test: `tests/test_coding_transcripts.py`

**Interfaces:**
- Produces: `Transcripts(repo)` with `.events(slug) -> list[dict]` (all sessions oldest-first, divider markers — the current `_task_transcript_events`) and `.usage(slug) -> dict` (`{"tokens", "cost"}` — the current `_task_usage`). Internal mtime cache preserved.
- Consumed by: `board.py` shims now; `Board` later.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coding_transcripts.py
import os
from leanlab.core.coding.transcripts import Transcripts
from leanlab.core import monitor


def test_usage_and_events_merge_all_sessions(tmp_path, monkeypatch):
    d = tmp_path / "tx"; d.mkdir()
    (d / "a.jsonl").write_text("x"); (d / "b.jsonl").write_text("x")
    os.utime(d / "a.jsonl", (1, 1)); os.utime(d / "b.jsonl", (2, 2))
    canned = {"a.jsonl": [{"kind": "text", "text": "one", "in_tok": 10, "out_tok": 5}],
              "b.jsonl": [{"kind": "text", "text": "two", "in_tok": 20, "out_tok": 7}]}
    t = Transcripts(tmp_path)
    monkeypatch.setattr(t, "_dir", lambda slug: d)
    monkeypatch.setattr(monitor, "parse_session", lambda p: ({}, canned[p.name]))
    evs = t.events("demo")
    assert [e["kind"] for e in evs] == ["divider", "text", "divider", "text"]
    assert t.usage("demo") == {"tokens": 42, "cost": 0.0}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_coding_transcripts.py -q`
Expected: FAIL — `ModuleNotFoundError: leanlab.core.coding.transcripts`

- [ ] **Step 3: Implement `Transcripts`**

Port `board.py`'s `_transcript_dir` → `Transcripts._dir(slug)`, `_parsed_sessions` → `._parsed(dir)` (instance-level cache dict replaces the module `_SESSIONS_CACHE`), `_task_transcript_events` → `.events(slug)`, `_task_usage` → `.usage(slug)`. Logic is unchanged.

- [ ] **Step 4: Delegate (shims)** — in `board.py`, build one `Transcripts(repo)` per state call and have `_task_transcript_events`/`_task_usage`/`_transcript_dir` delegate. (`coding_state`/`task_detail` will use the instance directly in Increment 6.)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — 91 + 1 new = 92 passed.

- [ ] **Step 6: Commit**

```bash
git add leanlab/core/coding/transcripts.py leanlab/core/coding/board.py tests/test_coding_transcripts.py
git commit -m "refactor: extract Transcripts class (session parse + usage cache)"
```

---

### Task 5: Reflect in archik

**Files:** none in code; staged via the CLI.

- [ ] **Step 1: Stage the new collaborator nodes**

Reconstruct the full document from `npx archik q list --json` + `q edges --json` (copy every node/edge verbatim), then add four nodes parented to `coding`, each with `stereotype: entity` (EventLog, LockStore, Transcripts) or the `Git` node `stereotype: control` + kind `adapter`, with real `sourcePath`s:

```
- id: event-log     kind: module  stereotype: entity   sourcePath: leanlab/core/coding/events.py
- id: lock-store    kind: module  stereotype: entity   sourcePath: leanlab/core/coding/locks.py
- id: transcripts   kind: module  stereotype: entity   sourcePath: leanlab/core/coding/transcripts.py
- id: git           kind: adapter stereotype: control  sourcePath: leanlab/core/coding/git.py
```

Pipe to `npx archik suggest set --note "increment 1: shared coding-lab entities"` and accept.

- [ ] **Step 2: Verify**

Run: `npx archik validate` (clean), `npx archik drift` (clean — the four sourcePaths now exist), `npx archik trace` (still 11 full).

- [ ] **Step 3: Commit**

```bash
git add .archik/main.archik.yaml
git commit -m "archik: model the shared coding-lab entities (increment 1)"
```

---

## Self-Review

- **Spec coverage:** This plan implements spec Increment 1 (EventLog, LockStore, Git, Transcripts) + its archik reflection. Increments 2–8 are separate plans.
- **Placeholders:** `Git.create_worktree/stage/merge` and `Transcripts` bodies say "port the exact existing body" rather than re-pasting ~60 lines that already exist verbatim in `spec.py`/`engineer.py`/`board.py` — the source is named precisely and the logic is unchanged, so this is a copy, not a design gap.
- **Type consistency:** `EventLog.log/read`, `LockStore.write/load/is_pristine/restore/remove`, `Git.run/is_repo/create_worktree/merged_branches/stage/merge`, `Transcripts.events/usage` are used consistently across tasks and match the spec's class map.
- **Behavior:** every task ends with the full suite green via shims; no behavior change.
