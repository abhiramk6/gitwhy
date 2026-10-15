# ADR-107: Flask services return RFC 7807 problem+json errors

Status: accepted
Date: 2026-05-06
Scope: flask, werkzeug
Topic: error-format

HTTP errors raised through werkzeug.exceptions are rendered by a Flask error handler as application/problem+json.
