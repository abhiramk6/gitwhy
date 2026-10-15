-- Daily free-tier embedding budget accounting. Counts only items the API accepted (a failed request is not counted).
CREATE TABLE IF NOT EXISTS embed_usage (
  day   DATE NOT NULL,
  model TEXT NOT NULL,
  kind  TEXT NOT NULL CHECK (kind IN ('index', 'query')),
  items INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, model, kind)
);
-- A model whose daily cap was hit: do not call it again before this instant (the API's own RetryInfo).
CREATE TABLE IF NOT EXISTS quota_state (
  model           TEXT PRIMARY KEY,
  exhausted_until TIMESTAMPTZ NOT NULL,
  note            TEXT,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
