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
