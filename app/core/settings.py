from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    supabase_url: str
    supabase_jwks_url: str
    supabase_service_role_key: str = ""
    jwt_audience: str = "authenticated"
    environment: str = "dev"
    sentry_dsn: str = ""

    @model_validator(mode="after")
    def _resolve_jwks_url(self) -> "Settings":
        # .env usa `${SUPABASE_URL}/...` (así lo documenta CLAUDE.md), pero los
        # archivos .env no interpolan variables solos: lo resolvemos aquí.
        self.supabase_jwks_url = self.supabase_jwks_url.replace(
            "${SUPABASE_URL}", self.supabase_url
        )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
