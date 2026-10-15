# ADR-007: Ledger writes are published through a transactional outbox

Status: accepted
Supersedes: ADR-002
Date: 2026-06-02
Scope: ledger-core, payments-api
Topic: service-communication

Ledger-affecting events are written to an outbox and delivered asynchronously. Direct synchronous calls from payments to ledger are deprecated.
