"""Interactive `leanlab init` — the init-architect.

Realizes the init-lab use case. The architect (Claude, reached through the same
AgentRunner the workers use) drafts task.md + the objective from the operator's
plain-words description, then proposes an evaluator in a loop until the operator
approves. All terminal I/O goes through an injected `ui` (default: a rich + questionary
console) so the flow is fully testable without a real terminal or Claude.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .loop import make_runner

LAB_JSON_TEMPLATE = {
    "name": "",
    "description": "TODO: one line describing the task.",
    "objective": {"metric": "score", "direction": "max"},
    "experiments_dir": "experiments",
    "results_file": "results.jsonl",
    "validate_cmd": "uv run python validate.py --experiment {file}",
    "eval_cmd": "uv run python evaluation.py --experiment {file}",
    "director_every": 5,
    "critic_every": 5,
    "max_fix_calls": 3,
}


class LabScaffold:
    """Creates the empty .leanlab/<name>/ skeleton (no agent specs — those live in the package)."""

    @staticmethod
    def create(lab: Path, name: str) -> None:
        lab = Path(lab)
        (lab / "experiments").mkdir(parents=True)
        (lab / "lab.json").write_text(json.dumps(dict(LAB_JSON_TEMPLATE, name=name), indent=2) + "\n")
        (lab / "results.jsonl").write_text("")
        (lab / "Director_Notes.md").write_text("# Director Notes\n\nNeutral — no experiments yet.\n")
        (lab / "Critic_Feedback.md").write_text("# Critic Feedback\n\nNo experiments reviewed yet.\n")


class RichUI:
    """Terminal UI for `init` — spinners, panels, syntax-highlighted code, arrow-key menus."""

    def __init__(self):
        from rich.console import Console
        self.console = Console()

    def status(self, message):
        return self.console.status(f"[bold cyan]{message}", spinner="dots")

    def note(self, message):
        self.console.print(message)

    def error(self, message):
        self.console.print(f"[bold red]{message}[/bold red]")

    def objective(self, obj):
        from rich.panel import Panel
        self.console.print(Panel(f"[bold]{obj.get('direction')} {obj.get('metric')}[/bold]",
                                 title="Objective", border_style="cyan", expand=False))

    def proposal(self, summary):
        from rich.markdown import Markdown
        from rich.panel import Panel
        self.console.print(Panel(Markdown(summary), title="Proposed evaluation",
                                 border_style="magenta"))

    def decide(self, evaluation_py):
        import questionary
        from rich.syntax import Syntax
        approve, view, feedback, cancel = (
            "✓ Approve & write the files", "👁 View the generated evaluation.py",
            "✍ Give feedback (revise)", "✖ Cancel")
        while True:
            choice = questionary.select("What now?", choices=[approve, view, feedback, cancel]).ask()
            if choice is None or choice == cancel:
                return ("cancel", None)
            if choice == view:
                self.console.print(Syntax(evaluation_py, "python", theme="ansi_dark",
                                          line_numbers=True, word_wrap=True))
                continue
            if choice == approve:
                return ("approve", None)
            return ("feedback", questionary.text("Your feedback for Claude:").ask() or "")

    def success(self, lab, name):
        from rich.panel import Panel
        self.console.print(Panel(
            f"Lab ready: [bold]{lab}[/bold]\n\nReview the evaluator, then run:\n"
            f"  [green]leanlab lock {name} && leanlab run {name}[/green]",
            title="✓ Done", border_style="green"))


class InitArchitect:
    """Drafts task.md + the objective, then proposes an evaluator in a feedback loop.

    `runner` (the AgentRunner) and `ui` are injected so the whole flow is testable
    without Claude or a real terminal.
    """

    def  __init__(self, runner=None, ui=None):
        self._runner = runner
        self._ui = ui or RichUI()

    @staticmethod
    def _draft_prompt(description: str) -> str:
        return (
            "You are the lab ARCHITECT for leanlab. The operator wants to research:\n\n"
            f"{description}\n\n"
            "Base your decision ONLY on the task description above. Ignore any other labs, "
            "example projects, or files that may exist in this directory or its parents — they are "
            "unrelated and must not influence the metric or framing. "
            "Decide what a single 'experiment' is for this task and how success is measured. "
            "Choose the objective metric that is STANDARD and APPROPRIATE for THIS task — judge it "
            "on the task's own terms; do NOT default to any particular metric. Match the metric to "
            "the task type, e.g.: classification -> accuracy / F1 / ROC-AUC; regression -> RMSE / "
            "MAE / R2; ranking -> NDCG / MAP; clustering -> silhouette. Set direction (min or max) "
            "to fit, and give a one-line justification for the choice. If the request is not a "
            "measurable experiment as written, reframe it into the closest measurable one and say so. "
            "Write a clear task.md: the goal, the chosen metric (with the justification), and the "
            "experiment contract — what ONE file in experiments/ must define so evaluation.py can run "
            "it. You may research the web. Do NOT create or edit any files. Reply with ONLY this JSON "
            'object: {"task_md": "<full markdown>", '
            '"objective": {"metric": "<name>", "direction": "min|max"}}'
        )

    @staticmethod
    def _propose_prompt(feedback: str | None, metric: str, eval_cmd: str, validate_cmd: str) -> str:
        base = (
            "Propose how to EVALUATE this task, using the objective metric you chose. If it needs "
            "data, say what data and how you would obtain and split it. Provide the full CONTENTS of "
            "a frozen evaluation.py and a cheap validate.py.\n"
            "HARD REQUIREMENTS — the lab will NOT score unless these hold exactly:\n"
            f"1. leanlab runs your files from inside the lab dir with EXACTLY these commands, where "
            f"{{file}} is the experiment path:\n"
            f"     evaluation:  {eval_cmd}\n"
            f"     validate:    {validate_cmd}\n"
            f"   So evaluation.py and validate.py MUST parse their arguments to match — use argparse "
            f"with a '--experiment' option. Do NOT read a positional argument like sys.argv[1].\n"
            f'2. evaluation.py MUST print ONE line of JSON whose keys include exactly "{metric}" '
            f'(the objective metric, spelled exactly — NOT a generic "score"). Extra metrics are fine '
            f"as additional flat (number) keys; avoid nested objects.\n"
            "3. Do NOT create or edit any files — return everything inside the JSON only.\n"
            "4. evaluation.py and validate.py MUST check the experiment file exists and fail fast FIRST "
            "— before importing heavy libraries, rendering, or calling any model — so a quick preflight "
            "stays cheap.\n"
            "5. List in 'packages' every third-party pip package evaluation.py or validate.py imports "
            "(e.g. playwright, numpy) so the lab can install them. Use [] if none. If you need an LLM "
            "to judge, call the `claude` CLI via subprocess (no API key needed) rather than an SDK.\n"
            "Reply with ONLY this JSON object: "
            '{"summary": "<plain-English approach, 3-5 sentences>", '
            '"evaluation_py": "<full file contents>", "validate_py": "<full file contents>", '
            '"packages": ["<pip name>", ...]}'
        )
        if feedback:
            return (f"The operator gave this feedback on your previous proposal:\n\n{feedback}\n\n"
                    f"Revise accordingly. {base}")
        return base

    def init(self, lab, name, description, *, verify=True, yes=False) -> None:
        """Scaffold a lab, then draft it with the architect and approve the evaluator in a loop."""
        lab = Path(lab)
        LabScaffold.create(lab, name)
        ui = self._ui
        runner = self._runner or make_runner(lab)

        with ui.status("Drafting task.md and the objective with Claude…"):
            draft = runner.run_structured(self._draft_prompt(description), ["task_md", "objective"])
        if not draft.ok:
            ui.error("Could not draft the task — try again with a clearer description.")
            return
        (lab / "task.md").write_text(draft.data["task_md"])
        cfg = json.loads((lab / "lab.json").read_text())
        obj = draft.data["objective"]
        if isinstance(obj, dict) and "metric" in obj and "direction" in obj:
            cfg["objective"] = obj
        else:
            ui.error("⚠ Claude returned an unexpected objective shape — set lab.json's objective by hand.")
        (lab / "lab.json").write_text(json.dumps(cfg, indent=2) + "\n")
        ui.objective(cfg["objective"])

        metric = cfg["objective"].get("metric", "score")
        session, feedback = draft.session_id, None
        while True:
            with ui.status("Designing an evaluator with Claude…"):
                prop = runner.run_structured(
                    self._propose_prompt(feedback, metric, cfg["eval_cmd"], cfg["validate_cmd"]),
                    ["summary", "evaluation_py", "validate_py"], session=session)
            if not prop.ok:
                ui.error("Could not propose an evaluation — aborting.")
                return
            session = prop.session_id or session
            ui.proposal(prop.data["summary"])
            action, text = ("approve", None) if yes else ui.decide(prop.data["evaluation_py"])
            if action == "approve":
                (lab / "evaluation.py").write_text(prop.data["evaluation_py"])
                (lab / "validate.py").write_text(prop.data["validate_py"])
                self._install_packages(prop.data.get("packages"))
                break
            if action == "cancel":
                ui.note("Cancelled — no evaluator written. task.md and lab.json were kept.")
                return
            feedback = text

        if verify:
            self._self_verify(lab, runner)
        ui.success(lab, name)

    def _install_packages(self, packages):
        """uv add the pip packages the evaluator/validator declared they need."""
        for pkg in packages or []:
            if not isinstance(pkg, str) or not pkg.strip():
                continue
            with self._ui.status(f"Installing {pkg}…"):
                r = subprocess.run(["uv", "add", pkg.strip()], capture_output=True, text=True)
            if r.returncode != 0:
                self._ui.error(f"⚠ could not install {pkg!r} (uv add failed) — install it yourself: "
                               f"{(r.stderr or '').strip()[:120]}")

    def _self_verify(self, lab, runner):
        """Run the doctor; if the generated lab is mis-wired, have Claude fix it before finishing."""
        from .doctor import LabDoctor, ok
        doctor = LabDoctor(lab)
        if ok(doctor.check()):
            self._ui.note("[green]✓ wiring check passed.[/green]")
            return
        self._ui.note("[yellow]⚠ wiring check found problems — fixing with Claude before finishing…[/yellow]")
        doctor.fix(runner=runner)
