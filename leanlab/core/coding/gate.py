"""The gate — the deterministic checks a code change must pass.

Objective and binary: every configured command must exit 0 (tests incl. the locked
acceptance tests, plus optional lint / typecheck). Returns a structured GateResult.
The LLM quality score (the reviewer) is a separate, later concern.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_GATE = [{"name": "tests", "cmd": "pytest -q"}]


@dataclass
class GateCheck:
    name: str
    ok: bool
    code: int
    output: str


@dataclass
class GateResult:
    passed: bool
    checks: list

    def failures(self):
        return [c for c in self.checks if not c.ok]


def run_gate(worktree, gate_cmds=None, *, timeout=600) -> GateResult:
    """Run each gate command in the worktree; the change passes only if all exit 0."""
    wt = Path(worktree)
    checks = []
    for step in (gate_cmds or DEFAULT_GATE):
        name, cmd = step["name"], step["cmd"]
        try:
            proc = subprocess.run(shlex.split(cmd), cwd=wt, capture_output=True,
                                  text=True, timeout=timeout)
            out = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
            checks.append(GateCheck(name, proc.returncode == 0, proc.returncode, out))
        except Exception as e:  # noqa: BLE001 — couldn't even run it
            checks.append(GateCheck(name, False, -1, f"could not run `{cmd}`: {e}"))
    return GateResult(passed=all(c.ok for c in checks), checks=checks)


def report(result: GateResult, console=None):
    """Print a rich pass/fail report."""
    if console is None:
        from rich.console import Console
        console = Console()
    for c in result.checks:
        mark = "[green]✓[/green]" if c.ok else "[red]✗[/red]"
        console.print(f"{mark} [bold]{c.name}[/bold] (exit {c.code})")
        if not c.ok:
            tail = "\n".join(c.output.splitlines()[-12:])
            console.print(f"[dim]{tail}[/dim]")
    verdict = "[green]GATE PASSED[/green]" if result.passed else "[red]GATE FAILED[/red]"
    console.print(f"\n[bold]{verdict}[/bold]")
