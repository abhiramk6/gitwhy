from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql://lore@127.0.0.1:5432/lore"
    environment: str = "local"
    demo_mode: bool = True  # deterministic fixtures + cached model output when True


@lru_cache
def get_settings() -> Settings:
    return Settings()
