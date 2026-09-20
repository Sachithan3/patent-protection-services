"""Typed application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for ClaimGuard AI."""

    database_host: str = "localhost"
    database_port: int = 5433
    database_user: str = "claimguard_user"
    database_password: str = ""
    database_name: str = "claimguard_db"

    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_vector_dimension: int = 384
    embedding_batch_size: int = 32

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = False
    environment: str = "development"
    log_level: str = "INFO"

    seed_data_path: str = "data/seed_patents.json"

    gemini_api_key: str | None = Field(default=None, repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    llm_temperature: float = 0.1
    llm_max_output_tokens: int = 4096

    # Provider layer (migration Phase 1b). Facts and dates: docs/PROVIDERS.md
    pqai_base_url: str = "https://api.projectpq.ai"
    pqai_token: str | None = Field(default=None, repr=False)
    uspto_base_url: str = "https://api.uspto.gov"
    uspto_api_key: str | None = Field(default=None, repr=False)
    patentsview_base_url: str = "https://search.patentsview.org"
    patentsview_api_key: str | None = Field(default=None, repr=False)
    google_patents_base_url: str = "https://patents.google.com"
    enable_epo: bool = False
    provider_timeout_seconds: float = 15.0
    provider_max_attempts: int = 3
    provider_concurrency: int = 4
    provider_user_agent: str = "ClaimGuardAI/1.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def async_database_url(self) -> str:
        """Return the SQLAlchemy asyncpg connection URL."""
        return (
            f"postgresql+asyncpg://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
