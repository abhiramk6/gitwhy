# LORE Intelligence — UX plan (v1, for review)

Companion to `PRODUCT.md`. Design direction follows the `frontend-design` skill.

## Design plan

**Subject.** An engineering organization's memory. Audience: engineers, reviewers, managers. Primary job: *trust an answer
because you can see exactly where it came from, who said it and when.* Vernacular: stratigraphy / core samples — layers
of time, a sample pulled from the ground with every layer dated and labelled.

**The one memorable thing — the Provenance Column.** Every claim anywhere in the product carries a *source tag*
(`type glyph · who · when`, e.g. `thread · Priya · Jun 8`). Selecting a tag opens the **Provenance Column** on the
right: the original words, highlighted, the surrounding thread, and the chain that led here (code → PR → thread →
ticket → decision) drawn as a dated vertical core sample. Everything else is quiet.

**Evidence span.** Under every answer, plan and review sits a thin time axis showing where its sources fall (oldest → newest):
one tick per source, colored by type. "Depth of knowledge" becomes visible: *12 sources across 5 months, oldest is a review
thread*.

**Palette (named, hex).**
- Chalk `#EDF0F2` (page), Paper `#FAFBFC` (reading surface), Ink `#18222D` (text), Slate `#5B6B7A` (secondary)
- Lapis `#2D3FA6` (citations and links, the signature color), Lichen `#4F7A36` (verified), Ochre `#B27316` (inferred / candidate),
  Madder `#A3303C` (superseded, conflicts, discarded)
- Dark mode: Basalt `#10161C` page, `#171F27` surface, `#E4E9ED` text, citations `#8E9CFF`.
- Source-type colors are tints of the four above plus Moss `#2F7F77` (code) and Plum `#7A4A8C` (people), used only on tags/ticks.

**Type.** Headings: *Bricolage Grotesque* (600, slightly condensed feel, personality). Body/UI: *Public Sans* (400/500/600), tabular numerals
for dates and counts. Code excerpts only: *JetBrains Mono*. Scale 12/14/16/20/28/40; line length ≤ 72ch in reading panes.
No all-caps labels, no eyebrow text above headings, sentence case everywhere.

**Layout.** Three columns on wide screens: slim rail (nav, 72px, icon + short label) · working surface (fluid, max 760px
reading width) · Provenance Column (420px, collapsible; becomes a bottom sheet under 1000px). Left-aligned. No grid of identical
rounded cards: sections are separated by rules and whitespace, radii differ by role (tags 4px, inputs 8px, drawer 0 on the
open edge).

**Motion.** One orchestrated moment: when an answer finishes, its tags land one after another and the evidence span draws
left→right. Opening the column slides it in. Nothing else animates; `prefers-reduced-motion` respected.

**Quality floor.** Keyboard: all tags focusable, `Esc` closes the column, `/` focuses the question box. Contrast ≥ 4.5:1.
Responsive down to 390px. Dark mode.

## Information architecture

| Rail item | Purpose | Flow |
|---|---|---|
| Ask | Chat with citations | F1 |
| Plan | Feature request → cited plan | F2 |
| Review | Pick a PR → drafted, cited review comments | F3 |
| Memory | Standards remembered from review threads, with timeline and verdict | F4 |
| People | Who knows what; handover brief | F5 |
| Trace | Why does this file look like this? | F7 |
| Sources | What was read, counts, embedding model/coverage, dropped items | F6 |
| Map | Service dependency graph (existing) | — |

## Flows

**F1 Ask** — Open the app (lands on Ask). Header says which organization and how much it has read (e.g. "Northwind Labs · 5 repos ·
42 tickets · 56 PRs · 13 review comments"). Starter questions come from the data (e.g. a remembered standard). Type question →
answer streams statement by statement; each statement ends with source tags → click a tag → Provenance Column shows the original
comment/PR/ticket/code with the cited words highlighted + chain. Under the answer: evidence span, "Not enough evidence" state when
the guard drops everything (tells what's missing), three follow-up questions. History stays in the thread. Empty state: three data-derived examples.
Error states: model unavailable → says Ask needs a model and that search still works; quota → says which resets when.

**F2 Plan** — Describe the feature → plan appears: affected services (including ones not named), applicable decisions
(superseded ones excluded and shown as such), risks, reuse, ordered tasks, tests, open questions; every line has tags. Approve / reject.

**F3 Review a PR** — Left list of recent PRs (repo, title, author, date, files); choose one → "Draft review" → comments grouped by type,
each with file, text, quoted source words, tags; discarded items listed with the reason (transparency). Banner: "Draft. Nothing is posted anywhere."
The moment: PR #11 gets a comment "Priya Raman said in June not to use offset pagination" with the thread one click away.

**F4 Memory** — List of remembered standards (topic, who/when/where, scope). Select → timeline (core sample): original thread at the bottom
(oldest), later mentions above (restates / follows / conflicts / replaces), a verdict at the top (holds / contradicted / replaced / unclear)
with the records that justify it. The column shows any item's full text.

**F5 People** — Roster sorted by how much knowledge is concentrated. Select a person → areas (bars: their share of commits, with who else
knows), reviews and standards they set, open tickets, last activity; "Prepare handover" → brief with sections (only they know, standards,
open work, people to ask, risks, first week), every item tagged.

**F6 Sources** — Per source type: count read, last sync; embedding model and per-tier coverage; what was dropped and why; plain statement of limits
(e.g. file-level only, no diffs).

**F7 Trace** — Search/pick a file → profile (functions, comments, style numbers) + dated trail (commits, PRs, threads, tickets, decisions).

## Three demo moments (the pitch)
1. *Ask:* "How should I paginate a new list endpoint in payments-api?" → cursor pagination, cited to Priya's June review thread, shown with the thread.
2. *Review:* payments-api#11 → draft comment citing the same thread; it appears with no mention of that thread in the PR.
3. *People:* "Dana Okafor is inactive" → handover brief: reconcile.py is 100% hers, LED-71 open, who to ask.

## Questions for the reviewer
Is the flow set complete and in a sensible order? Where would a first-time user get lost? Are the empty/error states enough? Is anything
in the visual plan generic rather than chosen for this subject? What is missing from the demo?
