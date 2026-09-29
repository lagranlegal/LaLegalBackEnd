"""Cabeceras de seguridad de todas las respuestas de la API.

La API solo sirve JSON, así que las cabeceras son las mínimas que aplican a
cualquier respuesta: no adivinar el tipo de contenido, no mandar el referer,
no dejarse enmarcar y, detrás de HTTPS, recordarle al navegador que use HTTPS.
"""

import os

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HSTS_VALUE = "max-age=63072000; includeSubDomains"

BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def hsts_enabled(environment: str, *, fly_app_name: str | None = None) -> bool:
    """HSTS va en todo ambiente desplegado. La única excepción es el
    desarrollo local (`ENVIRONMENT=dev` fuera de Fly), que corre por HTTP.
    El dev remoto también dice `dev`, pero corre en Fly — que pone
    `FLY_APP_NAME` en cada máquina — y siempre detrás de HTTPS."""
    if environment != "dev":
        return True
    app_name = fly_app_name if fly_app_name is not None else os.environ.get("FLY_APP_NAME", "")
    return bool(app_name.strip())


class SecurityHeadersMiddleware:
    """ASGI puro (no `BaseHTTPMiddleware`) para no interferir con respuestas
    en streaming. No pisa una cabecera que el endpoint ya haya fijado."""

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        headers = dict(BASE_HEADERS)
        if hsts:
            headers["Strict-Transport-Security"] = HSTS_VALUE
        self._headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {name.lower() for name, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self._headers if k not in existing]
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)
