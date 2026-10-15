from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql://lore@127.0.0.1:5432/lore"
    environment: str = "local"
    demo_mode: bool = True  # deterministic fixtures + cached model output when True
    org_slug: str = "northwind"
    # Shared demo token for write endpoints and /mcp. Empty is only accepted when environment == "local".
    demo_token: str = ""
    provider: str = "offline"  # offline | vertex
    gcp_project: str = ""
    gcp_location: str = "us-central1"
    # Model names must be confirmed in the Vertex console at deploy time (Stage 6).
    gen_model: str = "gemini-2.5-flash"
    embed_model: str = "text-embedding-005"


@lru_cache
def get_settings() -> Settings:
    return Settings()
