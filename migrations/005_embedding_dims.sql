-- Embeddings may come from models with different dimensions (gemini-embedding-001 = 768, voyage-4 = 1024). Each model's
-- vectors live in their own corpus slice (queries always filter on model); a single fixed-size HNSW index cannot span
-- dimensions, and exact search over a few thousand chunks per org is fast. Production can add a per-model partial index:
--   CREATE INDEX ... USING hnsw ((embedding::vector(1024)) vector_cosine_ops) WHERE model = '<name>';
DROP INDEX IF EXISTS embeddings_hnsw_idx;
ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector;
