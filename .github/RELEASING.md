# Releasing leanlab

Releases are automated. Pushing a `vX.Y.Z` tag builds the package and publishes
it to PyPI via **Trusted Publishing** (OIDC — no API token is stored anywhere),
then cuts a GitHub Release.

## One-time setup: configure the PyPI trusted publisher

Do this once, before the first release.

1. Create an account at https://pypi.org and verify your email.
2. Reserve the name by creating a **pending publisher** (you don't need to have
   uploaded anything yet): PyPI → **Your projects** → **Publishing** →
   **Add a pending publisher**, with:
   - PyPI Project Name: `leanlab`
   - Owner: `bacharSalleh`
   - Repository name: `leanlab`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. In the GitHub repo, create an **Environment** named `pypi`
   (Settings → Environments → New environment). No secrets needed — OIDC handles auth.

## Cut a release

One command does everything — bump (all 3 version spots), roll the CHANGELOG,
run the tests, commit, tag, and push:

```bash
uv run python scripts/release.py patch     # 0.2.1 -> 0.2.2  (or: minor | major | X.Y.Z)
```

It prints the change, asks before pushing, and on confirm pushes `main` + the
tag — which triggers `publish.yml` (build UI → build wheel → publish to PyPI →
GitHub Release). Watch it under the repo's **Actions** tab.

Flags: `--dry-run` (show changes, write nothing) · `--skip-tests` · `--yes`
(push without the prompt). Before running, write your release notes under
`## [Unreleased]` in `CHANGELOG.md` — the script moves them into the new version
section for you.

Doing it by hand instead: bump `version` in `pyproject.toml`,
`frontend/package.json`, and `leanlab/cli.py` (`_version()` fallback); move the
CHANGELOG notes; then `git tag vX.Y.Z && git push origin main vX.Y.Z`.

## Verify

```bash
pipx install leanlab            # or: pip install leanlab / uvx leanlab
leanlab --version
```
