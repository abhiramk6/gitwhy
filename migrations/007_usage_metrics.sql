-- What people did with the product and what they said about it: the raw material of the results dashboard.
CREATE TABLE IF NOT EXISTS usage_events (
  id              BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,
  kind            TEXT NOT NULL,            -- ask | review | plan | handover | impact | departure
  duration_ms     INTEGER,
  detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_events_org_kind ON usage_events (organization_id, kind, created_at);

-- A person's verdict on one answer. Rated by a human, so it is the only source of "answer correctness".
CREATE TABLE IF NOT EXISTS answer_feedback (
  id              BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  event_id        BIGINT NOT NULL REFERENCES usage_events(id) ON DELETE CASCADE,
  user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,
  resolved        BOOLEAN NOT NULL,
  correct         TEXT NOT NULL CHECK (correct IN ('yes','no','unsure')),
  onboarding      BOOLEAN NOT NULL DEFAULT false,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (event_id, user_id)
);

-- Stopwatch tasks: the same question found by hand (manual) and with the product (gitwhy). Seconds are measured, not guessed.
CREATE TABLE IF NOT EXISTS timed_tasks (
  id              BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,
  task            TEXT NOT NULL,
  arm             TEXT NOT NULL CHECK (arm IN ('manual','gitwhy')),
  seconds         NUMERIC(8,1) NOT NULL CHECK (seconds >= 0 AND seconds < 86400),
  found           BOOLEAN NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS timed_tasks_org ON timed_tasks (organization_id, task, arm);
