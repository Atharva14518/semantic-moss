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
    # Keep each agent call safely below Groq's 1,000 OTPM trial limit.
    groq_max_tokens: int = 512

    # LiveKit - the sole realtime transport for workspace events.
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Postgres
    database_url: str = "postgresql://recall:recallpass@postgres:5432/recall"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "recall-cold"

    # Security
    secret_key: str = "change_me"
    allowed_domains: str = "wikipedia.org,github.com,docs.python.org,nodejs.org"

    # App
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
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
