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
    # Correo saliente (docs/NOTIFICACIONES.md §8). Sin `RESEND_API_KEY` nada
    # sale: el despachador deja cada entrega en `skipped_no_provider` y el job
    # sigue — nunca falla por falta de proveedor. El remitente es SIEMPRE del
    # dominio de la plataforma; el nombre visible lo decide cada correo.
    resend_api_key: str = ""
    notifications_from_address: str = "notificaciones@prendo.com.co"
    # Firma los enlaces de baja de los correos al cliente (NOTIFICACIONES §17).
    # Sin esto no se arma ningún enlace, y un correo al cliente sin salida no
    # sale (queda `dead`); el endpoint público tampoco acepta ningún token —
    # un HMAC con clave vacía lo firma cualquiera. Cambiarlo invalida los
    # enlaces de los correos ya enviados: se rota solo si se filtró.
    notifications_link_secret: str = ""
    # URL pública de ESTE backend (`https://compraventa-backend-dev.fly.dev`).
    # La usa la cabecera `List-Unsubscribe` de los correos al cliente (RFC
    # 8058, NOTIFICACIONES §17-bis): la baja de un clic la dispara el SERVIDOR
    # del proveedor de correo con un POST, y el front (Vercel, estático) no
    # tiene quién lo reciba. Vacía = se deriva de `FLY_APP_NAME`, que Fly pone
    # solo en cada máquina; fuera de Fly y sin esto, los correos salen igual
    # pero sin esas cabeceras (el enlace del cuerpo sigue siendo la salida).
    public_api_url: str = ""

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
