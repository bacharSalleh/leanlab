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

1. Bump the version in **three** places (keep them in sync):
   - `pyproject.toml` → `version`
   - `frontend/package.json` → `version`
   - `leanlab/cli.py` → `_version()` fallback
2. Move the `## [Unreleased]` notes into a new dated section in `CHANGELOG.md`.
3. Commit, then tag and push:
   ```bash
   git commit -am "release: v0.2.2"
   git tag v0.2.2
   git push origin main --tags
   ```
4. The `Publish to PyPI` workflow runs: build UI → build wheel → publish → release.
   Watch it under the repo's **Actions** tab.

## Verify

```bash
pipx install leanlab            # or: pip install leanlab / uvx leanlab
leanlab --version
```
