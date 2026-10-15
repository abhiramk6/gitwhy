# ADR-102: User-controlled text is never wrapped in Markup()

Status: accepted
Date: 2026-03-04
Scope: flask, jinja, markupsafe
Topic: html-safety

Templates rely on Jinja2 autoescaping backed by markupsafe.escape. Application code must not construct Markup() from user-controlled input, and `|safe` is only allowed on strings produced by markupsafe.escape or a reviewed sanitiser. Any change to escape() behaviour is security-sensitive and needs sign-off from the security guild.
