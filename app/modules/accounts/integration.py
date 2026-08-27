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
