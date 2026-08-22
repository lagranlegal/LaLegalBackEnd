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
    base_url = (
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

    # `redirect_to` VA EN EL QUERY STRING, no en el body.
    #
    # BUG REAL, encontrado porque la invitación funcionaba al invitar a un
    # usuario y NO al crear una empresa. Los dos caminos llaman a esta misma
    # función; lo único que cambia es `send_email`, y ahí estaba la trampa:
    #
    #   · `/admin/generate_link` SÍ lee `redirect_to` del body — por eso el
    #     botón "Generar enlace" siempre funcionó.
    #   · `/invite` solo lo lee del QUERY STRING. En el body lo ignora, en
    #     silencio, y manda al invitado al "Site URL" del proyecto — que es
    #     la raíz de la app. O sea: el invitado entra directo, con sesión
    #     activa y sin que nadie le pida contraseña. Y como quedó sin
    #     contraseña, tampoco puede volver a entrar después.
    #
    # Crear una empresa siempre manda correo, así que ese camino estaba roto
    # al 100% mientras el otro se veía perfecto.
    #
    # Se confirma contra el cliente oficial (`@supabase/auth-js`,
    # `lib/fetch.js`): pone `redirect_to` en el query para AMBOS endpoints.
    # Acá se manda en los dos lugares a propósito — el query es el que
    # funciona en ambos, y el body es lo que `generate_link` ya venía
    # aceptando; un campo de más que el servidor ignora no cuesta nada, y
    # quitarlo arriesgaría el único camino que hoy sí sirve.
    #
    # OJO: la URL debe estar además en la lista de "Redirect URLs" permitidas
    # del proyecto Supabase (Authentication → URL Configuration). Si no está,
    # Supabase la IGNORA —también en silencio— y vuelve a caer en la Site
    # URL, con el mismo síntoma. Ver `frontend-starter/docs/DEPLOY.md`.
    params: dict[str, str] = {}
    if settings.frontend_url:
        callback = f"{settings.frontend_url.rstrip('/')}/auth/callback"
        params["redirect_to"] = callback
        payload["redirect_to"] = callback

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(base_url, headers=headers, json=payload, params=params)

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


async def generate_recovery_link(email: str) -> str:
    """Enlace para que alguien vuelva a poner su contraseña, SIN mandar correo.

    Es el equivalente del "Generar enlace" de la invitación, para el otro caso:
    a un empleado se le olvidó la contraseña. Hasta ahora eso solo se resolvía
    por correo (`resetPasswordForEmail` en el front), y el servicio incluido de
    Supabase limita los envíos a unos pocos por hora — así que si el correo no
    llegaba, esa persona quedaba afuera y NADIE podía rescatarla. Era el único
    hueco funcional que dejaba no tener correo propio.

    Con el enlace, el admin lo pasa por WhatsApp y listo, sin consumir cuota —
    el mismo camino que las compraventas ya usan para invitar, y que para
    ellas suele ser mejor que el correo porque la persona está ahí mismo.

    Es una CREDENCIAL de un solo uso: quien lo tenga puede cambiarle la
    contraseña a ese usuario y entrar como él. Por eso solo lo obtiene quien ya
    tiene `identity.manage_users`, se audita, y no se escribe en ningún log.
    """
    settings = get_settings()
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    payload: dict[str, object] = {"type": "recovery", "email": email}

    # Query Y body, por lo mismo que en `invite_user`: el query es el que
    # funciona en los dos endpoints de GoTrue y el body es lo que
    # `generate_link` ya venía aceptando.
    params: dict[str, str] = {}
    if settings.frontend_url:
        callback = f"{settings.frontend_url.rstrip('/')}/auth/callback"
        params["redirect_to"] = callback
        payload["redirect_to"] = callback

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{settings.supabase_url}/auth/v1/admin/generate_link",
            headers=headers,
            json=payload,
            params=params,
        )

    if response.status_code >= 400:
        raise AuthAdminError(
            "No se pudo generar el enlace de recuperación en Supabase Auth.",
            details={"status_code": response.status_code, "body": response.text},
        )

    link = response.json().get("action_link")
    if not link:
        raise AuthAdminError("Supabase no devolvió el enlace de recuperación.")
    return str(link)
