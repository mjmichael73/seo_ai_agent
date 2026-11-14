"""Validated application settings loaded from the environment or a local .env file."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration; secrets are read from environment variables, never committed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="SEO AI Agent", validation_alias="APP_NAME")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    request_timeout: float = Field(default=8.0, gt=0, le=120)
    search_timeout: float = Field(default=8.0, gt=0, le=120)
    max_pages: int = Field(default=20, ge=1, le=20)
    max_response_bytes: int = Field(default=2_000_000, ge=1_024, le=20_000_000)
    max_redirects: int = Field(default=3, ge=0, le=10)

    @property
    def llm_enabled(self) -> bool:
        """Whether a non-empty model API key is configured."""

        return bool(self.openai_api_key and self.openai_api_key.get_secret_value().strip())
