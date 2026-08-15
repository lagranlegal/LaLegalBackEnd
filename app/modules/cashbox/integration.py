"""Funciones de integración mínimas de `cashbox`, adelantadas para que
`contracts` (paso 5) pueda desembolsar/cobrar de verdad. El resto del módulo
(sesiones abrir/cerrar, gastos, cierre con acta, reapertura) es el paso 6 —
ver docs/ARCHITECTURE.md.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def get_open_session(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    """Fase 1: una sola caja por empresa (`platform.service.create_company_defaults`
    ya crea el `cash_register` "Caja principal" al dar de alta la empresa).
    """
    result = await db.execute(
        text(
            """
            select id, register_id
            from public.cash_session
            where company_id = :company_id and status = 'open'
            """
        ),
        {"company_id": str(company_id)},
    )
    return result.first()


async def record_movement(
    db: AsyncSession,
    *,
    session_id: UUID,
    company_id: UUID,
    module: str,
    direction: str,
    concept: str,
    amount: Decimal,
    payment_method: str,
    reference_type: str,
    reference_id: UUID,
    created_by: UUID | None,
    notes: str | None = None,
) -> UUID:
    movement_id = uuid4()
    await db.execute(
        text(
            """
            insert into public.cash_movement
                (id, company_id, session_id, module, direction, concept, reference_type,
                 reference_id, amount, payment_method, notes, created_by)
            values
                (:id, :company_id, :session_id, :module, :direction, :concept, :reference_type,
                 :reference_id, :amount, :payment_method, :notes, :created_by)
            """
        ),
        {
            "id": str(movement_id),
            "company_id": str(company_id),
            "session_id": str(session_id),
            "module": module,
            "direction": direction,
            "concept": concept,
            "reference_type": reference_type,
            "reference_id": str(reference_id),
            "amount": amount,
            "payment_method": payment_method,
            "notes": notes,
            "created_by": str(created_by) if created_by else None,
        },
    )
    return movement_id
