from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql://lore@127.0.0.1:5432/lore"
    environment: str = "local"
    demo_mode: bool = True  # model judgments are cached in llm_judgments and replayed when present
    org_slug: str = "northwind"
    # Shared demo token for write endpoints and /mcp. Empty is only accepted when environment == "local".
    demo_token: str = ""

    # offline: no model. Search is lexical only; judgments (planning, conflicts, compliance, reuse) are unavailable.
    # gemini: Gemini Developer API with GEMINI_API_KEY.  vertex: Vertex AI with application default credentials.
    provider: str = "offline"  # offline | gemini | vertex
    gemini_api_key: str = ""
    gcp_project: str = ""
    gcp_location: str = "us-central1"
    # Confirmed against the live Gemini API (models.list) on 2026-10-15; 2.5 models are retired for new users; newest generation only.
    # Vertex uses its own embedding names (e.g. text-embedding-005): set EMBED_MODEL when PROVIDER=vertex.
    gen_model: str = "gemini-3.8-flash"
    gen_fallback_models: str = "gemini-3.7-flash,gemini-3.5-flash-lite"  # comma separated; tried when the primary is overloaded
    embed_model: str = "gemini-embedding-2"

    # Candidate-pool and prompt budgets (cost/latency controls, not relevance rules; relevance is the model's job).
    rerank_pool: int = 30
    evidence_budget_chars: int = 60000
    judge_batch_size: int = 8
    # Bus-factor statistics (computed numbers; the model judges their significance for a given request).
    ownership_min_commits: int = 10
    ownership_min_share: float = 0.9
    dormant_days: int = 90


@lru_cache
def get_settings() -> Settings:
    return Settings()
