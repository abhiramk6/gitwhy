-- LORE Intelligence: initial schema (Stage 0).
-- Three layers: raw evidence (source_records), canonical graph (entities/edges), curated knowledge (facts).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE organizations (
  id          BIGSERIAL PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE repositories (
  id           BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  url          TEXT,
  default_branch TEXT NOT NULL DEFAULT 'main',
  language     TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organization_id, name)
);

-- Raw evidence. Idempotent on (org, source_type, source_id); content_hash detects change.
CREATE TABLE source_records (
  id           BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  repository_id BIGINT REFERENCES repositories(id) ON DELETE SET NULL,
  source_type  TEXT NOT NULL,            -- github_pr | github_commit | jira_issue | adr | doc | file
  source_id    TEXT NOT NULL,            -- stable id within the source system
  source_url   TEXT,
  title        TEXT,
  body         TEXT,
  payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_hash TEXT NOT NULL,
  observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  search_tsv   TSVECTOR GENERATED ALWAYS AS
    (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))) STORED,
  UNIQUE (organization_id, source_type, source_id)
);
CREATE INDEX source_records_tsv_idx ON source_records USING GIN (search_tsv);
CREATE INDEX source_records_repo_idx ON source_records (repository_id);

-- Canonical entities (repo, service, module, symbol, endpoint, team, person, decision, ticket, ...).
CREATE TABLE entities (
  id           BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  repository_id BIGINT REFERENCES repositories(id) ON DELETE SET NULL,
  entity_type  TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  aliases      TEXT[] NOT NULL DEFAULT '{}',
  attributes   JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organization_id, entity_type, canonical_name)
);
CREATE INDEX entities_name_trgm_idx ON entities USING GIN (canonical_name gin_trgm_ops);

-- Typed relationships with provenance, temporal validity and review status.
CREATE TABLE edges (
  id           BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  src_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  dst_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  rel_type     TEXT NOT NULL,             -- imports | calls | depends_on | owns | decided_by | supersedes | ...
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('structural','explicit','inferred')),
  status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('candidate','active','superseded','rejected')),
  confidence   REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
  source_record_id BIGINT REFERENCES source_records(id) ON DELETE SET NULL,
  source_ref   TEXT,                      -- repo path / URL when no source_record exists
  valid_from   TIMESTAMPTZ,
  valid_until  TIMESTAMPTZ,
  observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organization_id, src_id, dst_id, rel_type, evidence_type),
  CHECK (src_id <> dst_id)
);
CREATE INDEX edges_src_idx ON edges (organization_id, src_id) WHERE status = 'active';
CREATE INDEX edges_dst_idx ON edges (organization_id, dst_id) WHERE status = 'active';

-- Curated organizational knowledge (decisions, conventions, risks, lessons, ...).
CREATE TABLE facts (
  id           BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  repository_id BIGINT REFERENCES repositories(id) ON DELETE SET NULL,
  subject_id   BIGINT REFERENCES entities(id) ON DELETE SET NULL,
  fact_type    TEXT NOT NULL,             -- decision | convention | override | risk | lesson | ownership | ...
  predicate    TEXT NOT NULL,
  object_value TEXT NOT NULL,
  summary      TEXT NOT NULL,
  scope        TEXT NOT NULL DEFAULT 'org' CHECK (scope IN ('org','repo','team')),
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('structural','explicit','inferred')),
  status       TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','active','superseded','rejected')),
  confidence   REAL NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
  source_type  TEXT NOT NULL,
  source_id    TEXT NOT NULL,
  source_url   TEXT,
  superseded_by BIGINT REFERENCES facts(id),
  valid_from   TIMESTAMPTZ,
  valid_until  TIMESTAMPTZ,
  observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  author       TEXT,                      -- for /remember and /override
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  search_tsv   TSVECTOR GENERATED ALWAYS AS
    (to_tsvector('english', coalesce(predicate,'') || ' ' || coalesce(object_value,'') || ' ' || coalesce(summary,''))) STORED,
  -- one observation per source per claim; repeated evidence adds source_records, not duplicate facts
  UNIQUE (organization_id, fact_type, predicate, object_value, source_type, source_id)
);
CREATE INDEX facts_tsv_idx ON facts USING GIN (search_tsv);
CREATE INDEX facts_active_idx ON facts (organization_id, fact_type) WHERE status = 'active';

-- Embeddings (Vertex text-embedding-005 => 768 dims). Keyed by owner row + content hash so unchanged content is never re-embedded.
CREATE TABLE embeddings (
  id           BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  owner_table  TEXT NOT NULL CHECK (owner_table IN ('source_records','entities','facts')),
  owner_id     BIGINT NOT NULL,
  content_hash TEXT NOT NULL,
  model        TEXT NOT NULL,
  embedding    vector(768) NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_table, owner_id, model)
);
CREATE INDEX embeddings_hnsw_idx ON embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE ingestion_runs (
  id           BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  source       TEXT NOT NULL,
  mode         TEXT NOT NULL CHECK (mode IN ('backfill','incremental','reconcile')),
  status       TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','succeeded','failed')),
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  records_seen INT NOT NULL DEFAULT 0,
  records_new  INT NOT NULL DEFAULT 0,
  records_changed INT NOT NULL DEFAULT 0,
  error        TEXT
);

CREATE TABLE ingestion_cursors (
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  source       TEXT NOT NULL,
  cursor       TEXT NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, source)
);

CREATE TABLE feature_plans (
  id           BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  request_text TEXT NOT NULL,
  plan         JSONB NOT NULL DEFAULT '{}'::jsonb,
  status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','rejected','implemented')),
  model        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
