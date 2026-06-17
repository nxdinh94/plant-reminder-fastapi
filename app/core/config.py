from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Plant Reminder API", alias="APP_NAME")
    environment: Literal["local", "staging", "production"] = Field(
        default="local",
        alias="ENVIRONMENT",
    )
    debug: bool = Field(default=True, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    database_url: str = Field(alias="DATABASE_URL")
    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=30,
        alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    jwt_refresh_token_expire_minutes: int = Field(
        default=60 * 24 * 7,
        alias="JWT_REFRESH_TOKEN_EXPIRE_MINUTES",
    )
    bcrypt_rounds: int = Field(default=12, alias="BCRYPT_ROUNDS")
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="CORS_ORIGINS")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    PROXY_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="PROXY_BASE_URL",
    )
    openrouter_model: str = Field(alias="OPENROUTER_MODEL")
    openrouter_vision_models: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        alias="OPENROUTER_VISION_MODELS",
    )
    openrouter_site_url: str | None = Field(default=None, alias="OPENROUTER_SITE_URL")
    openrouter_site_name: str | None = Field(default=None, alias="OPENROUTER_SITE_NAME")
    upload_dir: str = Field(default="uploads", alias="UPLOAD_DIR")
    media_storage_backend: Literal["local", "r2"] = Field(
        default="local",
        alias="MEDIA_STORAGE_BACKEND",
    )
    r2_worker_upload_url: str | None = Field(default=None, alias="R2_WORKER_UPLOAD_URL")
    r2_worker_shared_secret: str | None = Field(default=None, alias="R2_WORKER_SHARED_SECRET")
    r2_account_id: str | None = Field(default=None, alias="R2_ACCOUNT_ID")
    r2_access_key_id: str | None = Field(default=None, alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: str | None = Field(default=None, alias="R2_SECRET_ACCESS_KEY")
    r2_bucket_name: str | None = Field(default=None, alias="R2_BUCKET_NAME")
    r2_public_base_url: str | None = Field(default=None, alias="R2_PUBLIC_BASE_URL")
    r2_key_prefix: str = Field(default="", alias="R2_KEY_PREFIX")

    # RevenueCat Settings
    REVENUECAT_WEBHOOK_AUTH_HEADER: str = Field(
        default="test-webhook-auth-header-secret",
        alias="REVENUECAT_WEBHOOK_AUTH_HEADER",
    )
    REVENUECAT_REST_API_KEY: str = Field(
        default="test-rest-api-key-secret",
        alias="REVENUECAT_REST_API_KEY",
    )
    REVENUECAT_API_BASE_URL: str = Field(
        default="https://api.revenuecat.com/v1",
        alias="REVENUECAT_API_BASE_URL",
    )
    REVENUECAT_PRO_ENTITLEMENT_ID: str = Field(
        default="PlantReminder Pro",
        alias="REVENUECAT_PRO_ENTITLEMENT_ID",
    )


    @property
    def upload_dir_path(self) -> Path:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent.parent / self.upload_dir
        return path

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        raise ValueError("CORS_ORIGINS must be a comma-separated string or list.")

    @field_validator("openrouter_vision_models", mode="before")
    @classmethod
    def parse_openrouter_vision_models(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        raise ValueError("OPENROUTER_VISION_MODELS must be a comma-separated string or list.")

    @field_validator(
        "openrouter_api_key",
        "openrouter_site_url",
        "openrouter_site_name",
        "r2_worker_upload_url",
        "r2_worker_shared_secret",
        "r2_account_id",
        "r2_access_key_id",
        "r2_secret_access_key",
        "r2_bucket_name",
        "r2_public_base_url",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
