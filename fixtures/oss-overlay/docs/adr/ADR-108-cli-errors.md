# ADR-108: Command line tools print plain-text errors and exit non-zero

Status: accepted
Date: 2026-05-20
Scope: click, requests
Topic: error-format

CLI tools built on Click show a one-line message on stderr via click.ClickException and use exit codes; they never print JSON error bodies.
