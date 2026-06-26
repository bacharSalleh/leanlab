"""ClaudeAgent — an AgentTransport backed by the Claude Code CLI (claude -p).

One concrete backend. Hermes / custom backends would be sibling AgentTransports;
the loop, which depends only on AgentRunner, would not change.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .port import AgentTransport


class ClaudeAgent(AgentTransport):
    """Runs one agent turn via `claude -p --output-format json`, in a lab's cwd."""

    def __init__(self, cwd, *, max_turns: int = 250, permission_mode: str = "bypassPermissions"):
        self._cwd = Path(cwd)
        self._max_turns = max_turns
        self._permission_mode = permission_mode

    def send(self, prompt: str, *, session: str | None = None) -> tuple[str | None, str]:
        cmd = ["claude", "-p", prompt,
               "--permission-mode", self._permission_mode,
               "--max-turns", str(self._max_turns),
               "--output-format", "json"]
        if session:
            cmd += ["--resume", session]
        proc = subprocess.run(cmd, cwd=self._cwd, capture_output=True, text=True)
        if proc.returncode != 0 and not proc.stdout.strip():
            raise RuntimeError(proc.stderr.strip() or "claude CLI failed")
        try:
            env = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None, proc.stdout  # let the protocol treat it as malformed
        return env.get("session_id"), env.get("result", "")
