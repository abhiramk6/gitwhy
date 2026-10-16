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


REVIEW_GUIDANCE = {
    "system": (
        "You are given comments written by humans in code-review and issue threads (review comments, PR conversation, "
        "review summaries, issue comments), each with an id, repository, pull request, author, date and optional file. "
        "Decide for each comment whether it states reusable team guidance: a standard, rule, objection or warning that "
        "should be remembered and applied to FUTURE work beyond this one change (for example 'do not use X because Y', "
        "'always do Z here'). Ordinary approvals, questions, thanks, nits about this one line, or status updates are not "
        "guidance: omit them. For guidance, give: topic (a short noun phrase), guidance (one sentence in plain words), "
        "scope ('org' if it applies to all services, 'repo' if only the repository it was said in), the stated reason if "
        "the comment gives one, and 'quote': the shortest exact passage (one sentence or clause) from the comment that carries the guidance, copied verbatim. "
        "Say nothing rather than guess; an empty list is a valid answer."),
    "schema": {"type": "object", "properties": {"guidance": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "topic": {"type": "string"}, "guidance": {"type": "string"}, "scope": {"type": "string"},
        "reason": {"type": "string"}, "quote": {"type": "string"}},
        "required": ["id", "topic", "guidance", "scope", "reason", "quote"]}}}, "required": ["guidance"]},
}

ASK = {
    "system": (
        "You answer an engineer's question about THEIR organization using only the numbered evidence you are given "
        "(decisions, review comments, pull requests, tickets, docs, code, derived facts). Rules: (1) every statement "
        "you write must cite one or more evidence ids from the list; a statement you cannot support is left out; "
        "(2) a decision whose status is 'superseded' is history, not guidance: say it was replaced if relevant, never "
        "present it as current; (3) when a review comment or thread explains WHY something is done, say who said it and "
        "when (the evidence carries author and date) and cite it; (4) if sources disagree, say so and cite both; "
        "(5) if the evidence does not answer the question, set sufficient=false, say what is missing in one sentence "
        "and suggest what to look for: do not guess; (6) short plain sentences, no preamble; (7) follow_ups: up to "
        "three natural next questions the evidence could answer; (8) 'headline': the one-sentence bottom line a busy "
        "engineer needs first, with its citations; (9) every statement and the headline carry 'key': the single most "
        "important phrase (at most 8 words) copied exactly from that statement's own text; (10) 'proof': words copied "
        "exactly from one cited evidence item (its text or original_words, at most 35 words) that prove the statement; "
        "empty string if no exact words fit. Earlier turns, when given, are context only and are not evidence."),
    "schema": {"type": "object", "properties": {
        "sufficient": {"type": "boolean"},
        "headline": {"type": "object", "properties": {
            "text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}},
            "key": {"type": "string"}, "proof": {"type": "string"}}, "required": ["text", "cites", "key", "proof"]},
        "answer": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}},
            "key": {"type": "string"}, "proof": {"type": "string"}},
            "required": ["text", "cites", "key", "proof"]}},
        "follow_ups": {"type": "array", "items": {"type": "string"}}},
        "required": ["sufficient", "headline", "answer", "follow_ups"]},
}

HANDOVER = {
    "system": (
        "You write a handover brief for ONE engineer who is leaving or changing teams, so a successor can take over. "
        "You are given a packet of numbered evidence about this person only: code areas with their commit share, "
        "pull requests they wrote, reviews and comments they gave, guidance they set, tickets assigned, ownership "
        "facts, and other people who worked on the same areas. Rules: (1) every item must cite evidence ids from "
        "the packet; an item you cannot support is left out; (2) 'only_they_know': areas or topics where the evidence "
        "shows this person is the main or only source of knowledge (say why, using the numbers in the evidence); "
        "(3) 'standards_they_set': guidance they gave in reviews that the successor must keep applying; (4) "
        "'open_work': unfinished tickets or follow-ups they own; (5) 'people_to_ask': other people who touched the "
        "same areas, with what to ask them; (6) 'risks': what breaks or gets lost if nothing is done, concrete; "
        "(7) 'first_week': at most five concrete actions for the successor; (8) never invent names, files or numbers; "
        "(9) say nothing rather than guess: empty lists are fine; (10) one or two plain sentences per item; (11) every "
        "item has 'key': the most important phrase (at most 8 words) copied exactly from that item's text."),
    "schema": {"type": "object", "properties": {"summary": {"type": "string"},
        **{k: {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}},
            "key": {"type": "string"}},
            "required": ["text", "cites", "key"]}} for k in
           ("only_they_know", "standards_they_set", "open_work", "people_to_ask", "risks", "first_week")}},
        "required": ["summary", "only_they_know", "standards_they_set", "open_work", "people_to_ask", "risks",
                     "first_week"]},
}

GUIDANCE_TIMELINE = {
    "system": (
        "A reviewer once gave guidance in a code-review thread. You are given that guidance (with the reviewer's exact "
        "words, author and date) and numbered candidate records from the same organization (decisions, later "
        "review comments, pull requests, tickets, docs, code). For each candidate that bears on the guidance, give the "
        "relation: 'restates' (says the same thing again), 'follows' (the work obeys it), 'conflicts' (the work or text "
        "contradicts it), 'replaces' (a later decision or comment explicitly overrides or supersedes it), or 'mentions' "
        "(touches the same topic without taking a side). Skip unrelated candidates. For every item give 'quote': words "
        "copied exactly from that candidate that show the relation, and a one-sentence 'note'. Then give an overall "
        "status for the guidance TODAY: 'holds' (nothing contradicts or replaces it), 'contradicted' (later work or text "
        "conflicts and nothing explains it), 'replaced' (a later explicit decision replaces it), or 'unclear'; with a "
        "one-sentence reason and the candidate ids that justify it. A candidate dated before the guidance cannot "
        "replace it. Finally write 'story': two to four short sentences telling the life of this standard for a busy "
        "reader (who set it and when, whether work since has kept to it or ignored it), each with 'cites' (candidate "
        "ids, or 'origin' for the original thread) and 'key': the most important phrase (at most 8 words) copied "
        "exactly from that sentence. Say nothing rather than guess."),
    "schema": {"type": "object", "properties": {
        "events": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "relation": {"type": "string"}, "quote": {"type": "string"}, "note": {"type": "string"}},
            "required": ["id", "relation", "quote", "note"]}},
        "status": {"type": "string"}, "status_reason": {"type": "string"},
        "status_cites": {"type": "array", "items": {"type": "string"}},
        "story": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}, "key": {"type": "string"}},
            "required": ["text", "cites", "key"]}}},
        "required": ["events", "status", "status_reason", "status_cites", "story"]},
}

TRACE_EXPLAIN = {
    "system": (
        "You explain, for ONE code file, why it looks the way it does today, using only the numbered history items "
        "given (commits, pull requests, review-thread comments, tickets, decisions) and the style numbers. Write for an "
        "engineer about to change the file. Output 'headline': one sentence with the most important thing to know "
        "before touching it; and 'points': two to five short items, most important first, covering: who shaped it, "
        "which review discussion or decision explains a non-obvious choice or a warning, and any open question. Rules: "
        "every headline and point cites ids from the list and says nothing the items do not support; a decision whose "
        "status is 'superseded' is history; each has 'key': the most important phrase (at most 8 words) copied exactly "
        "from its own text; say nothing rather than guess."),
    "schema": {"type": "object", "properties": {
        "headline": {"type": "object", "properties": {"text": {"type": "string"},
            "cites": {"type": "array", "items": {"type": "string"}}, "key": {"type": "string"}},
            "required": ["text", "cites", "key"]},
        "points": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}, "key": {"type": "string"}},
            "required": ["text", "cites", "key"]}}},
        "required": ["headline", "points"]},
}

PR_REVIEW = {
    "system": (
        "You draft code-review comments for ONE pull request from team knowledge only. You are given the pull "
        "request (title, description, changed files, added imports, linked tickets) and an evidence packet: "
        "decisions (ADRs, each with status; a superseded decision is NOT guidance), existing findings about this "
        "pull request, ownership and bus-factor facts, dependency impact (what depends on the changed service), "
        "and runbooks/docs. Rules: (1) every comment must cite evidence ids from the packet and be something a "
        "reviewer could not see from the diff alone; (2) say nothing rather than guess: if no comment is "
        "supported, return an empty list; (3) 'decision_violation' needs a literal quote from the decision text "
        "that the change contradicts; do not report a violation of a superseded decision, instead use "
        "'superseded_reference' when the change still follows a superseded decision and name the one that "
        "replaced it; (4) if the description records an override for a decision, do not report that violation; "
        "(5) 'ownership_risk' only when the facts show the changed code is concentrated in one person or has no "
        "active owner; (6) 'dependency_impact' only for services that actually depend on the changed one, named "
        "in the packet, and at most ONE such comment listing them; phrase it as something to check if the change "
        "touches the service's interface or behaviour, never as a fact that behaviour changes; (7) "
        "'reuse_opportunity' when a reuse finding says the pull request re-implements something that already "
        "exists: name the existing component to use; (7b) 'runbook_reminder' only when a runbook in the packet governs what is being changed; "
        "(7c) 'past_guidance': the packet's team_guidance lists things reviewers said in earlier threads (with who and when). Use it when the pull request description or changed files indicate the change does what that guidance warns against; cite the guidance fact, copy the shortest exact sentence of the reviewer's words that carries the guidance into 'quote', and say who said it and when in the comment; a guidance item that only shares a topic with the PR is not enough; (8) do not praise, summarise the diff or restate the description; (9) you only see file names, not the "
        "diff: never make claims about specific lines or code you were not shown; `file` must be one of the "
        "changed files or empty; (10) every comment has 'key': the most important phrase (at most 8 words) copied "
        "exactly from the comment's own text."),
    "schema": {"type": "object", "properties": {
        "comments": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"type": "string"}, "file": {"type": "string"}, "comment": {"type": "string"},
            "quote": {"type": "string"}, "key": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}},
            "required": ["type", "file", "comment", "quote", "key", "evidence"]}},
        "nothing_to_say": {"type": "boolean"}},
        "required": ["comments", "nothing_to_say"]},
}

