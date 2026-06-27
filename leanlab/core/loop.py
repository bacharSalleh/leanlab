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

The pieces are objects with injected collaborators: a `Lab` value object, a
`ResultsStore` (the book), an `Evaluator` (the judge), a `Prompts` builder, and
the `ExperimentLoop` that drives them. The module-level functions at the bottom
are thin shims kept for the CLI, the doctor, and the tests.

Run:
    uv run python core/loop.py --lab labs/house-prices --n 5
    uv run python core/loop.py --lab labs/house-prices --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
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


# --- the lab (a value object over lab.json) ---------------------------------
class Lab:
    """A metric lab folder and its config — the objective, commands, and cadences."""

    def __init__(self, lab_dir, cfg):
        self.dir = Path(lab_dir)
        self.cfg = cfg

    @classmethod
    def load(cls, lab_dir):
        lab_dir = Path(lab_dir)
        cfg = json.loads((lab_dir / "lab.json").read_text())
        cfg.setdefault("experiments_dir", "experiments")
        cfg.setdefault("results_file", "results.jsonl")
        cfg.setdefault("director_every", 5)
        cfg.setdefault("critic_every", 5)
        cfg.setdefault("max_fix_calls", 3)
        cfg["objective"].setdefault("direction", "max")
        return cls(lab_dir, cfg)

    @property
    def metric(self):
        return self.cfg["objective"]["metric"]

    @property
    def direction(self):
        return self.cfg["objective"]["direction"]

    @property
    def name(self):
        return self.cfg["name"]


# --- the book (results.jsonl) -----------------------------------------------
class ResultsStore:
    """The lab's book: read/append result records and rank them by the objective."""

    def __init__(self, lab):
        self._lab = lab

    @property
    def _path(self):
        return self._lab.dir / self._lab.cfg["results_file"]

    def read(self):
        if not self._path.exists():
            return []
        out = []
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out

    def append(self, record):
        with self._path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def best_value(self):
        return self.rank_best(self.read(), self._lab.metric, self._lab.direction)

    @staticmethod
    def metric_val(rec, metric):
        try:
            return float(rec.get(metric))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def rank_best(rows, metric, d):
        vals = [v for v in (ResultsStore.metric_val(r, metric) for r in rows) if v is not None]
        if not vals:
            return None
        return min(vals) if d == "min" else max(vals)

    @staticmethod
    def is_better(value, best, d):
        if best is None:
            return True
        return value < best if d == "min" else value > best


# --- the judge (evaluation.py) ----------------------------------------------
class Evaluator:
    """Runs the lab's frozen evaluation.py on an experiment file and parses its metrics."""

    def __init__(self, lab):
        self._lab = lab

    @staticmethod
    def run_cmd(template, lab_dir, file_rel):
        parts = [p.replace("{file}", file_rel) for p in shlex.split(template)]
        return subprocess.run(parts, cwd=lab_dir, capture_output=True, text=True)

    def evaluate(self, file_rel):
        """Run the lab's eval_cmd. Returns (metrics_dict_or_None, raw_output)."""
        proc = self.run_cmd(self._lab.cfg["eval_cmd"], self._lab.dir, file_rel)
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


# The fixed agent specs live in the leanlab package (not the user's lab) and are
# injected into each prompt at runtime. Each prompt's FIRST line names the role so
# the dashboard can identify the session.
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


# --- prompt construction ----------------------------------------------------
class Prompts:
    """Builds the worker / director / critic prompts for a lab from its specs + state."""

    def __init__(self, lab):
        self._lab = lab

    def worker(self):
        rows = ResultsStore(self._lab).read()
        parts = [WORKER_INTRO, self.spec("CLAUDE.md"), WORKER_ACTION,
                 self.memory(rows, self._lab.metric, self._lab.direction)]
        for extra in (self.directions(), self.critique()):
            if extra:
                parts.append(extra)
        return "\n\n".join(parts)

    def directions(self):
        return self._inject("Director_Notes.md",
                            "DIRECTOR'S GUIDANCE (your chief scientist — follow it):")

    def critique(self):
        return self._inject("Critic_Feedback.md",
                            "THE TEAM OF CRITICS SAID (fix these flaws — do not repeat them):")

    def _inject(self, filename, header):
        path = self._lab.dir / filename
        if not path.exists():
            return ""
        text = path.read_text().strip()
        return f"{header}\n{text}" if text else ""

    @staticmethod
    def memory(rows, metric, d):
        scored = [r for r in rows if ResultsStore.metric_val(r, metric) is not None]
        if not scored:
            return "MEMORY: no experiments scored yet. You are the first."
        scored.sort(key=lambda r: ResultsStore.metric_val(r, metric), reverse=(d == "max"))
        top = scored[:MEMORY_TOP_N]
        lines = [f"MEMORY — best experiments so far (objective: {d} {metric}; "
                 f"do not repeat these):"]
        for r in top:
            extras = " ".join(f"{k}={v}" for k, v in r.items()
                              if k not in ("tag", "experiment_file", "best_so_far", "notes", "ts"))
            lines.append(f"- {r.get('experiment_file','?')} :: {extras} :: {r.get('notes','')}")
        return "\n".join(lines)

    @staticmethod
    def spec(name):
        return (resources.files("leanlab") / "templates" / "agents" / name).read_text().strip()

    @classmethod
    def director(cls):
        return "\n\n".join([DIRECTOR_INTRO, cls.spec("director.md"), DIRECTOR_ACTION])

    @classmethod
    def critic(cls):
        return "\n\n".join([CRITIC_INTRO, cls.spec("critic.md"), CRITIC_ACTION])


def make_runner(lab_dir):
    """The default AgentRunner: a Claude transport wrapped in the retry protocol.

    The loop depends only on the AgentRunner abstraction — swap this factory to
    plug in a Hermes or custom backend.
    """
    return StructuredRunner(
        ClaudeAgent(lab_dir, max_turns=TURNS_PER_RUN, permission_mode=FULL_PERMISSION_MODE)
    )


# --- the loop ---------------------------------------------------------------
class ExperimentLoop:
    """Drives a lab for N experiments: worker → score (with fixes) → critic / director."""

    def __init__(self, lab, runner=None, ui=None):
        self._lab = lab
        self._results = ResultsStore(lab)
        self._evaluator = Evaluator(lab)
        self._prompts = Prompts(lab)
        self._runner = runner
        self._ui = ui or console

    def worker_prompt(self):
        return self._prompts.worker()

    def experiment_files(self):
        d = self._lab.dir / self._lab.cfg["experiments_dir"]
        return {p for p in d.glob("*.py") if p.name != "sample.py"}

    def resolve_experiment(self, report, new_files):
        if report and report.get("experiment_file"):
            cand = (self._lab.dir / report["experiment_file"]).resolve()
            if cand.exists():
                return cand
        return sorted(new_files)[-1] if new_files else None

    @staticmethod
    def first_docstring_line(path):
        m = re.search(r'^\s*["\']{3}(.*?)["\']{3}', path.read_text(), re.DOTALL)
        if not m:
            return ""
        body = m.group(1).strip()
        return body.splitlines()[0].strip() if body else ""

    def score_with_fixes(self, tag, exp, session_id):
        lab, cfg = self._lab, self._lab.cfg
        rel = str(exp.relative_to(lab.dir))
        metrics, out = self._evaluator.evaluate(rel)
        fixes = 0
        while metrics is None:
            fixes += 1
            if fixes > cfg["max_fix_calls"] or not session_id:
                self._ui.print(f"[red]✗ {exp.name} — invalid after {cfg['max_fix_calls']} fix attempts[/red]")
                self._ui.print(f"[dim]{' '.join(out.split())[-200:]}[/dim]")
                self._results.append({
                    "tag": tag, "experiment_file": rel, lab.metric: None,
                    "best_so_far": False, "notes": f"invalid: {' '.join(out.split())[-160:]}",
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                return
            self._ui.print(f"[yellow]⟳ evaluation failed — asking the worker to fix it "
                           f"({fixes}/{cfg['max_fix_calls']})…[/yellow]")
            fix_prompt = (
                f"You were working on {rel}. The judge ran on it and FAILED:\n\n{out}\n\n"
                "Fix the experiment file so it runs cleanly. Validate it. Do not run "
                "evaluation.py. Reply with the same JSON object, then stop."
            )
            with self._ui.status("[yellow]Worker is fixing the experiment…", spinner="dots"):
                session_id = self._runner.run_structured(
                    fix_prompt, ["experiment_file"], session=session_id).session_id
            metrics, out = self._evaluator.evaluate(rel)

        prior = self._results.best_value()
        val = ResultsStore.metric_val(metrics, lab.metric)
        best = val is not None and ResultsStore.is_better(val, prior, lab.direction)
        self._results.append({
            "tag": tag, "experiment_file": rel, **metrics,
            "best_so_far": best, "notes": self.first_docstring_line(exp),
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        flag = "  [bold yellow]⭐ new best![/bold yellow]" if best else ""
        self._ui.print(f"[green]✓ {exp.name}[/green] · {lab.metric}=[bold]{val}[/bold]{flag}")

    def run(self, n):
        """Run N experiments, waking the critic / director on their cadence."""
        lab, cfg = self._lab, self._lab.cfg
        self._runner = self._runner or make_runner(lab.dir)
        tag = datetime.now(timezone.utc).strftime("%b%d").lower()
        start = len(self._results.read())
        self._ui.rule(f"[bold]🧪 {lab.name}[/bold]  ·  {lab.direction} {lab.metric}  ·  "
                      f"{n} experiment(s)")
        try:
            for loop in range(1, n + 1):
                self._ui.rule(f"[bold cyan]Experiment {loop}/{n}", style="cyan")
                before = self.experiment_files()
                with self._ui.status("[cyan]Worker is researching and writing an experiment…", spinner="dots"):
                    result = self._runner.run_structured(self.worker_prompt(), ["experiment_file"])
                scored = False
                if not result.ok:
                    self._ui.print("[yellow]⚠ worker produced no valid result — moving on.[/yellow]")
                else:
                    new = self.experiment_files() - before
                    exp = self.resolve_experiment(result.data, new)
                    if exp is None:
                        self._ui.print("[yellow]⚠ no experiment file produced — moving on.[/yellow]")
                    else:
                        self._ui.print(f"[dim]Worker wrote [bold]{exp.name}[/bold] — scoring…[/dim]")
                        self.score_with_fixes(tag, exp, result.session_id)
                        scored = True

                if scored and loop % cfg["critic_every"] == 0:
                    self._ui.rule("[magenta]Critic review", style="magenta")
                    with self._ui.status("[magenta]Critic is red-teaming the latest experiments…", spinner="dots"):
                        self._runner.run_plain(Prompts.critic())
                    self._ui.print("[magenta]✓ Critic_Feedback.md updated.[/magenta]")
                if loop % cfg["director_every"] == 0:
                    self._ui.rule("[blue]Director review", style="blue")
                    with self._ui.status("[blue]Director is rewriting the research plan…", spinner="dots"):
                        self._runner.run_plain(Prompts.director())
                    self._ui.print("[blue]✓ Director_Notes.md updated.[/blue]")
        except KeyboardInterrupt:
            self._ui.print("\n[yellow]Stopped.[/yellow]")

        n_new = len(self._results.read()) - start
        best = self._results.best_value()
        self._ui.rule("[green]Done", style="green")
        self._ui.print(f"[green]✓ {n_new} new record(s)[/green] · best {lab.metric}=[bold]{best}[/bold]"
                       f"  ·  watch:  [bold]leanlab serve {lab.name}[/bold]")

    def dry_run(self):
        lab = self._lab
        print(f"Lab: {lab.name} — objective: {lab.direction} {lab.metric}\n")
        print("# WORKER PROMPT\n" + self.worker_prompt())
        print(f"\n# eval: {lab.cfg['eval_cmd']}  | validate: {lab.cfg['validate_cmd']}")
        print(f"# Critic every {lab.cfg['critic_every']} loops, Director every {lab.cfg['director_every']}.")


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
    lab = Lab.load(lab_dir)
    loop = ExperimentLoop(lab, ui=console)

    if args.dry_run:
        loop.dry_run()
        return

    if shutil.which("claude") is None:
        print("ERROR: `claude` not found on PATH.", file=sys.stderr)
        sys.exit(1)

    loop.run(args.n)


if __name__ == "__main__":
    main()
