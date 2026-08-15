"""Cliente delgado sobre la Admin API de Supabase Auth.

Solo se usa para invitar usuarios (`POST /auth/v1/invite`): crea el
`auth.users` y dispara el correo de invitación. Funciona con signups
públicos desactivados porque es una acción admin (service_role), no
self-service.
"""

from uuid import UUID

import httpx

from app.core.errors import AppError
from app.core.settings import get_settings


class AuthAdminError(AppError):
    status_code = 502
    code = "AUTH_ADMIN_ERROR"


async def invite_user(email: str, full_name: str) -> UUID:
    settings = get_settings()
    url = f"{settings.supabase_url}/auth/v1/invite"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    payload = {"email": email, "data": {"full_name": full_name}}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.status_code >= 400:
        raise AuthAdminError(
            "No se pudo invitar al usuario en Supabase Auth.",
            details={"status_code": response.status_code, "body": response.text},
        )

    return UUID(response.json()["id"])
