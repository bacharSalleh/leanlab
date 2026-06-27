"""The coding board — a dashboard for a coding lab's tasks, status, traces, and PLAYBOOK.

Overview (`/`) lists task cards from `.leanlab/worktrees/*`, `.leanlab/coding-results.jsonl`,
and `.leanlab/PLAYBOOK.md`. A task detail (`/?task=<slug>`) shows the build TIMELINE (from the
structured event log written by `build`) and the live agent CHAT (parsed from the worktree's
Claude transcripts). `Board` builds the state; the renderers are pure and testable.
"""

from __future__ import annotations

import json
import mimetypes
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .events import EventLog
from .playbook import Playbook
from .transcripts import Transcripts

_STATUS = {"merged": "#3fb950", "failed": "#f85149", "spec'd": "#d29922", "building": "#58a6ff"}


# --- agent chat (transcripts) ----------------------------------------------
# One Transcripts per repo so its parse cache survives across SSE polls.
_TRANSCRIPTS = {}


def _transcripts(repo):
    key = str(Path(repo).resolve())
    if key not in _TRANSCRIPTS:
        _TRANSCRIPTS[key] = Transcripts(repo)
    return _TRANSCRIPTS[key]


# --- state (the Board) ------------------------------------------------------
class Board:
    """Builds the coding lab's dashboard state from worktrees, results, events, and transcripts."""

    def __init__(self, repo):
        self._repo = Path(repo)
        self._events = EventLog(repo)
        self._transcripts = _transcripts(repo)
        self._playbook = Playbook(repo)

    def _results(self):
        p = self._repo / ".leanlab" / "coding-results.jsonl"
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

    @staticmethod
    def _spec_summary(d):
        spec = (d / "SPEC.md").read_text() if (d / "SPEC.md").exists() else ""
        lines = [ln.strip() for ln in spec.splitlines() if ln.strip()]
        return next((ln for ln in lines if not ln.startswith("#")), lines[0] if lines else "(no spec)")

    def _slugs(self):
        """Live worktrees PLUS finished tasks recorded in results/events (worktrees get cleaned)."""
        wtroot = self._repo / ".leanlab" / "worktrees"
        live = [d.name for d in sorted(wtroot.iterdir()) if d.is_dir()] if wtroot.is_dir() else []
        durable = [*self._results()] + [f.stem for f in sorted((self._repo / ".leanlab" / "events").glob("*.jsonl"))]
        seen, archived = set(live), []
        for slug in durable:
            if slug not in seen:
                seen.add(slug)
                archived.append(slug)
        return live, archived

    def _status(self, slug, by_slug=None):
        """A task's status: the result row wins; otherwise inferred from the event log."""
        by_slug = self._results() if by_slug is None else by_slug
        r = by_slug.get(slug)
        if r:
            return "merged" if r.get("merged") else "failed"
        evs = self._events.read(slug)
        if any(e.get("event") == "merged" and e.get("merged") for e in evs):
            return "merged"
        if any(e.get("event") == "gaveup" for e in evs):
            return "failed"
        return "spec'd"

    def state(self):
        by_slug = self._results()
        wtroot = self._repo / ".leanlab" / "worktrees"
        live, archived = self._slugs()
        tasks = []
        for slug in live + archived:
            d = wtroot / slug
            is_live = d.is_dir()
            r = by_slug.get(slug)
            status = self._status(slug, by_slug)
            attempts = (r or {}).get("attempts")
            if attempts is None:                    # recover the count from the event log
                n = sum(1 for e in self._events.read(slug) if e.get("event") == "attempt")
                attempts = n or None
            spec = self._spec_summary(d) if is_live else (
                "merged — worktree cleaned" if status == "merged" else "worktree cleaned")
            u = self._transcripts.usage(slug)
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
        return {"tasks": tasks, "playbook": self._playbook.read(), "totals": totals}

    def task(self, slug):
        wt = self._repo / ".leanlab" / "worktrees" / slug
        u = self._transcripts.usage(slug)
        return {"slug": slug, "exists": wt.is_dir(), "status": self._status(slug),
                "spec": self._spec_summary(wt) if wt.is_dir() else "",
                "timeline": self._events.read(slug), "stream": self._transcripts.events(slug),
                "cost": u["cost"], "tokens": u["tokens"]}

    def overview(self):
        return {"lab": self._repo.resolve().name, **self.state()}


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
    board = Board(repo)                          # one Board for the server (shares the transcript cache)

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
                    st = json.dumps(board.overview())
                    if st != last_state:
                        self._sse("state", st)
                        last_state = st
                    if slug:
                        td = json.dumps(board.task(slug))
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
                    self._send(json.dumps(board.overview()))
                    return
                if route.path == "/api/task":
                    self._send(json.dumps(board.task(q.get("task", [""])[0])))
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
