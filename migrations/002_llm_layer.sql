-- LLM layer: cached/replayable model judgments and chunk-level embeddings (no more "first 2000 chars only").
CREATE TABLE IF NOT EXISTS llm_judgments (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  task TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  output JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (organization_id, task, input_hash, model)
);

ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS chunk_index INT NOT NULL DEFAULT 0;
ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS chunk_start INT NOT NULL DEFAULT 0;
ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS chunk_end INT;
ALTER TABLE embeddings DROP CONSTRAINT IF EXISTS embeddings_owner_table_owner_id_model_key;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'embeddings_chunk_uk') THEN
    ALTER TABLE embeddings ADD CONSTRAINT embeddings_chunk_uk UNIQUE (owner_table, owner_id, model, chunk_index);
  END IF;
END $$;
