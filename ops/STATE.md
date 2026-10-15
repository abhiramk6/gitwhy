# Agent state (resume point)

Updated: 2026-10-15

## Done
- Environment probed: headless Ubuntu 24.04, 3.8 GB RAM, 47 GB disk; git + python3 + curl only.
- Cleaned plan written: docs/PLAN.md
- Telegram scaffolding written: ops/notify.sh, ops/get_chat_id.sh (waiting for bot token)

## Blocked on owner
- Telegram bot token (BotFather)
- GCP account + free-trial activation (phone + card)
- GitHub account (private repo)
- Decisions D1-D8 confirmation

## Next (once unblocked)
1. Install toolchain: node, gcloud, gh, postgres+pgvector (local), docker if needed
2. Stage 0 foundation

## Channel
- Telegram is the primary channel (bot @<project bot>, owner chat paired 2026-10-15).
- Replies arrive via ops/poll_telegram.sh under Monitor (30 min max per arm; re-arm on expiry).
- Only messages from the paired chat id are acted on.
- Checklist sent to Telegram; waiting on: new bot token, GitHub, GCP trial, gcloud login.
- Group "Cb" paired 2026-10-15 on explicit owner confirmation typed in terminal. Updates go to the group
  (ops/notify.sh); NOTIFY_DM=1 forces DM. Instructions/approvals accepted ONLY from the owner's user id.
- Approvals for billable/outward actions must still be typed in the terminal session (Telegram events are
  delivered as background events, not user input).
