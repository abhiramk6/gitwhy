# LORE Intelligence — product definition

**One sentence:** the memory of an engineering organization — it has read every PR, review comment, ticket, commit, doc and line of
code, and it answers (and reviews) with the exact source of every claim.

## Who it is for
| Person | Job to be done |
|---|---|
| Engineer starting a feature | "How do we build this here? What did we decide before? What will I break?" |
| Reviewer | "Is this PR consistent with what we agreed, and who said what, when?" |
| Engineering manager | "Someone is leaving — what do they uniquely know, and where is it written down?" |
| New hire | "How does this team write code, and why?" |

## Features (owner-confirmed ones marked ●, proposed ○)
1. ● **Ask** — chatbot for feature support. Free-form questions; every answer sentence carries citations that open the source
   (PR, review comment, ticket, ADR, code span) with author and date.
2. ● **Review** — feature plans and PR reviews checked against past decisions, review comments and code patterns; each finding
   links to the thing that makes it true. Drafts stay local; nothing is posted to GitHub.
3. ● **Knowledge map ("engineer replacement")** — per person: areas they own, decisions they made, reviews they gave, code only they
   touch, and a *handover brief* for when they leave. Gaps ("only one person knows this") are called out.
4. ● **Deep ingestion** — PR titles/descriptions/review comments, issue comments, commits, code, code comments, function and naming
   styles, docs, ADRs. Ingestion status shows what was read and what was dropped, and why.
5. ○ **Memory timeline** — the "three months ago a reviewer said don't use X" case: a standard or objection surfaced from a PR thread,
   shown with who/when/where, whether it still holds, and which later work followed or ignored it.
6. ○ **Conventions** — "how we write X" (errors, naming, tests, HTTP calls) mined from code and review history with cited examples.
7. ○ **Code archaeology** — "why does this code look like this?" walk: code → PR → review thread → ticket → ADR.
8. ○ **Staleness alerts** — superseded decisions still cited in code; contradictions between sources.
9. ○ **MCP access** — the same answers inside IDE agents (exists).

## Trust rules (non-negotiable)
- No claim without a citation that exists. Trust labels (verified / inferred / proposed) are derived from the evidence, never from the model.
- "Say nothing rather than guess": when evidence is thin the product says so.
- Everything judged (relevance, conflicts, violations, intent) is a model judgment constrained by an evidence guard. Rule-based code only
  parses, counts, traverses and fuses rankings.
- Local-only drafts; no write to external services.

## User flows (screens captured for the owner are exactly these)
| # | Flow | Steps | The moment that should land |
|---|---|---|---|
| F1 | Ask a question | Home → type question → streamed answer with numbered citations → open a citation in the side drawer (full thread, author, date, link) | A reviewer comment from months ago appears as the reason behind an answer |
| F2 | Review a feature request | Plan → describe feature → plan with affected services, decisions, risks, reuse, tasks → click any claim → evidence trail | A decision the request never mentioned is applied, and superseded ones are excluded |
| F3 | Review a PR | Reviews → pick PR → drafted comments each with evidence → discard/keep | "Don't use X" from a 3-month-old thread flagged on a new PR |
| F4 | Memory timeline | Memory → standard or topic → timeline of mentions (PR thread, ADR, plan) with status | One standard traced across threads, ADRs and later PRs |
| F5 | Knowledge map | People → pick engineer → areas, evidence, risk if they leave → handover brief | A single-owner area with exact evidence |
| F6 | Ingestion health | Sources → what was read, counts per type, dropped items and reasons | Honesty about coverage |

## Design brief (for the UI)
Subject: engineering archaeology. Evidence is the hero: the citation *is* the interface. Every claim shows its provenance chain
(source type, author, date, location) and opens a drawer with the original text, highlighted. Distinct, not template; quiet
elsewhere and bold in one place: the citation trail.
