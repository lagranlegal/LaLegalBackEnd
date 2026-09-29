"""Reporte de errores a Sentry, opcional.

Solo se activa si `SENTRY_DSN` está configurado; sin él no se importa ni se
inicializa nada. No se envía información personal: sin PII por defecto, y
`before_send` quita del evento las cabeceras de autenticación, las cookies y
el cuerpo del request (que puede traer datos de clientes).
"""

from typing import Any

from app.core.settings import Settings

_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "proxy-authorization"}


def scrub_event(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_HEADERS
            }
        request.pop("data", None)
        request.pop("cookies", None)
    return event


def init_sentry(settings: Settings) -> bool:
    """Inicializa Sentry si hay DSN. Devuelve si quedó inicializado."""
    dsn = settings.sentry_dsn.strip()
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        integrations=[FastApiIntegration()],
        send_default_pii=False,
        max_request_body_size="never",
        before_send=scrub_event,  # type: ignore[arg-type]
        traces_sample_rate=0.0,
    )
    return True
