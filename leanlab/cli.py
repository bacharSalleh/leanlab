"""leanlab CLI — init, run, and serve labs.

leanlab is a research tool used *inside* another project (like archik). Labs live in
that project's `.leanlab/<name>/` folder and hold only the task-specific files the user
edits: task.md, lab.json, evaluation.py, validate.py. The engine (loop + monitor) and the
fixed agent specs live in the installed package and are never copied into the project.

Usage (inside your project):
    uvx leanlab init <name>           # interactively scaffold a lab (Claude drafts it)
    uvx leanlab run <lab> --n 5       # run N experiments
    uvx leanlab serve <lab>           # open the dashboard
    uvx leanlab list                  # list labs in this project
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .core.init import InitArchitect


def _version() -> str:
    """The installed package version (falls back when running from an uninstalled checkout)."""
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("leanlab")
    except (ImportError, PackageNotFoundError):
        return "0.2.2"


def labs_dir() -> Path:
    """Where labs live: the .leanlab/ folder of the project leanlab is run inside."""
    return Path.cwd() / ".leanlab"


def _install_agent_skill(project: Path) -> Path:
    from importlib import resources
    src = (resources.files("leanlab") / "templates" / "skill" / "SKILL.md").read_text()
    dest = project / ".claude" / "skills" / "leanlab" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src)
    return dest


_CLAUDE_MD_MARKER = "<!-- leanlab:agent -->"
_CLAUDE_MD_BLOCK = (
    f"{_CLAUDE_MD_MARKER}\n"
    "## Coding tasks — use leanlab\n\n"
    "For feature / fix / refactor work on this repo, drive it through **leanlab** (the honest, "
    "test-gated loop) instead of editing files directly. See `.claude/skills/leanlab/SKILL.md`.\n"
    "Flow: `leanlab spec \"<task>\" --yes` → read the `slug:` line → `leanlab build <slug>` → report.\n"
    f"{_CLAUDE_MD_MARKER}\n"
)


def _append_claude_md(project: Path) -> bool:
    """Append the leanlab guidance to the project's CLAUDE.md (idempotent). True if it changed."""
    p = project / "CLAUDE.md"
    text = p.read_text() if p.exists() else ""
    if _CLAUDE_MD_MARKER in text:
        return False
    sep = "" if (not text or text.endswith("\n")) else "\n"
    p.write_text(text + sep + "\n" + _CLAUDE_MD_BLOCK)
    return True


def _coding_gate_cmds(args):
    """Assemble the gate command list shared by `build` and `gate` from the CLI flags."""
    cmds = [{"name": "tests", "cmd": args.test_cmd or "pytest -q"}]
    if args.lint_cmd:
        cmds.append({"name": "lint", "cmd": args.lint_cmd})
    return cmds


def cmd_init(args):
    if args.for_agent:
        dest = _install_agent_skill(Path.cwd())
        print(f"✓ leanlab skill installed at {dest}")
        if _append_claude_md(Path.cwd()):
            print("✓ added leanlab guidance to CLAUDE.md")
        else:
            print("• CLAUDE.md already mentions leanlab — left it as is")
        print("Claude Code in this project can now drive leanlab (spec → build → merge).")
        return
    import questionary
    if not args.name:
        print("ERROR: a lab name is required (or use `leanlab init --for-agent`).", file=sys.stderr)
        sys.exit(1)
    lab = labs_dir() / args.name
    if lab.exists():
        print(f"ERROR: {lab} already exists.", file=sys.stderr)
        sys.exit(1)
    description = (args.describe
                  or questionary.text("Describe the task you want to research:").ask() or "").strip()
    if not description:
        print("ERROR: a task description is required.", file=sys.stderr)
        sys.exit(1)
    InitArchitect().init(lab, args.name, description, yes=args.yes)


def cmd_spec(args):
    from .core.coding.spec import SpecWriter
    res = SpecWriter().spec(Path.cwd(), args.task, yes=args.yes)
    if res:
        print(f"slug: {Path(res['worktree']).name}")     # plain line for an agent to parse
    sys.exit(0 if res else 1)


def cmd_build(args):
    from .core.coding.engineer import Engineer
    from .core.coding.gate import Gate
    eng = Engineer(gate=Gate(_coding_gate_cmds(args)), persona_set=args.persona_set,
                   reviewers=args.reviewers, max_attempts=args.max_attempts,
                   min_quality=args.min_quality, playbook=not args.no_playbook,
                   isolate=not args.no_isolate, accept_cmd=args.accept_cmd)
    res = eng.build(Path.cwd(), args.slug)
    sys.exit(0 if (res and res.get("merged")) else 1)


def cmd_clean(args):
    from .core.coding.spec import clean_worktrees
    removed = clean_worktrees(Path.cwd(), args.slug, remove_all=args.all)
    print(f"removed {len(removed)} worktree(s): {', '.join(removed) or '(none)'}")


def cmd_board(args):
    from .core.coding.board import serve_board
    serve_board(Path.cwd(), port=args.port or 8766, open_browser=not args.no_open)


def cmd_gate(args):
    from .core.coding.gate import Gate, report
    wt = labs_dir() / "worktrees" / args.slug
    if not wt.is_dir():
        print(f"ERROR: no worktree at {wt} — run `leanlab spec` first.", file=sys.stderr)
        sys.exit(1)
    res = Gate(_coding_gate_cmds(args)).run(wt)
    report(res)
    sys.exit(0 if res.passed else 1)


def cmd_check(args):
    from .core.doctor import LabDoctor, RichReport, ok
    checks = LabDoctor(_resolve_lab(args.lab)).check()
    RichReport().report(checks)
    sys.exit(0 if ok(checks) else 1)


def cmd_fix(args):
    from .core.doctor import LabDoctor
    sys.exit(0 if LabDoctor(_resolve_lab(args.lab)).fix() else 1)


def cmd_run(args):
    lab = _resolve_lab(args.lab)
    if not args.skip_checks and not args.dry_run:
        from .core.doctor import LabDoctor, RichReport, ok
        checks = LabDoctor(lab).check()
        if not ok(checks):
            RichReport().report(checks)
            print(f"\nRun blocked by failed checks. Fix them with:  leanlab fix {args.lab}\n"
                  f"(or rerun with --skip-checks to ignore)", file=sys.stderr)
            sys.exit(1)
    cmd = [sys.executable, "-m", "leanlab.core.loop", "--lab", str(lab), "--n", str(args.n)]
    if args.dry_run:
        cmd.append("--dry-run")
    sys.exit(subprocess.run(cmd).returncode)


def cmd_serve(args):
    lab = _resolve_lab(args.lab)
    cmd = [sys.executable, "-m", "leanlab.core.monitor", "--lab", str(lab)]
    if args.port:
        cmd += ["--port", str(args.port)]
    sys.exit(subprocess.run(cmd).returncode)


def cmd_list(_args):
    base = labs_dir()
    if not base.exists():
        print("(no labs yet — run `leanlab init <name>`)")
        return
    for d in sorted(base.iterdir()):
        if (d / "lab.json").exists():
            cfg = json.loads((d / "lab.json").read_text())
            obj = cfg.get("objective", {})
            print(f"  {d.name:20} objective: {obj.get('direction')} {obj.get('metric')}")


def _evaluator(lab):
    ev = lab / "evaluation.py"
    if not ev.exists():
        print(f"ERROR: no evaluation.py in {lab}", file=sys.stderr)
        sys.exit(1)
    return ev


def cmd_lock(args):
    """Make the lab's evaluation.py read-only — a guardrail against accidental edits.

    Note: this is a speed bump, not a sandbox. An agent running as you with full
    tools could chmod it back. For a hard wall, run the Worker as a separate user.
    """
    ev = _evaluator(_resolve_lab(args.lab))
    ev.chmod(0o444)
    print(f"🔒 locked {ev} read-only. Run `leanlab unlock {args.lab}` to edit it.")


def cmd_unlock(args):
    ev = _evaluator(_resolve_lab(args.lab))
    ev.chmod(0o644)
    print(f"🔓 unlocked {ev}. Edit it, then `leanlab lock {args.lab}` again.")


def _resolve_lab(name):
    p = Path(name)
    if p.exists() and (p / "lab.json").exists():
        return p.resolve()
    if (labs_dir() / name / "lab.json").exists():
        return (labs_dir() / name).resolve()
    print(f"ERROR: lab '{name}' not found in {labs_dir()}.", file=sys.stderr)
    sys.exit(1)


def main():
    p = argparse.ArgumentParser(description="leanlab CLI")
    p.add_argument("--version", action="version", version=f"leanlab {_version()}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="scaffold a lab (Claude drafts it), or --for-agent to install the skill")
    pi.add_argument("name", nargs="?", default=None)
    pi.add_argument("--for-agent", action="store_true",
                    help="install the leanlab skill into .claude/ so Claude Code can drive leanlab")
    pi.add_argument("--describe", default=None, help="task description (skips the prompt)")
    pi.add_argument("--yes", action="store_true", help="auto-approve the drafted evaluator (headless)")
    pi.set_defaults(func=cmd_init)

    pr = sub.add_parser("run", help="run N experiments in a lab")
    pr.add_argument("lab")
    pr.add_argument("--n", type=int, default=5)
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--skip-checks", action="store_true", help="skip the preflight doctor checks")
    pr.set_defaults(func=cmd_run)

    psp = sub.add_parser("spec", help="(coding) turn a task into approved, locked acceptance tests")
    psp.add_argument("task", help="the coding task, e.g. \"create a /health endpoint\"")
    psp.add_argument("--yes", action="store_true", help="auto-approve the drafted tests (headless)")
    psp.set_defaults(func=cmd_spec)

    pb = sub.add_parser("build", help="(coding) engineer the task to a green gate + review, then merge")
    pb.add_argument("slug", help="the task worktree name under .leanlab/worktrees/")
    pb.add_argument("--persona-set", default="coding", help="agent persona set (default: coding)")
    pb.add_argument("--max-attempts", type=int, default=5)
    pb.add_argument("--test-cmd", default=None, help="test command (default: pytest -q)")
    pb.add_argument("--lint-cmd", default=None, help="optional lint/typecheck command")
    pb.add_argument("--no-playbook", action="store_true", help="skip the tech-lead PLAYBOOK update")
    pb.add_argument("--min-quality", type=float, default=0, help="reject merges below this 0-100 quality score")
    pb.add_argument("--reviewers", type=int, default=1,
                    help="adversarial reviewer panel size; >1 runs that many reviewers with "
                         "different lenses (correctness/spec/security/robustness) and merges only "
                         "if all approve")
    pb.add_argument("--no-isolate", action="store_true",
                    help="skip the isolated acceptance re-run (which disables engineer conftest)")
    pb.add_argument("--accept-cmd", default="pytest --noconftest -q",
                    help="isolated acceptance command (pristine test paths are appended)")
    pb.set_defaults(func=cmd_build)

    pcl = sub.add_parser("clean", help="(coding) remove task worktrees + branches (merged only by default)")
    pcl.add_argument("slug", nargs="?", default=None, help="a specific task to remove (force)")
    pcl.add_argument("--all", action="store_true", help="remove ALL task worktrees (force)")
    pcl.set_defaults(func=cmd_clean)

    pbd = sub.add_parser("board", help="(coding) live dashboard of tasks, status, and the playbook")
    pbd.add_argument("--port", type=int, default=0)
    pbd.add_argument("--no-open", action="store_true")
    pbd.set_defaults(func=cmd_board)

    pg = sub.add_parser("gate", help="(coding) run the pass/fail gate on a task's worktree")
    pg.add_argument("slug", help="the task worktree name under .leanlab/worktrees/")
    pg.add_argument("--test-cmd", default=None, help="test command (default: pytest -q)")
    pg.add_argument("--lint-cmd", default=None, help="optional lint/typecheck command")
    pg.set_defaults(func=cmd_gate)

    pc = sub.add_parser("check", help="preflight: verify the lab is wired correctly")
    pc.add_argument("lab")
    pc.set_defaults(func=cmd_check)

    pf = sub.add_parser("fix", help="use Claude to fix lab wiring problems the checks found")
    pf.add_argument("lab")
    pf.set_defaults(func=cmd_fix)

    ps = sub.add_parser("serve", help="open the dashboard for a lab")
    ps.add_argument("lab")
    ps.add_argument("--port", type=int, default=0)
    ps.set_defaults(func=cmd_serve)

    pl = sub.add_parser("list", help="list labs")
    pl.set_defaults(func=cmd_list)

    pk = sub.add_parser("lock", help="make a lab's evaluation.py read-only (frozen)")
    pk.add_argument("lab")
    pk.set_defaults(func=cmd_lock)

    pu = sub.add_parser("unlock", help="restore write access to a lab's evaluation.py")
    pu.add_argument("lab")
    pu.set_defaults(func=cmd_unlock)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
