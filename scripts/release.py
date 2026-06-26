#!/usr/bin/env python3
"""One-command release.

Bumps the version everywhere, rolls the CHANGELOG, runs the tests as a guard,
commits, tags, and (after a confirm) pushes — then .github/workflows/publish.yml
builds the UI + wheel, publishes to PyPI, and cuts the GitHub Release.

Usage (run from a clean `main`):
    uv run python scripts/release.py patch        # 0.2.1 -> 0.2.2
    uv run python scripts/release.py minor        # 0.2.1 -> 0.3.0
    uv run python scripts/release.py major        # 0.2.1 -> 1.0.0
    uv run python scripts/release.py 1.2.3        # explicit version
    uv run python scripts/release.py patch --dry-run     # show what would change, write nothing
    uv run python scripts/release.py patch --skip-tests  # skip the pytest guard
    uv run python scripts/release.py patch --yes         # push without the confirmation prompt
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "bacharSalleh/leanlab"


def sh(*args, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture)


def die(msg):
    sys.exit(f"release: {msg}")


def current_version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def next_version(cur, how):
    if re.fullmatch(r"\d+\.\d+\.\d+", how):
        return how
    try:
        major, minor, patch = (int(x) for x in cur.split("."))
    except ValueError:
        die(f"current version '{cur}' is not X.Y.Z")
    return {"major": f"{major + 1}.0.0",
            "minor": f"{major}.{minor + 1}.0",
            "patch": f"{major}.{minor}.{patch + 1}"}.get(how) or die(
        f"unknown bump '{how}' — use patch | minor | major | X.Y.Z")


def edit(path, pattern, repl, label):
    """Return (path, new_text) after exactly one substitution, or abort."""
    p = ROOT / path
    new, n = re.subn(pattern, repl, p.read_text(), count=1)
    if n != 1:
        die(f"could not update {label} in {path} (expected exactly 1 match, got {n})")
    return p, new


def main():
    ap = argparse.ArgumentParser(description="Cut a leanlab release.")
    ap.add_argument("bump", help="patch | minor | major | X.Y.Z")
    ap.add_argument("--dry-run", action="store_true", help="show changes, write nothing")
    ap.add_argument("--skip-tests", action="store_true", help="skip the pytest guard")
    ap.add_argument("--yes", action="store_true", help="push without confirmation")
    args = ap.parse_args()

    branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True).stdout.strip()
    if branch != "main":
        die(f"must be on 'main' (currently on '{branch}')")
    if not args.dry_run and sh("git", "status", "--porcelain", capture=True).stdout.strip():
        die("working tree is not clean — commit or stash first")

    cur = current_version()
    new = next_version(cur, args.bump)
    if new == cur:
        die(f"version is already {new}")
    today = datetime.now(timezone.utc).date().isoformat()
    tag = f"v{new}"
    print(f"release: {cur} -> {new}  ({today})")

    edits = [
        edit("pyproject.toml", rf'(?m)^version = "{re.escape(cur)}"$', f'version = "{new}"', "pyproject version"),
        edit("frontend/package.json", rf'"version": "{re.escape(cur)}"', f'"version": "{new}"', "frontend version"),
        edit("leanlab/cli.py", rf'return "{re.escape(cur)}"', f'return "{new}"', "cli version fallback"),
    ]

    # CHANGELOG: turn the Unreleased section into the new version, open a fresh Unreleased,
    # and refresh the compare links at the bottom.
    cl = ROOT / "CHANGELOG.md"
    text = cl.read_text()
    if "## [Unreleased]" not in text:
        die("CHANGELOG.md has no '## [Unreleased]' section")
    text = text.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{new}] - {today}", 1)
    text, n = re.subn(
        r"(?m)^\[Unreleased\]: (.*)/compare/v[\d.]+\.\.\.HEAD$",
        rf"[Unreleased]: \1/compare/v{new}...HEAD\n[{new}]: \1/compare/v{cur}...v{new}",
        text, count=1)
    if n != 1:
        die("could not update the CHANGELOG '[Unreleased]' compare link")
    edits.append((cl, text))

    if args.dry_run:
        print("dry-run — would update:")
        for p, _ in edits:
            print(f"  - {p.relative_to(ROOT)}")
        print(f"  then: uv lock · pytest · commit 'release: {tag}' · tag {tag} · push")
        return

    for p, new_text in edits:
        p.write_text(new_text)
    sh("uv", "lock")                       # keep uv.lock's version in sync

    if not args.skip_tests:
        print("release: running tests…")
        sh("uv", "run", "pytest", "-q")

    sh("git", "add", "-A")
    sh("git", "commit", "-m", f"release: {tag}")
    sh("git", "tag", tag)
    print(f"release: committed + tagged {tag}")

    if not args.yes:
        ans = input(f"Push main + {tag} and trigger the PyPI release? [y/N] ").strip().lower()
        if ans != "y":
            print("release: prepared locally, NOT pushed. To finish:")
            print(f"  git push origin main {tag}")
            print(f"  to undo:  git tag -d {tag} && git reset --hard HEAD~1")
            return

    sh("git", "push", "origin", "main", tag)
    print(f"release: pushed. Watch → https://github.com/{REPO}/actions")


if __name__ == "__main__":
    main()
