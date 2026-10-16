from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql://gitwhy@127.0.0.1:5432/gitwhy"
    environment: str = "local"
    demo_mode: bool = True  # model judgments are cached in llm_judgments and replayed when present
    org_slug: str = "northwind"
    # Shared demo token for write endpoints and /mcp. Empty is only accepted when environment == "local".
    demo_token: str = ""

    # offline: no model. Search is lexical only; judgments (planning, conflicts, compliance, reuse) are unavailable.
    # gemini: Gemini Developer API with GEMINI_API_KEY.  vertex: Vertex AI with application default credentials.
    provider: str = "offline"  # offline | gemini | vertex
    gemini_api_key: str = ""
    # Backup key (another project, own free-tier quota): generation + query embeddings fall back to it.
    gemini_api_key_backup: str = ""
    # Owner decision pending: whether INDEX embeddings may also use the backup key (faster than plan A).
    embed_backup_for_index: bool = False
    gcp_project: str = ""
    gcp_location: str = "us-central1"
    # Confirmed against the live Gemini API (models.list) on 2026-10-15; 2.5 models are retired for new users; newest generation only.
    # Vertex uses its own embedding names (e.g. text-embedding-005): set EMBED_MODEL when PROVIDER=vertex.
    gen_model: str = "gemini-3.8-flash"
    gen_fallback_models: str = "gemini-3.7-flash,gemini-3.5-flash-lite"  # comma separated; tried when the primary is overloaded
    embed_model: str = "gemini-embedding-2"

    # Free-tier embedding cap is 1,000 items/day/model: index at most this many per day, reserve the rest for queries.
    embed_daily_budget: int = 900
    embed_query_reserve: int = 100
    # Accounts and onboarding. With auth_required=false (default) the app serves the single configured org with no login.
    auth_required: bool = False
    session_secret: str = ""            # prefer GITWHY_SESSION_SECRET or the generated file in secrets_dir
    secrets_dir: str = "~/.config/gitwhy/org-secrets"  # per-organization tokens (mode 600); production: Secret Manager
    llm_calls_per_hour: int = 60        # per signed-in user, on endpoints that call a model
    sync_embed: bool = False            # embed during an organization's sync (slow on free-tier model quotas)
    sync_max_prs: int = 150
    sync_max_issues: int = 150
    sync_max_threads: int = 100
    sync_max_commits: int = 300
    # Embeddings may come from a different provider than generation. "voyage" = Voyage AI (free 200M tokens/account).
    # Voyage dims are 256/512/1024/2048 (not 768); a new model means a new corpus, never mixed with another model's vectors.
    embed_provider: str = "gemini"
    voyage_api_key: str = ""
    voyage_model: str = "voyage-4-large"
    voyage_dim: int = 1024
    voyage_tokens_per_min: int = 0      # 0 = unpaced; set from the observed account limit
    voyage_request_tokens: int = 20000  # estimated tokens per request
    voyage_requests_per_min: int = 0
    # Paid tier (only after the owner enabled billing): no daily item cap, but a hard dollar cap on estimated spend.
    # Tokens are over-estimated (3 chars/token), so the real bill is at or below the estimate.
    embed_paid: bool = False
    embed_max_usd: float = 0.50
    embed_price_per_mtok: float = 0.15  # USD per 1M input tokens, remembered list price for gemini-embedding-001, unverified

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
