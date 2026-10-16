# Gitwhy: why your code is the way it is
Pitch deck, text only. Every claim here is something the product does today unless marked (planned).

---
## 1. Title
**Gitwhy.** Ask your engineering history. Every answer shows its proof.

## 2. The problem
- The reasons behind code live in places nobody searches: review threads from months ago, ticket comments, commit messages, a PR description.
- A reviewer said "never use offset pagination" in June. In September a new PR does exactly that, and nobody remembers the thread.
- When an engineer leaves, what they uniquely know leaves with them. Handover is a guess.
- Chatbots over code can sound right and be wrong. Teams cannot act on an answer with no source.

## 3. The solution
Gitwhy reads an organization's GitHub (code, commits, pull requests, review comments) and Jira (tickets and comments), then:
- **Answers** "why" and "how do we" questions, led by a one-sentence bottom line.
- **Shows proof**: the exact words, who said them, when. Click to open the original, highlighted.
- **Checks pull requests** against what reviewers said before.
- **Remembers standards** nobody wrote down, and tells you if later work kept to them.
- **Maps who knows what**, and writes a handover brief for a successor.

## 4. The rule that makes it trustworthy
No claim without a citation. A statement with no valid source is dropped before you see it. Quotes must appear word for word in the cited source. Labels (verified, inferred, replaced) come from the evidence, not from the model. Drafts stay local: nothing is ever posted to GitHub or Jira.

## 5. Product tour (7 screens)
1. **Ask**: bottom line, proof cards, follow-ups.
2. **Review**: a PR and the comment "a reviewer already said this", with the old thread as proof.
3. **Memory**: a standard set once in a thread, its verdict (still holds / contradicted / replaced), a three-sentence story.
4. **People**: one-sentence handover summary, only-they-know areas, open work, who to ask, first-week actions.
5. **Plan**: a feature request to affected services, applicable decisions, risks, an ordered task list, each with sources.
6. **Trace**: why a file looks the way it does, in plain words.
7. **Sources**: what was read, how much, and the honest limits.

## 6. The three-minute demo
1. Ask "What is our rule on cursor pagination, and who set it?" The answer cites a June review thread.
2. Open Review on a September PR that adds offset pagination. The draft comment quotes the June thread, though the PR never mentions it.
3. Open Memory on the same standard: verdict "contradicted by later work".
4. Open People on an engineer inactive since April: a handover brief with the files only they touched and the tickets still open.

## 7. How it works
- **Read**: GitHub (shallow clone, PRs, issues, review discussion) and Jira, bounded and counted; every drop is reported.
- **Understand**: a knowledge graph (services, decisions, ownership, dependencies) plus model judgments checked by guards.
- **Remember**: reviewer guidance extracted with the exact quote; later records placed against it.
- **Answer**: hybrid search (keyword, vector, graph) with model query analysis and reranking, then a cited write-up.
- **Guard**: ids must exist, quotes must be literal, highlights must be real text, labels derive from evidence.

## 8. Onboarding a new organization (built)
Sign up, name the organization, connect GitHub (read-only token, choose repositories), connect Jira (optional), then watch a live status page (reading GitHub, reading Jira, connecting the dots, building the search index). When done the app opens on the organization's own data. Tokens are stored outside the database. A test account opens a sample organization.

## 9. Technology
Python and FastAPI, Postgres with pgvector, React. Gemini for reading and writing, Voyage for search vectors, both swappable behind one provider interface. An MCP endpoint lets IDE agents query the same knowledge. Runs on a single VM today; a Cloud Run and Cloud SQL deployment path is prepared (not used).

## 10. What is verified
- 90+ automated tests, including guards, isolation between organizations, and the sync job.
- Live runs on a synthetic organization (planted scenarios) and on real public repositories (Flask, Werkzeug, Jinja, Click, MarkupSafe, ItsDangerous, Requests, urllib3).
- A held-out evaluation set is frozen but has not been run (planned, needs the full index first).
- Quality at scale and with a stronger model is not yet measured.

## 11. Honest limits
- Pull requests are read at file level; diffs are not ingested, so reviews never claim line-level facts.
- Python code is understood structurally; other languages are searchable text.
- Free-tier model quotas make big organizations slow; paid quotas fix this.
- Customer data is sent to the model providers; customers must accept that.
- Today's answers come from a small model because the stronger ones are out of free quota.

## 12. Roadmap
- Now: onboarding, public link, test organization.
- Next: held-out evaluation and a stronger-model comparison; GitHub webhooks and nightly sync; diffs for line-level review.
- Later: more languages, more sources (Slack, Confluence), roles and audit, paid tiers.

## 13. Ask
Try the test organization, then onboard a real repository. Tell us which question your team asks most often.
