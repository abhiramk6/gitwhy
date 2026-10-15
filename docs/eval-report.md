# Evaluation report

Provider: `offline` · Organization: synthetic Northwind Labs · Result: **ALL PASS**

Baselines are measured on the synthetic dataset only; they are not claims about real organizations.

## Retrieval

| Query | Expectation | Result | Rank |
|---|---|---|---|
| PAY-142 | PAY-142 in top 3 | PASS | 1 |
| outbound HTTP must use the platform client with timeouts and retries | ADR-004 in top 5 | PASS | 1 |
| which decision replaced synchronous calls between payments and ledger | ADR-007 in top 5 | PASS | 4 |
| why do errors use problem+json in payments | ADR-005 in top 5 | PASS | 1 |
| duplicate notification sends de-dupe | NTF-27 in top 5 | PASS | 1 |
| settlement file reconcile fails on large files | LED-71 in top 5 | PASS | 1 |
| migrate ledger amounts to wider numeric type | LED-88 in top 5 | PASS | 1 |
| kubernetes helm chart for the mobile app | no relevant results | SKIPPED: offline hashing embeddings cannot reject unsupported queries; verify with the Vertex provider | – |

- hit rate@k: **7/7**; MRR: **0.89**

## Planning

| Case | Check | Result |
|---|---|---|
| Add support for partial refunds on captured payments (PAY-14 | plan | SKIPPED: planning needs an LLM provider (PROVIDER=gemini + GEMINI_API_KEY, or vertex) |
| Add configurable retries to notification delivery in notify- | plan | SKIPPED: planning needs an LLM provider (PROVIDER=gemini + GEMINI_API_KEY, or vertex) |
| Train a recommendation model for advertising banners | plan | SKIPPED: planning needs an LLM provider (PROVIDER=gemini + GEMINI_API_KEY, or vertex) |

- unsupported-claim rate: **0.0%** (0/0 claims)

