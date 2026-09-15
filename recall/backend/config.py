from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Moss
    moss_project_id: str
    moss_project_key: str
    moss_index_name: str = "recall-workspace"

    # LLM — xAI Grok
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-4.6"

    # Postgres
    database_url: str = "postgresql://recall:recallpass@postgres:5432/recall"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "recall-cold"

    # Security
    secret_key: str = "change_me"
    allowed_domains: str = "wikipedia.org,github.com,docs.python.org"

    # App
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def allowed_domains_list(self) -> list[str]:
        return [d.strip() for d in self.allowed_domains.split(",")]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
