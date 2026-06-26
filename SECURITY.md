# Security Policy

## Supported versions

leanlab is pre-1.0; only the latest released version on PyPI receives fixes.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report privately via GitHub's
[private vulnerability reporting](https://github.com/bacharSalleh/leanlab/security/advisories/new),
or email **welcomebachar@gmail.com** with details and reproduction steps.

You can expect an acknowledgement within a few days. Once a fix is ready, a new
patch release is published to PyPI and the advisory is disclosed.

## Scope notes

leanlab runs the `claude` CLI with elevated permissions inside isolated git
worktrees and executes project test commands as part of the gate. Treat the
labs you run it in as you would any code-execution tool — only point it at
repositories and tasks you trust.
