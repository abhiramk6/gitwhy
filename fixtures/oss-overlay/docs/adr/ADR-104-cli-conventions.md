# ADR-104: Command line tools are built with Click

Status: accepted
Date: 2026-03-25
Scope: click, flask
Topic: cli

Internal CLIs use Click command groups with shell completion enabled; hand-written argparse parsers are not accepted in new code. Flask application commands are registered through the Flask CLI so they share the app context.
