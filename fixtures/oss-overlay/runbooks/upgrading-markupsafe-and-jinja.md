# Runbook: upgrading markupsafe or jinja

markupsafe is imported by jinja, werkzeug and flask, so a behaviour change in escape() or Markup ripples through every web service on the platform.
Checklist: run flask and werkzeug test suites against the candidate version, grep application code for Markup( and |safe (ADR-102), roll out to one canary service first.
