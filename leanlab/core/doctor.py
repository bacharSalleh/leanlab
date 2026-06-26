"""Preflight 'doctor' — verify a lab is wired correctly before running.

The expensive bugs are silent wiring mismatches: lab.json names metric "FPS" but
evaluation.py prints "score"; or the command passes --experiment but the script
reads a positional arg. `check_lab` catches those *cheaply* by probing the
evaluator with a sentinel missing file — the evaluator should fail fast on the
missing file (before any render / Claude call), and from its output we can verify
both the argument wiring and the metric key.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"
_SENTINEL = "experiments/__leanlab_preflight__.py"


@dataclass
class Check:
    name: str
    status: str   # ok | warn | fail
    message: str


def _run(cmd_template, lab_dir, file_rel):
    parts = [p.replace("{file}", file_rel) for p in shlex.split(cmd_template)]
    try:
        proc = subprocess.run(parts, cwd=lab_dir, capture_output=True, text=True, timeout=120)
    except Exception as e:  # noqa: BLE001
        return None, f"could not run `{cmd_template}`: {e}"
    return proc, (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()


def _last_json(out):
    for line in reversed(out.splitlines()):
        try:
            o = json.loads(line.strip())
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(o, dict):
            return o
    return None


def _probe_args(name, cmd_template, lab_dir, checks):
    """A command should receive the file path, not the flag. Returns the probe output."""
    proc, out = _run(cmd_template, lab_dir, _SENTINEL)
    if proc is None:
        checks.append(Check(name, FAIL, out))
        return None
    if "--experiment" in out and _SENTINEL not in out and "__leanlab_preflight__" not in out:
        checks.append(Check(name, FAIL, "the script is not reading the file argument (it got the "
                                        "flag instead) — fix its arg parsing or the command in lab.json"))
    else:
        checks.append(Check(name, OK, "the file argument reaches the script"))
    return out


def check_lab(lab_dir) -> list[Check]:
    lab = Path(lab_dir)
    checks: list[Check] = []

    cfgpath = lab / "lab.json"
    if not cfgpath.exists():
        return [Check("lab.json", FAIL, "missing — is this a lab folder?")]
    try:
        cfg = json.loads(cfgpath.read_text())
    except (ValueError, json.JSONDecodeError) as e:
        return [Check("lab.json", FAIL, f"invalid JSON: {e}")]

    obj = cfg.get("objective") or {}
    metric, direction = obj.get("metric"), obj.get("direction")
    missing = [k for k in ("eval_cmd", "validate_cmd", "experiments_dir", "results_file")
               if not cfg.get(k)]
    if missing or not metric or not direction:
        checks.append(Check("lab.json", FAIL,
                            f"missing {missing or ''} objective.metric/direction={metric}/{direction}"))
    else:
        checks.append(Check("lab.json", OK, f"objective {direction} {metric}"))

    for f in ("task.md", "evaluation.py", "validate.py"):
        checks.append(Check(f, OK if (lab / f).exists() else FAIL,
                            "present" if (lab / f).exists() else "missing"))
    exp = lab / cfg.get("experiments_dir", "experiments")
    checks.append(Check("experiments/", OK if exp.is_dir() else FAIL,
                        "present" if exp.is_dir() else "missing"))

    checks.append(Check("claude CLI", OK if shutil.which("claude") else FAIL,
                        "on PATH" if shutil.which("claude")
                        else "not found — workers/director/critic/judge cannot run"))

    try:
        base = resources.files("leanlab") / "templates" / "agents"
        have = all((base / s).is_file() for s in ("CLAUDE.md", "director.md", "critic.md"))
        checks.append(Check("agent specs", OK if have else FAIL,
                            "resolved from package" if have else "missing from package"))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("agent specs", FAIL, f"cannot resolve: {e}"))

    # Actually build the worker/director/critic prompts for this lab — the real wiring test
    # (injects the specs and reads the lab's memory + Director/Critic notes).
    try:
        from .loop import build_worker_prompt, build_director_prompt, build_critic_prompt
        build_worker_prompt(lab, cfg)
        build_director_prompt()
        build_critic_prompt()
        checks.append(Check("agent prompts", OK, "worker / director / critic prompts build"))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("agent prompts", FAIL, f"cannot build agent prompts: {e}"))

    for f in ("Director_Notes.md", "Critic_Feedback.md"):
        checks.append(Check(f, OK if (lab / f).exists() else WARN,
                            "present" if (lab / f).exists() else "missing (created on first review)"))

    # The wiring probes — cheap, run the eval/validate on a missing sentinel file.
    if (lab / "evaluation.py").exists() and cfg.get("eval_cmd"):
        out = _probe_args("eval args", cfg["eval_cmd"], lab, checks)
        if out is not None and metric:
            verdict = _last_json(out)
            if verdict is None:
                checks.append(Check("eval metric", WARN,
                                    "evaluator emitted no JSON for a missing file — can't verify the metric key"))
            elif metric not in verdict:
                checks.append(Check("eval metric", FAIL,
                                    f'evaluator output has no "{metric}" key (lab.json objective); '
                                    f"it printed keys {list(verdict)[:6]}"))
            else:
                checks.append(Check("eval metric", OK, f'emits the objective key "{metric}"'))
    if (lab / "validate.py").exists() and cfg.get("validate_cmd"):
        _probe_args("validate args", cfg["validate_cmd"], lab, checks)

    return checks


def summarize(checks):
    return {s: sum(c.status == s for c in checks) for s in (OK, WARN, FAIL)}


def ok(checks):
    return not any(c.status == FAIL for c in checks)


# --- reporting --------------------------------------------------------------
_SYMBOL = {OK: "[green]✓[/green]", WARN: "[yellow]⚠[/yellow]", FAIL: "[red]✗[/red]"}


class RichReport:
    """Default terminal reporter for check/fix."""

    def __init__(self):
        from rich.console import Console
        self.console = Console()

    def report(self, checks):
        for c in checks:
            self.console.print(f"{_SYMBOL.get(c.status, '?')} [bold]{c.name}[/bold] — {c.message}")
        s = summarize(checks)
        self.console.print(f"\n[bold]{s[OK]} ok · {s[WARN]} warn · {s[FAIL]} fail[/bold]")

    def status(self, message):
        return self.console.status(f"[bold cyan]{message}", spinner="dots")

    def note(self, message):
        self.console.print(message)


# --- automated fixing -------------------------------------------------------
def _fix_prompt(fails):
    lines = "\n".join(f"- {c.name}: {c.message}" for c in fails)
    return (
        "You are fixing a leanlab lab in the current directory. `leanlab check` found these "
        f"wiring problems:\n\n{lines}\n\n"
        "Fix them by editing the lab's files so they are mutually consistent:\n"
        "- evaluation.py and validate.py MUST parse their CLI args to match lab.json's eval_cmd / "
        "validate_cmd (which pass `--experiment <path>`) — use argparse, NOT a positional arg.\n"
        "- evaluation.py MUST print ONE line of JSON whose keys include exactly the objective "
        "metric named in lab.json (objective.metric) — not a generic 'score' unless that IS the "
        "metric.\n"
        "- Create any missing files the checks listed.\n"
        "Make the edits now with your tools, then stop. Do NOT run experiments."
    )


def fix_lab(lab_dir, *, runner=None, ui=None, rounds=3) -> bool:
    """Run checks; if any fail, have Claude edit the lab to fix them, then re-check. Loop."""
    lab = Path(lab_dir)
    ui = ui or RichReport()
    from .loop import make_runner
    runner = runner or make_runner(lab)

    for attempt in range(1, rounds + 1):
        checks = check_lab(lab)
        fails = [c for c in checks if c.status == FAIL]
        ui.report(checks)
        if not fails:
            ui.note("\n[green]✓ all checks pass — nothing to fix.[/green]")
            return True
        ui.note(f"\n[yellow]Fixing {len(fails)} issue(s) with Claude (round {attempt}/{rounds})…[/yellow]")
        # evaluation.py is often locked read-only — unlock so the agent can edit it.
        ev = lab / "evaluation.py"
        relock = ev.exists() and not (ev.stat().st_mode & 0o200)
        if relock:
            ev.chmod(0o644)
        try:
            with ui.status("Claude is editing the lab to fix the issues…"):
                runner.run_plain(_fix_prompt(fails))
        finally:
            if relock and ev.exists():
                ev.chmod(0o444)

    checks = check_lab(lab)
    ui.report(checks)
    return ok(checks)
