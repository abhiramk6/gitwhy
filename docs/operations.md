# Operations

## Control channel
Telegram group "Cb" (bot @<project bot>). Only the owner's Telegram user id can instruct the agent.
tmux session `gitwhy`: `agent`, `bridge` (Telegram -> agent), `shell`, `watchdog` (no-progress alert).
Attach: `tmux attach -t gitwhy` · detach: Ctrl-b d.

## Costs ($300 free-trial credit; never click Upgrade)
- Develop locally; cloud deploy is one step (`deploy/deploy.sh plan|apply`), after the owner approves billable resources.
- `ops/cost_watch.sh` posts an hourly digest and stops Cloud SQL at 80% of the credit. Its spend figure is an
  ESTIMATE (gcloud cannot read credit balance); confirm in console Billing > Credits.
- Biggest recurring item is Cloud SQL: stop it when idle (`gcloud sql instances patch gitwhy-pg --activation-policy=NEVER`).

## Known limitations
- Offline hashing embeddings cannot reject unsupported queries; calibrate `min_similarity` with Vertex.
- Cloud SQL pgvector availability/version, Gemini model names, and the Docker image are unverified until deploy
  (no Docker on the dev box; image is built by Cloud Build).
- Live GitHub/Jira connectors are not built; ingestion reads fixtures behind the same interface.
