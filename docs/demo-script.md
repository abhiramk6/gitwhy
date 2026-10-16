# Demo script (3 minutes, Northwind org, `http://127.0.0.1:8000`)

Setup: `PROVIDER=gemini ORG_SLUG=northwind` (see README). Everything below is live model output over real stored sources.

1. **Ask** — click "What is our rule on cursor pagination, and who set it?". The answer is two cited statements; the first tag
   is a review comment by Priya from June. Click it: the Provenance Column opens with her exact words highlighted, the thread around
   it, the PR it sat on. Say: "nobody wrote this into a decision record — it only exists in a review thread."
2. **Review** — open *Review*, pick `payments-api#11` (Add GET /v1/refunds listing), "Draft review". One comment: a reviewer already
   said not to use offset pagination (quoted, with who and when). The PR description never mentions that thread. "Draft. Nothing is
   posted anywhere."
3. **Memory** — open *Memory*, "Cursor pagination", "Trace what happened since": verdict *Contradicted by later work* (the Sep 9 PR),
   timeline with the original thread at the bottom.
4. **People** — *Dana Okafor* has been inactive since April. "Prepare handover brief": `reconcile.py` is 100% hers (22 of 22 commits),
   LED-71 and LED-88 are open, who else touched the area. Every line is tagged.
5. **Trace** — `notify-svc / notify/dedupe.py`: commits, PRs, and the review thread where a reviewer asked why a second de-dupe store
   exists when `IdempotencyStore` does.
6. **Plan** — "Add support for partial refunds on captured payments (PAY-142)": affected services including ones not named, applicable
   decisions (superseded ones excluded), risks, tasks, each with sources.
7. **Sources** — what was read, which embedding model indexes it, limits stated plainly.

What to say about trust: statements with no valid source are dropped before you see them; labels (verified / inferred) come from the
evidence, not from the model; PR review is file-level (diffs are not ingested); nothing is posted to GitHub.
