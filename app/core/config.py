"""Typed application configuration loaded from environment variables.

When running on AWS (APP_AWS_REGION is set), secrets are pulled from
Secrets Manager. Otherwise, falls back to .env file for local development.
"""

import json
import logging
import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_AWS_SECRET_CACHE: dict[str, Any] = {}


def _get_aws_secret(secret_name: str) -> dict[str, Any]:
    """Fetch and cache a JSON secret from AWS Secrets Manager."""
    if secret_name in _AWS_SECRET_CACHE:
        return _AWS_SECRET_CACHE[secret_name]
    region = os.environ.get("APP_AWS_REGION", "ap-southeast-2")
    client = boto3.client("secretsmanager", region_name=region)
    try:
        response = client.get_secret_value(SecretId=secret_name)
        value = json.loads(response["SecretString"])
        _AWS_SECRET_CACHE[secret_name] = value
        return value
    except ClientError as exc:
        raise RuntimeError(
            f"Failed to retrieve secret '{secret_name}' from Secrets Manager: {exc}"
        ) from exc


class Settings(BaseSettings):
    """Runtime configuration for ClaimGuard AI."""

    database_host: str = "localhost"
    database_port: int = 5433
    database_user: str = "claimguard_user"
    database_password: str = ""
    database_name: str = "claimguard_db"

    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_vector_dimension: int = 384
    embedding_batch_size: int = 128

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = False
    environment: str = "development"
    log_level: str = "INFO"

    seed_data_path: str = "data/Patents_data_withclaims.csv"
    gemini_api_key: str | None = Field(default=None, repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: float = 120.0
    llm_temperature: float = 0.1
    llm_max_output_tokens: int = 4096

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


def _load_aws_secrets() -> dict[str, str]:
    """Load DB and Gemini secrets from AWS Secrets Manager."""
    overrides: dict[str, str] = {}
    db_secret_name = os.environ.get("DB_SECRET_NAME", "claimguard/db-credentials")
    gemini_secret_name = os.environ.get("GEMINI_SECRET_NAME", "claimguard/gemini-api-key")

    try:
        db_secret = _get_aws_secret(db_secret_name)
        # The secret stores credentials; host/port/name come from environment.
        if db_secret.get("username"):
            overrides["database_user"] = db_secret["username"]
        if db_secret.get("password"):
            overrides["database_password"] = db_secret["password"]
        if db_secret.get("host"):
            overrides["database_host"] = db_secret["host"]
        if db_secret.get("port"):
            overrides["database_port"] = str(db_secret["port"])
        if db_secret.get("dbname"):
            overrides["database_name"] = db_secret["dbname"]
        logger.info("Loaded database credentials from Secrets Manager")
    except RuntimeError as exc:
        logger.warning("Could not load DB secret: %s", exc)

    try:
        gemini_secret = _get_aws_secret(gemini_secret_name)
        overrides["gemini_api_key"] = gemini_secret["api_key"]
        logger.info("Loaded Gemini API key from Secrets Manager")
    except RuntimeError as exc:
        logger.warning("Could not load Gemini secret: %s", exc)

    return overrides


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance.

    On AWS (APP_AWS_REGION set), secrets are pulled from Secrets Manager
    and override environment variables. Locally, .env file is used.
    """
    if os.environ.get("APP_AWS_REGION"):
        overrides = _load_aws_secrets()
        os.environ.update(overrides)
        return Settings(**overrides)
    return Settings()
