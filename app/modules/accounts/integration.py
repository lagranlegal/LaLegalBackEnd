"""Funciones de integración mínimas de `accounts` para otros módulos
(CLAUDE.md regla 2 — un módulo nunca importa el `service.py` de otro).

`sales` las necesita para decidir si una devolución en efectivo es segura:
si la venta original se cobró por una cuenta `settlement` (Sistecrédito) que
todavía no se liquidó, no hay plata real que devolver — devolverla en
efectivo sacaría dinero que el negocio nunca recibió.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts import repository


async def get_account_type(db: AsyncSession, *, company_id: UUID, account_id: UUID) -> str | None:
    row = await repository.get_account(db, company_id=company_id, account_id=account_id)
    return str(row._mapping["type"]) if row is not None else None


async def get_account_balance(db: AsyncSession, *, company_id: UUID, account_id: UUID) -> Decimal:
    return await repository.account_balance(db, company_id=company_id, account_id=account_id)


async def get_cash_on_hand(db: AsyncSession, *, company_id: UUID) -> Decimal:
    """Todo el efectivo que el sistema cree que hay en cajones, ahora mismo.

    Es contra este número que se arquea al abrir y al cerrar el turno, y por
    eso suma TODAS las cuentas `cash` y no solo la predeterminada: es el
    mismo criterio con el que `cashbox._expected_cash` decide qué entra al
    arqueo (el tipo de cuenta, no el medio de pago). Si los dos no sumaran lo
    mismo, un descuadre podría aparecer y desaparecer según por dónde se
    mirara.

    Desde 00048 esto es una suma de movimientos y ya no depende de que haya
    una sesión abierta: el efectivo del cajón sigue existiendo a las 11 de la
    noche.
    """
    rows = await repository.list_accounts(db, company_id=company_id, include_inactive=True)
    return sum(
        (Decimal(str(r._mapping["balance"])) for r in rows if r._mapping["type"] == "cash"),
        Decimal("0.00"),
    )
