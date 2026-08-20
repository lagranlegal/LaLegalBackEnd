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
    # Orígenes exactos del front (Vercel prod + localhost de desarrollo),
    # coma-separados — se completa por ambiente vía `fly secrets set`, nunca
    # hardcodeado (el dominio de prod cambia por cliente/proyecto).
    cors_allow_origins: str = ""
    # URL base del front de ESTE ambiente. La usa la invitación para armar el
    # `redirect_to` del correo de Supabase.
    #
    # Sin esto, Supabase redirige a su "Site URL" por defecto y el link del
    # correo muere en "This site can't be reached": el usuario queda confirmado
    # en `auth.users` pero nunca llega a `/auth/callback`, así que jamás crea
    # su contraseña ni pasa de `invited` a `active` en `app_user`. Bug real,
    # confirmado en vivo (un invitado con `confirmed_at` y `last_sign_in_at`
    # poblados y `app_user.status` todavía en `invited`).
    frontend_url: str = ""

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
