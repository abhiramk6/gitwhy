"""Prompts and output schemas for every model judgment. One place, so behaviour is reviewable.

Design rules shared by all tasks:
- The model only sees evidence we pass in and must cite it by id; ids that were not supplied are discarded.
- The model never assigns trust labels. 'verified'/'inferred' derive from the cited evidence's own type/status.
- When evidence is insufficient the model must say so rather than guess.
"""

QUERY_ANALYSIS = {
    "system": (
        "You analyse a question about a software organization's repositories, tickets, pull requests, decisions "
        "(ADRs) and docs, to drive search. Return: the intent in one sentence; 1-5 search queries (keywords, "
        "phrases, synonyms, and exact symbol or file names that would literally appear in the sources); exact "
        "identifiers named in the question (ticket keys, ADR ids, config keys, function or class names); and a "
        "short hypothetical passage that would answer the question (used for semantic matching). Do not answer "
        "the question. Do not invent identifiers that are not in the question."),
    "schema": {"type": "object", "properties": {
        "intent": {"type": "string"},
        "search_queries": {"type": "array", "items": {"type": "string"}},
        "identifiers": {"type": "array", "items": {"type": "string"}},
        "answer_sketch": {"type": "string"}},
        "required": ["intent", "search_queries", "identifiers", "answer_sketch"]},
}

RERANK = {
    "system": (
        "You judge how well each candidate source helps answer the query. Grade every candidate: 3 = directly "
        "answers or is the authoritative source; 2 = strongly relevant context; 1 = weakly related; 0 = not "
        "relevant. Superseded decisions are history: grade them by whether the query asks about history, and "
        "prefer the current decision when the query asks what to do. Return one entry per candidate id."),
    "schema": {"type": "object", "properties": {"ranked": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "relevance": {"type": "integer"}, "reason": {"type": "string"}},
        "required": ["id", "relevance", "reason"]}}}, "required": ["ranked"]},
}

SELECT_SERVICES = {
    "system": (
        "Given a feature request, a catalog of services (repositories) and retrieved evidence, choose which "
        "services the request primarily changes. Use only catalog names. Cite the evidence ids that justify each "
        "choice. If the evidence does not let you link the request to any service, set insufficient_evidence=true "
        "and explain; do not guess."),
    "schema": {"type": "object", "properties": {
        "primary_services": {"type": "array", "items": {"type": "object", "properties": {
            "service": {"type": "string"}, "reason": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}},
            "required": ["service", "reason", "evidence"]}},
        "insufficient_evidence": {"type": "boolean"}, "explanation": {"type": "string"}},
        "required": ["primary_services", "insufficient_evidence", "explanation"]},
}

PLAN = {
    "system": (
        "You produce an evidence-bound implementation plan for a feature request. You are given: the services in "
        "scope with their dependency relationships, candidate decisions (ADRs, with status), candidate risks and "
        "facts, and retrieved evidence. Rules: (1) cite evidence ids for every decision, risk and component "
        "judgment; (2) a superseded decision is not guidance: apply the superseding one and flag code still "
        "following the old one; (3) judge relevance — omit candidates that do not matter for this request instead "
        "of listing everything; (4) tasks, tests and questions are proposals: make them specific to this request "
        "and the cited evidence, order them with depends_on, and do not restate generic boilerplate; (5) if "
        "something needed is unknown, put it in open_questions; (6) never invent ids, services or decisions; "
        "(7) for EVERY active decision, ask whether the request touches the thing it governs (data formats and "
        "representations, error handling, outbound calls, messaging, idempotency, security) and include it when it "
        "does, even if its title does not repeat the request's words; (8) review every entry in "
        "code_citing_superseded_decisions: when that code sits in a service the request changes or depends on, "
        "report it as a risk of type 'stale_reference' saying which superseded decision it still follows and which "
        "decision replaced it; (9) review every reuse_candidates entry: when the request would add or extend "
        "functionality that an existing component already provides, or that two components duplicate, report it "
        "under reuse and name the component to use. 'reuse' means existing code to reuse, never planned work."),
    "schema": {"type": "object", "properties": {
        "components": {"type": "array", "items": {"type": "object", "properties": {
            "service": {"type": "string"}, "needs_change": {"type": "string"}, "reason": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}},
            "required": ["service", "needs_change", "reason", "evidence"]}},
        "decisions": {"type": "array", "items": {"type": "object", "properties": {
            "adr": {"type": "string"}, "guidance": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["adr", "guidance", "evidence"]}},
        "risks": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"type": "string"}, "summary": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["type", "summary", "evidence"]}},
        "reuse": {"type": "array", "items": {"type": "object", "properties": {
            "summary": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}},
            "required": ["summary", "evidence"]}},
        "tasks": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "title": {"type": "string"}, "service": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}}, "rationale": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}},
            "required": ["id", "title", "service", "depends_on", "rationale", "evidence"]}},
        "tests": {"type": "array", "items": {"type": "object", "properties": {
            "service": {"type": "string"}, "check": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["service", "check", "evidence"]}},
        "open_questions": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}},
            "required": ["question", "evidence"]}}},
        "required": ["components", "decisions", "risks", "reuse", "tasks", "tests", "open_questions"]},
}

DECISION_PAIRS = {
    "system": (
        "For each pair of architecture decisions, decide their relationship: 'conflict' (both are active and "
        "give incompatible guidance where their scopes overlap or could be confused), 'supersedes' (the first "
        "replaces the second), 'complementary', or 'unrelated'. Quote the sentence from each decision that "
        "supports a 'conflict' or 'supersedes' verdict."),
    "schema": {"type": "object", "properties": {"pairs": {"type": "array", "items": {"type": "object", "properties": {
        "a": {"type": "string"}, "b": {"type": "string"}, "relation": {"type": "string"}, "reason": {"type": "string"},
        "quote_a": {"type": "string"}, "quote_b": {"type": "string"}},
        "required": ["a", "b", "relation", "reason", "quote_a", "quote_b"]}}}, "required": ["pairs"]},
}

PR_COMPLIANCE = {
    "system": (
        "For each pull request, check it against the listed decisions that could apply to it. Verdict per "
        "(pull request, decision): 'complies', 'violates', or 'not_applicable'. For 'violates', say whether the "
        "pull request description explicitly records a deliberate exception (an override) and quote the exact "
        "words. Only report a violation you can justify from the pull request title, description or changed "
        "files; if the text gives no basis, answer 'not_applicable'."),
    "schema": {"type": "object", "properties": {"findings": {"type": "array", "items": {"type": "object", "properties": {
        "pr": {"type": "string"}, "adr": {"type": "string"}, "verdict": {"type": "string"},
        "override_recorded": {"type": "boolean"}, "override_quote": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["pr", "adr", "verdict", "override_recorded", "override_quote", "reason"]}}},
        "required": ["findings"]},
}

REUSE_PAIRS = {
    "system": (
        "You are given class signatures (name, module, public methods) from several repositories. Identify pairs "
        "from DIFFERENT repositories where one class appears to re-implement the other (same responsibility and "
        "interface), so the team should reuse one implementation. Be conservative: similar method names alone are "
        "not enough. Return an empty list if none."),
    "schema": {"type": "object", "properties": {"pairs": {"type": "array", "items": {"type": "object", "properties": {
        "existing": {"type": "string"}, "duplicate": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["existing", "duplicate", "reason"]}}}, "required": ["pairs"]},
}
