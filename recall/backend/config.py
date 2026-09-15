from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Moss
    moss_project_id: str
    moss_project_key: str
    moss_index_name: str = "recall-workspace"

    # Ingest to Moss Cloud is opt-in. Queries still use the shared index.
    moss_sync_enabled: bool = False

    # LLM — Groq (OpenAI-compatible, fast inference)
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"

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
    cors_origins: str = "http://localhost:5175,http://127.0.0.1:5175,http://localhost:5173,http://localhost:3000"
    benchmark_cache_ttl_s: int = 180

    @property
    def allowed_domains_list(self) -> list[str]:
        return [d.strip() for d in self.allowed_domains.split(",")]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
