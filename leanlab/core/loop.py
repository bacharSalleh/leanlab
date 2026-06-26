"""leanlab — the generic experiment loop.

A LAB is a folder with:
  - task.md            the goal + the experiment contract (what to write)
  - lab.json           machine config: objective, commands, cadences
  - evaluation.py      the FROZEN judge — prints ONE line of JSON metrics
  - validate.py        a structural check the experimenter runs (no score)
  - experiments/       where the Worker writes one Experiment file per loop
  - results.jsonl      the book: one JSON record per experiment
  - CLAUDE.md / director.md / critic.md   the agent specs

One LOOP = one experiment:
  1. Build the Worker prompt: task + memory (best experiments) + Director notes
     + Critic feedback.
  2. Launch the Worker (a Claude session). It writes ONE Experiment file,
     validates it, and returns JSON: {experiment_file, valid, notes}.
  3. Run the lab's evaluation.py on that file → parse the JSON metrics.
  4. If it errors, resume the same Worker session to fix it (up to max_fix_calls).
  5. Append one record to results.jsonl.
  6. Every critic_every / director_every loops, wake the Critic / Director.

The objective (e.g. minimize rmse, or maximize pnl) is read from lab.json, so the
same loop drives any kind of lab.

Run:
    uv run python core/loop.py --lab labs/house-prices --n 5
    uv run python core/loop.py --lab labs/house-prices --dry-run
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from rich.console import Console

from .agents import ClaudeAgent, StructuredRunner

CORE = Path(__file__).resolve().parent
console = Console()

# Runaway brake + memory size.
TURNS_PER_RUN = 250
MEMORY_TOP_N = 5
FULL_PERMISSION_MODE = "bypassPermissions"


# --- lab config -------------------------------------------------------------
def load_lab(lab_dir):
    cfg = json.loads((lab_dir / "lab.json").read_text())
    cfg.setdefault("experiments_dir", "experiments")
    cfg.setdefault("results_file", "results.jsonl")
    cfg.setdefault("director_every", 5)
    cfg.setdefault("critic_every", 5)
    cfg.setdefault("max_fix_calls", 3)
    obj = cfg["objective"]
    obj.setdefault("direction", "max")
    return cfg


def metric_name(cfg):
    return cfg["objective"]["metric"]


def direction(cfg):
    return cfg["objective"]["direction"]


# --- results.jsonl ----------------------------------------------------------
def read_results(lab_dir, cfg):
    path = lab_dir / cfg["results_file"]
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def append_result(lab_dir, cfg, record):
    path = lab_dir / cfg["results_file"]
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _metric_val(rec, metric):
    try:
        return float(rec.get(metric))
    except (TypeError, ValueError):
        return None


def best_value(rows, cfg):
    metric, d = metric_name(cfg), direction(cfg)
    vals = [v for v in (_metric_val(r, metric) for r in rows) if v is not None]
    if not vals:
        return None
    return min(vals) if d == "min" else max(vals)


def is_better(value, best, d):
    if best is None:
        return True
    return value < best if d == "min" else value > best


def build_memory(rows, cfg):
    metric, d = metric_name(cfg), direction(cfg)
    scored = [r for r in rows if _metric_val(r, metric) is not None]
    if not scored:
        return "MEMORY: no experiments scored yet. You are the first."
    scored.sort(key=lambda r: _metric_val(r, metric), reverse=(d == "max"))
    top = scored[:MEMORY_TOP_N]
    lines = [f"MEMORY — best experiments so far (objective: {d} {metric}; "
             f"do not repeat these):"]
    for r in top:
        extras = " ".join(f"{k}={v}" for k, v in r.items()
                          if k not in ("tag", "experiment_file", "best_so_far", "notes", "ts"))
        lines.append(f"- {r.get('experiment_file','?')} :: {extras} :: {r.get('notes','')}")
    return "\n".join(lines)


# --- injected advisor files -------------------------------------------------
def _inject(lab_dir, filename, header):
    path = lab_dir / filename
    if not path.exists():
        return ""
    text = path.read_text().strip()
    return f"{header}\n{text}" if text else ""


def build_directions(lab_dir):
    return _inject(lab_dir, "Director_Notes.md",
                   "DIRECTOR'S GUIDANCE (your chief scientist — follow it):")


def build_critique(lab_dir):
    return _inject(lab_dir, "Critic_Feedback.md",
                   "THE TEAM OF CRITICS SAID (fix these flaws — do not repeat them):")


# --- prompts ----------------------------------------------------------------
# The fixed agent specs live in the leanlab package (not the user's lab) and are
# injected into each prompt at runtime. Each prompt's FIRST line names the role so
# the dashboard can identify the session.
def _spec(name):
    return (resources.files("leanlab") / "templates" / "agents" / name).read_text().strip()


WORKER_INTRO = ("You are the WORKER (experimenter) on this lab. Read task.md in this lab "
                "and the spec below, then follow them.")
WORKER_ACTION = (
    "Do EXACTLY ONE experiment: invent one new idea and write it as ONE new file in the "
    "experiments folder (a new file, do not overwrite sample.py). Give it a one-line "
    "docstring. Validate it with the lab's validate command until it prints VALID. Do NOT "
    "run or read evaluation.py, and do NOT edit results.jsonl. Be a proactive, true "
    "researcher: research the web, use any method, install any library you need (uv add). "
    "Your final message must be ONLY this JSON object: "
    '{"experiment_file": "experiments/<file>.py", "valid": true, "notes": "one line"}'
)
DIRECTOR_INTRO = ("You are the DIRECTOR (chief scientist) of this lab. Read task.md in this "
                  "lab and the spec below, then follow them.")
DIRECTOR_ACTION = (
    "Study results.jsonl and the experiment files, then rewrite Director_Notes.md with "
    "sharp, concrete, ambitious guidance for the next experiments. Write ONLY that one "
    "file, then stop."
)
CRITIC_INTRO = ("You are the CRITIC (hypercritical red-team) of this lab. Read task.md in "
                "this lab and the spec below, then follow it.")
CRITIC_ACTION = (
    "Review the newest experiments against results.jsonl, hunt for every flaw (overfitting, "
    "leakage, fragility, fake novelty), and rewrite Critic_Feedback.md with blunt, specific "
    "criticism. Write ONLY that one file, then stop."
)


def build_director_prompt():
    return "\n\n".join([DIRECTOR_INTRO, _spec("director.md"), DIRECTOR_ACTION])


def build_critic_prompt():
    return "\n\n".join([CRITIC_INTRO, _spec("critic.md"), CRITIC_ACTION])


# --- launching agents -------------------------------------------------------
def make_runner(lab_dir):
    """The default AgentRunner: a Claude transport wrapped in the retry protocol.

    The loop depends only on the AgentRunner abstraction — swap this factory to
    plug in a Hermes or custom backend.
    """
    return StructuredRunner(
        ClaudeAgent(lab_dir, max_turns=TURNS_PER_RUN, permission_mode=FULL_PERMISSION_MODE)
    )


# --- evaluation -------------------------------------------------------------
def run_cmd_template(template, lab_dir, file_rel):
    parts = [p.replace("{file}", file_rel) for p in shlex.split(template)]
    return subprocess.run(parts, cwd=lab_dir, capture_output=True, text=True)


def evaluate(lab_dir, cfg, file_rel):
    """Run the lab's eval_cmd. Returns (metrics_dict_or_None, raw_output)."""
    proc = run_cmd_template(cfg["eval_cmd"], lab_dir, file_rel)
    out = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
    # The judge prints ONE line of JSON metrics; take the last JSON object.
    for line in reversed(out.splitlines()):
        line = line.strip()
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj, out
    return None, out


# --- experiment-file resolution ---------------------------------------------
def experiment_files(lab_dir, cfg):
    d = lab_dir / cfg["experiments_dir"]
    return {p for p in d.glob("*.py") if p.name != "sample.py"}


def resolve_experiment(lab_dir, cfg, report, new_files):
    if report and report.get("experiment_file"):
        cand = (lab_dir / report["experiment_file"]).resolve()
        if cand.exists():
            return cand
    return sorted(new_files)[-1] if new_files else None


# --- the loop ---------------------------------------------------------------
def build_worker_prompt(lab_dir, cfg):
    rows = read_results(lab_dir, cfg)
    parts = [WORKER_INTRO, _spec("CLAUDE.md"), WORKER_ACTION, build_memory(rows, cfg)]
    for extra in (build_directions(lab_dir), build_critique(lab_dir)):
        if extra:
            parts.append(extra)
    return "\n\n".join(parts)


def score_with_fixes(lab_dir, cfg, tag, exp, session_id, runner):
    rel = str(exp.relative_to(lab_dir))
    metrics, out = evaluate(lab_dir, cfg, rel)
    fixes = 0
    while metrics is None:
        fixes += 1
        if fixes > cfg["max_fix_calls"] or not session_id:
            console.print(f"[red]✗ {exp.name} — invalid after {cfg['max_fix_calls']} fix attempts[/red]")
            console.print(f"[dim]{' '.join(out.split())[-200:]}[/dim]")
            append_result(lab_dir, cfg, {
                "tag": tag, "experiment_file": rel, metric_name(cfg): None,
                "best_so_far": False, "notes": f"invalid: {' '.join(out.split())[-160:]}",
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            return
        console.print(f"[yellow]⟳ evaluation failed — asking the worker to fix it "
                      f"({fixes}/{cfg['max_fix_calls']})…[/yellow]")
        fix_prompt = (
            f"You were working on {rel}. The judge ran on it and FAILED:\n\n{out}\n\n"
            "Fix the experiment file so it runs cleanly. Validate it. Do not run "
            "evaluation.py. Reply with the same JSON object, then stop."
        )
        with console.status("[yellow]Worker is fixing the experiment…", spinner="dots"):
            session_id = runner.run_structured(fix_prompt, ["experiment_file"], session=session_id).session_id
        metrics, out = evaluate(lab_dir, cfg, rel)

    rows = read_results(lab_dir, cfg)
    prior = best_value(rows, cfg)
    val = _metric_val(metrics, metric_name(cfg))
    best = val is not None and is_better(val, prior, direction(cfg))
    append_result(lab_dir, cfg, {
        "tag": tag, "experiment_file": rel, **metrics,
        "best_so_far": best, "notes": first_docstring_line(exp),
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    flag = "  [bold yellow]⭐ new best![/bold yellow]" if best else ""
    console.print(f"[green]✓ {exp.name}[/green] · {metric_name(cfg)}=[bold]{val}[/bold]{flag}")


def first_docstring_line(path):
    import re
    m = re.search(r'^\s*["\']{3}(.*?)["\']{3}', path.read_text(), re.DOTALL)
    if not m:
        return ""
    body = m.group(1).strip()
    return body.splitlines()[0].strip() if body else ""


def main():
    p = argparse.ArgumentParser(description="Run a leanlab for N experiments.")
    p.add_argument("--lab", required=True, help="path to the lab folder")
    p.add_argument("--n", type=int, default=5, help="how many experiments to run")
    p.add_argument("--dry-run", action="store_true", help="print the worker prompt, run nothing")
    args = p.parse_args()

    lab_dir = Path(args.lab).resolve()
    if not (lab_dir / "lab.json").exists():
        print(f"ERROR: no lab.json in {lab_dir}", file=sys.stderr)
        sys.exit(1)
    cfg = load_lab(lab_dir)

    if args.dry_run:
        print(f"Lab: {cfg['name']} — objective: {direction(cfg)} {metric_name(cfg)}\n")
        print("# WORKER PROMPT\n" + build_worker_prompt(lab_dir, cfg))
        print(f"\n# eval: {cfg['eval_cmd']}  | validate: {cfg['validate_cmd']}")
        print(f"# Critic every {cfg['critic_every']} loops, Director every {cfg['director_every']}.")
        return

    if shutil.which("claude") is None:
        print("ERROR: `claude` not found on PATH.", file=sys.stderr)
        sys.exit(1)

    tag = datetime.now(timezone.utc).strftime("%b%d").lower()
    start = len(read_results(lab_dir, cfg))
    runner = make_runner(lab_dir)
    console.rule(f"[bold]🧪 {cfg['name']}[/bold]  ·  {direction(cfg)} {metric_name(cfg)}  ·  "
                 f"{args.n} experiment(s)")

    try:
        for loop in range(1, args.n + 1):
            console.rule(f"[bold cyan]Experiment {loop}/{args.n}", style="cyan")
            before = experiment_files(lab_dir, cfg)
            with console.status("[cyan]Worker is researching and writing an experiment…", spinner="dots"):
                result = runner.run_structured(build_worker_prompt(lab_dir, cfg), ["experiment_file"])
            scored = False
            if not result.ok:
                console.print("[yellow]⚠ worker produced no valid result — moving on.[/yellow]")
            else:
                new = experiment_files(lab_dir, cfg) - before
                exp = resolve_experiment(lab_dir, cfg, result.data, new)
                if exp is None:
                    console.print("[yellow]⚠ no experiment file produced — moving on.[/yellow]")
                else:
                    console.print(f"[dim]Worker wrote [bold]{exp.name}[/bold] — scoring…[/dim]")
                    score_with_fixes(lab_dir, cfg, tag, exp, result.session_id, runner)
                    scored = True

            if scored and loop % cfg["critic_every"] == 0:
                console.rule("[magenta]Critic review", style="magenta")
                with console.status("[magenta]Critic is red-teaming the latest experiments…", spinner="dots"):
                    runner.run_plain(build_critic_prompt())
                console.print("[magenta]✓ Critic_Feedback.md updated.[/magenta]")
            if loop % cfg["director_every"] == 0:
                console.rule("[blue]Director review", style="blue")
                with console.status("[blue]Director is rewriting the research plan…", spinner="dots"):
                    runner.run_plain(build_director_prompt())
                console.print("[blue]✓ Director_Notes.md updated.[/blue]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")

    n_new = len(read_results(lab_dir, cfg)) - start
    best = best_value(read_results(lab_dir, cfg), cfg)
    console.rule("[green]Done", style="green")
    console.print(f"[green]✓ {n_new} new record(s)[/green] · best {metric_name(cfg)}=[bold]{best}[/bold]"
                  f"  ·  watch:  [bold]leanlab serve {cfg['name']}[/bold]")


if __name__ == "__main__":
    main()
