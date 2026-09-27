from typing import Annotated

from fastapi import Header

from app.core.errors import AppError


async def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """CLAUDE.md regla 4: toda operación de dinero exige este header. Quien
    llama es responsable de deduplicar contra él donde el esquema lo soporte
    (ver `contract_payment.idempotency_key`)."""
    if not idempotency_key:
        raise AppError(
            "Falta el header Idempotency-Key, obligatorio en operaciones de dinero.",
            code="IDEMPOTENCY_KEY_REQUIRED",
        )
    return idempotency_key


async def optional_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    """La misma cabecera, pero sin exigirla: la usan los endpoints que hoy
    NO la reciben del front y que no pueden empezar a rechazar peticiones
    sin romper la app ya desplegada (auditoría 27/09/2026: remate F4-04,
    gasto F5-03, egreso de inventario F6-11). Si viene, el servicio la
    persiste con su UNIQUE y deduplica igual que en los obligatorios; si no
    viene, la operación corre como antes. Cuando el front la mande siempre,
    el endpoint pasa a `require_idempotency_key`.
    """
    return idempotency_key or None
