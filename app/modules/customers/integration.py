"""Lo que otros módulos pueden pedirle a `customers` (CLAUDE.md regla 2).

Hoy, la base legal del correo del cliente (docs/NOTIFICACIONES.md §9.2):

- `contracts` la escribe cuando nace un contrato vivo (§9.2-a).
- `notifications` registra la baja que el titular pidió por el enlace del
  correo (§9.2-e) y lee lo necesario para mostrarle la página de baja.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers import repository
from app.modules.identity import repository as identity_repo


async def ensure_contract_basis(db: AsyncSession, *, company_id: UUID, customer_id: UUID) -> bool:
    """Base `contract` para un cliente que acaba de quedar con un contrato
    vivo, si tiene correo y todavía no tiene base. Se llama en la MISMA
    transacción que crea el contrato.

    **Se escribe en vez de deducirse en cada envío** (§9.2-a): la base que
    importa es la que había el día que salió el correo, y un `join` al vuelo
    contesta qué pasa hoy, no qué pasaba entonces.

    No se audita aparte: el hecho que la origina (crear, importar o ampliar
    el contrato) ya queda en `audit_log`, y la base es su consecuencia. Lo que
    sí se audita es lo que decide una PERSONA — la casilla del mostrador y la
    baja."""
    return await repository.set_contract_basis_if_missing(
        db, company_id=company_id, customer_id=customer_id
    )


async def get_email_status(
    db: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> dict[str, Any] | None:
    """Correo y baja del cliente, o None si no existe en esa empresa."""
    row = await repository.get_customer(db, company_id=company_id, customer_id=customer_id)
    if row is None:
        return None
    m = row._mapping
    return {"email": m["email"], "email_opt_out_at": m["email_opt_out_at"]}


async def record_opt_out_from_link(
    db: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> datetime | None:
    """La baja pedida por el titular desde el enlace del correo.

    Idempotente: si ya estaba de baja, devuelve la fecha original y no
    audita otra vez — un segundo POST no es un hecho nuevo. `user_id` va
    NULL en `audit_log`: no la hizo un usuario de la empresa, la hizo la
    persona, y confundir las dos cosas sería decir que alguien del mostrador
    la dio de baja."""
    changed, opted_out_at = await repository.mark_opted_out(
        db, company_id=company_id, customer_id=customer_id
    )
    if changed:
        await identity_repo.insert_audit_log(
            db,
            company_id=company_id,
            user_id=None,
            module="customers",
            action="email_opt_out",
            entity_type="customer",
            entity_id=customer_id,
            before={"email_opt_out_at": None},
            after={"email_opt_out_at": str(opted_out_at), "source": "link"},
        )
    return opted_out_at
