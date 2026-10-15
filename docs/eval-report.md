# Evaluation report

Provider: `offline-deterministic` · Organization: synthetic Northwind Labs · Result: **ALL PASS**

Baselines are measured on the synthetic dataset only; they are not claims about real organizations.

## Retrieval

| Query | Expectation | Result | Rank |
|---|---|---|---|
| PAY-142 | PAY-142 in top 3 | PASS | 1 |
| outbound HTTP must use the platform client with timeouts and retries | ADR-004 in top 5 | PASS | 1 |
| which decision replaced synchronous calls between payments and ledger | ADR-007 in top 5 | PASS | 1 |
| why do errors use problem+json in payments | ADR-005 in top 5 | PASS | 1 |
| duplicate notification sends de-dupe | NTF-27 in top 5 | PASS | 3 |
| settlement file reconcile fails on large files | LED-71 in top 5 | PASS | 1 |
| migrate ledger amounts to wider numeric type | LED-88 in top 5 | PASS | 2 |
| kubernetes helm chart for the mobile app | no relevant results | SKIPPED: offline hashing embeddings cannot reject unsupported queries; verify with the Vertex provider | – |

- hit rate@k: **7/7**; MRR: **0.83**

## Planning

| Case | Check | Result |
|---|---|---|
| partial refunds | component payments-api | PASS |
| partial refunds | component ledger-core | PASS |
| partial refunds | component notify-svc | PASS |
| partial refunds | component customer-portal | PASS |
| partial refunds | decision ADR-007 | PASS |
| partial refunds | decision ADR-004 | PASS |
| partial refunds | decision ADR-003 | PASS |
| partial refunds | excludes ADR-002 | PASS |
| partial refunds | risk marker LED-88 | PASS |
| partial refunds | risk marker stale_reference | PASS |
| partial refunds | risk marker dana.okafor | PASS |
| partial refunds | reuse marker IdempotencyStore | PASS |
| partial refunds | no unsupported claims | PASS |
| notification retries | component notify-svc | PASS |
| notification retries | decision ADR-004 | PASS |
| notification retries | excludes ADR-002 | PASS |
| notification retries | no unsupported claims | PASS |
| out of scope | returns insufficient_evidence instead of inventing a plan | PASS |

- unsupported-claim rate: **0.0%** (0/47 claims)

