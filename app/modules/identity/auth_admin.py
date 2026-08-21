"""Cliente delgado sobre la Admin API de Supabase Auth.

Solo se usa para invitar usuarios (`POST /auth/v1/invite`): crea el
`auth.users` y dispara el correo de invitación. Funciona con signups
públicos desactivados porque es una acción admin (service_role), no
self-service.
"""

from dataclasses import dataclass
from uuid import UUID

import httpx

from app.core.errors import AppError
from app.core.settings import get_settings


class AuthAdminError(AppError):
    status_code = 502
    code = "AUTH_ADMIN_ERROR"


class InviteRateLimitedError(AppError):
    """Supabase limitó el envío de correos (429).

    Es un caso aparte y no un `AuthAdminError` porque no hay nada roto: hay
    que esperar. Mezclarlo con el error genérico le decía al admin "no se
    pudo invitar" con un 502 —que se lee como una falla del sistema— cuando
    la acción correcta es simplemente reintentar más tarde.

    El servicio de correo incluido de Supabase tiene un límite bajo a
    propósito: está pensado para pruebas, no para producción. La solución de
    fondo es configurar un SMTP propio (ver docs/DEPLOY.md).
    """

    status_code = 429
    code = "INVITE_RATE_LIMITED"


@dataclass(frozen=True)
class Invitation:
    """Resultado de dar de alta a alguien en Supabase Auth.

    `link` solo viene cuando se pidió SIN correo: es el enlace que el admin
    le pasa a la persona por otro medio.
    """

    user_id: UUID
    link: str | None


async def invite_user(email: str, full_name: str, *, send_email: bool = True) -> Invitation:
    """Crea el usuario en Supabase Auth.

    Dos modos, y la diferencia es solo quién entrega el enlace:

    · `send_email=True` → `POST /auth/v1/invite`. Supabase manda el correo.
    · `send_email=False` → `POST /auth/v1/admin/generate_link`. Devuelve el
      MISMO enlace sin enviar nada, así que **no consume la cuota de correos**
      y sirve cuando el correo no llega, cae en spam, o la persona está
      parada al lado del admin — que en una compraventa es lo normal.

    El enlace es una credencial de un solo uso: quien lo tenga se convierte en
    ese usuario. Por eso solo se devuelve a quien ya tiene
    `identity.manage_users`, y no se escribe en ningún log.
    """
    settings = get_settings()
    url = (
        f"{settings.supabase_url}/auth/v1/invite"
        if send_email
        else f"{settings.supabase_url}/auth/v1/admin/generate_link"
    )
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    payload: dict[str, object] = {"email": email, "data": {"full_name": full_name}}
    if not send_email:
        # `generate_link` necesita saber QUÉ tipo de enlace emitir; `invite`
        # lo da por hecho porque el endpoint ya lo dice.
        payload["type"] = "invite"

    # Sin `redirect_to`, Supabase manda al usuario a su "Site URL" por defecto
    # y el link del correo muere. El destino es la pantalla donde el invitado
    # crea su contraseña; `detectSessionInUrl` del cliente de Supabase procesa
    # ahí el token que viene en el fragmento de la URL.
    #
    # OJO: la URL debe estar además en la lista de "Redirect URLs" permitidas
    # del proyecto Supabase (Authentication → URL Configuration). Si no está,
    # Supabase la IGNORA en silencio y vuelve a caer en la Site URL — o sea,
    # el mismo síntoma. Configurado en dev el 21/08/2026 (junto con el Site
    # URL, que estaba en localhost:3000 y era la otra mitad del problema);
    # el procedimiento y por qué NO se usa `supabase config push` están en
    # `frontend-starter/docs/DEPLOY.md`.
    if settings.frontend_url:
        payload["redirect_to"] = f"{settings.frontend_url.rstrip('/')}/auth/callback"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.status_code == 429:
        raise InviteRateLimitedError(
            "Supabase limitó el envío de correos. Espera unos minutos e invita de nuevo.",
            details={"body": response.text},
        )
    if response.status_code >= 400:
        raise AuthAdminError(
            "No se pudo invitar al usuario en Supabase Auth.",
            details={"status_code": response.status_code, "body": response.text},
        )

    body = response.json()
    return Invitation(user_id=UUID(body["id"]), link=body.get("action_link"))
