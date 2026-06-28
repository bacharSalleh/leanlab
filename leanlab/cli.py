"""leanlab CLI — init, run, and serve experiment labs.

leanlab is a research tool used *inside* another project. Labs live in that
project's `.leanlab/<name>/` folder and hold only the task-specific files the
user edits: task.md, lab.json, evaluation.py, validate.py. The engine (loop +
monitor) and the fixed agent specs live in the installed package and are never
copied into the project.

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
        return "0.2.4"


def labs_dir() -> Path:
    """Where labs live: the .leanlab/ folder of the project leanlab is run inside."""
    return Path.cwd() / ".leanlab"


def cmd_init(args):
    import questionary
    if not args.name:
        print("ERROR: a lab name is required.", file=sys.stderr)
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

    pi = sub.add_parser("init", help="scaffold a lab (Claude drafts it)")
    pi.add_argument("name", nargs="?", default=None)
    pi.add_argument("--describe", default=None, help="task description (skips the prompt)")
    pi.add_argument("--yes", action="store_true", help="auto-approve the drafted evaluator (headless)")
    pi.set_defaults(func=cmd_init)

    pr = sub.add_parser("run", help="run N experiments in a lab")
    pr.add_argument("lab")
    pr.add_argument("--n", type=int, default=5)
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--skip-checks", action="store_true", help="skip the preflight doctor checks")
    pr.set_defaults(func=cmd_run)

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
