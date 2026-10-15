# Demo script (~5 minutes, deterministic: works offline, no live model call needed)

1. **Overview** — 5 repos, ingestion health, and the alerts: bus-factor on `ledger/reconcile.py`, inactive owner
   (145 days), conflicting error-format ADRs, an override with and without a record, a reuse candidate.
2. **Feature Planner** — request: *"Add support for partial refunds on captured payments (PAY-142)"*.
   It names one API; the plan surfaces **payments-api (primary)**, ledger-core, notify-svc, customer-portal.
3. **Governing decisions** — ADR-007 (outbox), ADR-004, ADR-003; **ADR-002 is absent** because it is superseded.
4. **Risks** — LED-88 widening migration blocks the feature; `ledger_client.py` still cites superseded ADR-002;
   Dana (sole owner of reconcile) has been inactive; notify-svc de-dupe duplicates `IdempotencyStore`.
5. **Evidence inspector** — click any chip: source, evidence type, status. Inferred items are labelled inferred.
6. **Tasks** — T1 confirm LED-88 first; ledger/notify before payments; portal last. Approve the plan.
7. **Graph** — click payments-api: verified dependency edges with the source line that produced them.
8. **Knowledge** — only validated facts are `active`; candidates can be promoted/rejected; run `/override ADR-004`.
9. **MCP** — `POST /mcp` `tools/call create_feature_plan` returns the same plan for a coding agent.

Fallback: everything above runs from the seeded DB with the offline provider; Vertex is optional polish.
Out-of-scope request ("Train a recommendation model…") returns *insufficient evidence* instead of a plan.
