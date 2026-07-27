from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    app_env: str = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "NODE_ENV"),
    )
    core_api_host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("CORE_API_HOST"),
    )
    core_api_port: int = Field(
        default=8080,
        validation_alias=AliasChoices("CORE_API_PORT", "PORT"),
    )
    fe_domain: str = "http://localhost:5173"
    database_url: str
    redis_url: str = "redis://localhost:6379"
    jwt_access_secret: str
    jwt_access_expired: str = "1d"
    jwt_refresh_secret: str
    jwt_refresh_expired: str = "15d"
    internal_secret: str = ""
    ai_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AI_SERVICE_URL", "LEXMIND_AI_SERVICE_URL"),
    )
    # Deprecated fallbacks retained for one compatibility cycle.  The canonical
    # internal service address is AI_SERVICE_URL.
    fastapi_url: str = Field(default="localhost", validation_alias=AliasChoices("FASTAPI_URL"))
    fastapi_port: int = Field(default=8001, validation_alias=AliasChoices("FASTAPI_PORT"))
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    browser_redirect_uri: str = ""
    # Signs the short-lived OAuth state session cookie. Falls back to the
    # refresh-token secret during migration so existing .env files still run.
    session_secret: str | None = None
    email_host: str = ""
    email_user: str = ""
    email_password: str = ""
    mail_from: str = "Support Team <no-reply@domain.com>"

    @property
    def oauth_session_secret(self) -> str:
        return self.session_secret or self.jwt_refresh_secret

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def ai_base_url(self) -> str:
        if self.ai_service_url:
            return self.ai_service_url.rstrip("/")
        host = self.fastjson_host
        return f"http://{host}:{self.fastapi_port}"

    @property
    def fastjson_host(self) -> str:
        return self.fastjson_url_host(self.fastapi_url)

    @staticmethod
    def fastjson_url_host(value: str) -> str:
        return value.removeprefix("http://").removeprefix("https://").rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
