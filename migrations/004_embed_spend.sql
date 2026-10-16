-- Estimated paid-tier embedding spend (tokens, over-estimated at 3 chars/token). Only batches the API accepted are counted.
CREATE TABLE IF NOT EXISTS embed_spend (
  model      TEXT PRIMARY KEY,
  est_tokens BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
