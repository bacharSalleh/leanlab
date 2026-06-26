"""The coding board — a dashboard for a coding lab's tasks, status, traces, and PLAYBOOK.

Overview (`/`) lists task cards from `.leanlab/worktrees/*`, `.leanlab/coding-results.jsonl`,
and `.leanlab/PLAYBOOK.md`. A task detail (`/?task=<slug>`) shows the build TIMELINE (from the
structured event log written by `build`) and the live agent CHAT (parsed from the worktree's
Claude transcripts). `coding_state` / `task_detail` / the renderers are pure and testable.
"""

from __future__ import annotations

import json
import mimetypes
import sys
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .playbook import read_playbook

_STATUS = {"merged": "#3fb950", "failed": "#f85149", "spec'd": "#d29922", "building": "#58a6ff"}


# --- structured event log (the timeline) ------------------------------------
def _events_path(repo, slug):
    return Path(repo) / ".leanlab" / "events" / f"{slug}.jsonl"


def log_event(repo, slug, rec):
    """Append one build event for a task (used by spec/build to feed the timeline)."""
    p = _events_path(repo, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({**rec, "ts": datetime.now(timezone.utc).isoformat()}) + "\n")


def read_events(repo, slug):
    p = _events_path(repo, slug)
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


# --- agent chat (transcripts) ----------------------------------------------
def _transcript_dir(repo, slug):
    """The Claude transcript dir for a task's worktree, or None."""
    wt = Path(repo) / ".leanlab" / "worktrees" / slug
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return None
    d = base / str(wt.resolve()).replace("/", "-")
    if d.is_dir():
        return d
    matches = sorted(base.glob(f"*worktrees-{slug}"))   # specific tail — avoids other projects
    return matches[-1] if matches else None


_SESSIONS_CACHE = {}


def _parsed_sessions(d):
    """[(path, events)] for every session in `d`, oldest first — parsed ONCE and cached by
    the dir's (name, mtime) signature. The SSE loop polls task detail every second; without
    this each poll would re-parse every transcript file."""
    sessions = sorted(d.glob("*.jsonl"))
    sig = tuple((p.name, p.stat().st_mtime) for p in sessions)
    cached = _SESSIONS_CACHE.get(str(d))
    if cached and cached[0] == sig:
        return cached[1]
    from ..monitor import parse_session            # reuse the metric dashboard's parser
    parsed = [(p, parse_session(p)[1])
              for p in sorted(sessions, key=lambda p: p.stat().st_mtime)]
    _SESSIONS_CACHE[str(d)] = (sig, parsed)
    return parsed


def _task_transcript_events(repo, slug):
    """Every agent session's events for a task, oldest first — one session per claude call,
    so all build attempts and reviews show, not just the latest. A `divider` event marks
    each session boundary."""
    d = _transcript_dir(repo, slug)
    if not d:
        return []
    runs = [events for _p, events in _parsed_sessions(d) if events]
    out = []
    for i, events in enumerate(runs, 1):
        tok = sum((e.get("in_tok") or 0) + (e.get("out_tok") or 0) for e in events)
        out.append({"kind": "divider", "text": f"session {i}/{len(runs)}", "tokens": tok})
        out.extend(events)
    return out


def _task_usage(repo, slug):
    """Total tokens + cost across ALL agent sessions for a task."""
    d = _transcript_dir(repo, slug)
    if not d:
        return {"tokens": 0, "cost": 0.0}
    tokens = cost = 0
    for _p, events in _parsed_sessions(d):
        for e in events:
            tokens += (e.get("in_tok") or 0) + (e.get("out_tok") or 0)
            cost += e.get("cost") or 0
    return {"tokens": tokens, "cost": round(cost, 4)}


# --- state builders ---------------------------------------------------------
def _results(repo):
    p = Path(repo) / ".leanlab" / "coding-results.jsonl"
    latest = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    latest[r["slug"]] = r
                except (ValueError, KeyError):
                    pass
    return latest


def _spec_summary(d):
    spec = (d / "SPEC.md").read_text() if (d / "SPEC.md").exists() else ""
    lines = [ln.strip() for ln in spec.splitlines() if ln.strip()]
    return next((ln for ln in lines if not ln.startswith("#")), lines[0] if lines else "(no spec)")


def _task_slugs(repo):
    """Every task we know about — live worktrees PLUS finished ones recorded in results/events.

    A task's worktree is removed once it merges and is cleaned, so the worktree dir alone
    forgets completed work. Union the durable records so the board keeps the full history.
    """
    repo = Path(repo)
    wtroot = repo / ".leanlab" / "worktrees"
    live = [d.name for d in sorted(wtroot.iterdir()) if d.is_dir()] if wtroot.is_dir() else []
    durable = [*_results(repo)] + [f.stem for f in sorted((repo / ".leanlab" / "events").glob("*.jsonl"))]
    seen = set(live)
    archived = []
    for slug in durable:
        if slug not in seen:
            seen.add(slug)
            archived.append(slug)
    return live, archived


def _task_status(repo, slug, by_slug=None):
    """A task's status: the result row wins; otherwise inferred from the event log."""
    by_slug = _results(repo) if by_slug is None else by_slug
    r = by_slug.get(slug)
    if r:
        return "merged" if r.get("merged") else "failed"
    evs = read_events(repo, slug)
    if any(e.get("event") == "merged" and e.get("merged") for e in evs):
        return "merged"
    if any(e.get("event") == "gaveup" for e in evs):
        return "failed"
    return "spec'd"


def coding_state(repo) -> dict:
    repo = Path(repo)
    by_slug = _results(repo)
    wtroot = repo / ".leanlab" / "worktrees"
    live, archived = _task_slugs(repo)
    tasks = []
    for slug in live + archived:
        d = wtroot / slug
        is_live = d.is_dir()
        r = by_slug.get(slug)
        status = _task_status(repo, slug, by_slug)
        attempts = (r or {}).get("attempts")
        if attempts is None:                    # recover the count from the event log
            n = sum(1 for e in read_events(repo, slug) if e.get("event") == "attempt")
            attempts = n or None
        if is_live:
            spec = _spec_summary(d)
        else:
            spec = "merged — worktree cleaned" if status == "merged" else "worktree cleaned"
        u = _task_usage(repo, slug)
        tasks.append({"slug": slug, "status": status, "branch": f"leanlab/{slug}",
                      "attempts": attempts, "spec": spec, "archived": not is_live,
                      "tokens": u["tokens"], "cost": u["cost"]})
    merged = sum(t["status"] == "merged" for t in tasks)
    failed = sum(t["status"] == "failed" for t in tasks)
    decided = merged + failed
    totals = {"tasks": len(tasks), "merged": merged, "failed": failed,
              "open": sum(t["status"] == "spec'd" for t in tasks),
              "tokens": sum(t["tokens"] for t in tasks),
              "cost": round(sum(t["cost"] for t in tasks), 4),
              "success": round(100 * merged / decided) if decided else None}
    return {"tasks": tasks, "playbook": read_playbook(repo), "totals": totals}


def task_detail(repo, slug) -> dict:
    repo = Path(repo)
    wt = repo / ".leanlab" / "worktrees" / slug
    usage = _task_usage(repo, slug)                  # tokens + cost across all the task's sessions
    return {"slug": slug, "exists": wt.is_dir(), "status": _task_status(repo, slug),
            "spec": _spec_summary(wt) if wt.is_dir() else "",
            "timeline": read_events(repo, slug), "stream": _task_transcript_events(repo, slug),
            "cost": usage["cost"], "tokens": usage["tokens"]}



# --- live SPA (SSE) ---------------------------------------------------------
def overview_state(repo) -> dict:
    return {"lab": Path(repo).resolve().name, **coding_state(repo)}


_DIST = Path(__file__).resolve().parent / "board_dist"   # built React app (see frontend/)

_NOT_BUILT_HTML = (
    "<!doctype html><meta charset='utf-8'>"
    "<body style='font:14px system-ui;background:#0a0a0a;color:#e6edf3;padding:40px'>"
    "<h2>Board UI not built</h2>"
    "<p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code> to compile it.</p>"
    "</body>"
)


def _asset(rel):
    """Resolve a request path to a file inside the built board, rejecting path traversal."""
    rel = (rel or "").lstrip("/") or "index.html"
    f = (_DIST / rel).resolve()
    if _DIST.resolve() not in f.parents:
        return None
    return f if f.is_file() else None


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if not isinstance(exc, (ConnectionResetError, BrokenPipeError, TimeoutError)):
            super().handle_error(request, client_address)


def serve_board(repo, port=8766, open_browser=True):
    repo = Path(repo).resolve()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError, TimeoutError):
                pass

        def _send(self, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _sse(self, event, payload):
            self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
            self.wfile.flush()

        def stream(self, slug):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            last_state = last_task = None
            last_ping = 0.0
            try:
                while True:
                    st = json.dumps(overview_state(repo))
                    if st != last_state:
                        self._sse("state", st)
                        last_state = st
                    if slug:
                        td = json.dumps(task_detail(repo, slug))
                        if td != last_task:
                            self._sse("task", td)
                            last_task = td
                    if time.time() - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = time.time()
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def do_GET(self):
            route = urlparse(self.path)
            q = parse_qs(route.query)
            try:
                if route.path == "/api/stream":
                    self.stream(q.get("task", [""])[0])
                    return
                if route.path == "/api/state":
                    self._send(json.dumps(overview_state(repo)))
                    return
                if route.path == "/api/task":
                    self._send(json.dumps(task_detail(repo, q.get("task", [""])[0])))
                    return
                # static: the built React app. Unknown paths fall back to index.html (SPA).
                f = _asset(route.path) or _asset("index.html")
                if f is None:
                    self._send(_NOT_BUILT_HTML, "text/html; charset=utf-8")
                    return
                ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype == "image/svg+xml":
                    ctype += "; charset=utf-8"
                self._send(f.read_bytes(), ctype)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *a):
            pass

    url = f"http://127.0.0.1:{port}"
    print(f"leanlab coding board: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        _QuietServer(("127.0.0.1", port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
