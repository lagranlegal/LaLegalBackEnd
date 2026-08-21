"""Funciones de integración mínimas de `cashbox`, adelantadas para que
`contracts` (paso 5) pueda desembolsar/cobrar de verdad. El resto del módulo
(sesiones abrir/cerrar, gastos, cierre con acta, reapertura) es el paso 6 —
ver docs/ARCHITECTURE.md.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import CashSessionNotOpenError, NotFoundError


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
    session_id: UUID | None,
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
    account_id: UUID | None = None,
) -> UUID:
    """`account_id` es opcional durante la fase 2 del catálogo de cuentas: si
    no viene, se resuelve la cuenta por defecto del tipo que corresponde al
    `payment_method`. Así las operaciones que todavía no eligen cuenta siguen
    quedando bien clasificadas en vez de sin cuenta, y el saldo por cuenta no
    nace incompleto. La fase 3 lo vuelve obligatorio.
    """
    if account_id is None:
        account_id = await _default_account_for(
            db, company_id=company_id, payment_method=payment_method
        )
    movement_id = uuid4()
    await db.execute(
        text(
            """
            insert into public.cash_movement
                (id, company_id, session_id, module, direction, concept, reference_type,
                 reference_id, amount, payment_method, notes, created_by, account_id)
            values
                (:id, :company_id, :session_id, :module, :direction, :concept, :reference_type,
                 :reference_id, :amount, :payment_method, :notes, :created_by, :account_id)
            """
        ),
        {
            "id": str(movement_id),
            "company_id": str(company_id),
            "session_id": str(session_id) if session_id else None,
            "module": module,
            "direction": direction,
            "concept": concept,
            "reference_type": reference_type,
            "reference_id": str(reference_id),
            "amount": amount,
            "payment_method": payment_method,
            "notes": notes,
            "created_by": str(created_by) if created_by else None,
            "account_id": str(account_id) if account_id else None,
        },
    )
    return movement_id


async def _default_account_for(
    db: AsyncSession, *, company_id: UUID, payment_method: str
) -> UUID | None:
    """Cuenta por defecto del tipo que corresponde a un medio de pago.

    `cash` -> la cuenta de efectivo; cualquier otro medio -> la bancaria por
    defecto. Es el mismo mapeo del backfill de 00024, para que un movimiento
    creado por código que aún no elige cuenta caiga donde caerían sus
    hermanos históricos.
    """
    tipo = "cash" if payment_method == "cash" else "bank"
    result = await db.execute(
        text(
            "select id from public.account "
            "where company_id = :cid and type = :type and is_default and active"
        ),
        {"cid": str(company_id), "type": tipo},
    )
    row = result.first()
    if row is not None:
        return UUID(str(row[0]))

    # Red de seguridad: una empresa sin la cuenta predeterminada de ese tipo
    # es un hueco del alta (`platform.create_company_defaults` las crea), pero
    # fallar acá dejaría caer una operación de dinero por un problema de
    # configuración. Se crea al vuelo y la operación sigue: perder el registro
    # del movimiento sería peor que crear una cuenta implícita.
    nombre = "Caja principal" if tipo == "cash" else "Transferencias"
    result = await db.execute(
        text(
            """
            insert into public.account (company_id, name, type, is_default)
            values (:cid, :name, :type, true)
            on conflict (company_id, name) do update set name = excluded.name
            returning id
            """
        ),
        {"cid": str(company_id), "name": nombre, "type": tipo},
    )
    creada = result.first()
    return UUID(str(creada[0])) if creada else None


@dataclass(frozen=True)
class ResolvedAccount:
    """Cuenta resuelta para un movimiento, con la sesión que le corresponde."""

    account_id: UUID | None
    account_type: str | None
    #: `None` cuando la cuenta no es de efectivo y no hay sesión abierta. El
    #: movimiento se registra igual: no pertenece a ningún turno de caja.
    session_id: UUID | None


async def resolve_account_for_movement(
    db: AsyncSession,
    *,
    company_id: UUID,
    payment_method: str,
    account_id: UUID | None = None,
) -> ResolvedAccount:
    """Resuelve la cuenta de un movimiento y decide si exige sesión de caja.

    ES EL ÚNICO LUGAR donde vive esta regla, a propósito: antes cada servicio
    repetía "si no hay sesión abierta, rechaza", lo que hacía que una
    transferencia a las 11 de la noche quedara bloqueada por una regla
    pensada para el cajón físico.

    La sesión la exige el TIPO DE CUENTA, no la operación:

      cash               exige sesión abierta. No se pueden meter billetes a
                         un cajón cerrado, y sin sesión el arqueo no podría
                         cuadrar nunca.
      bank / settlement  no la exige. Una transferencia o una venta por
                         Sistecrédito no pasan por el cajón. Si hay una
                         sesión abierta el movimiento se asocia igual, para
                         que el acta del turno siga mostrando todo lo que
                         ocurrió durante él.
    """
    if account_id is None:
        account_id = await _default_account_for(
            db, company_id=company_id, payment_method=payment_method
        )

    account_type: str | None = None
    if account_id is not None:
        result = await db.execute(
            text("select type from public.account where company_id = :cid and id = :id"),
            {"cid": str(company_id), "id": str(account_id)},
        )
        row = result.first()
        if row is None:
            raise NotFoundError("La cuenta indicada no existe en esta empresa.")
        account_type = str(row[0])

    session = await get_open_session(db, company_id=company_id)

    # Sin cuenta resuelta se mantiene el comportamiento anterior (exigir
    # sesión): es lo conservador mientras queden caminos que aún no eligen
    # cuenta, y evita que un movimiento se escape del arqueo por accidente.
    if account_type in (None, "cash") and session is None:
        raise CashSessionNotOpenError(
            "No hay una sesión de caja abierta para registrar un movimiento en efectivo."
        )

    return ResolvedAccount(
        account_id=account_id,
        account_type=account_type,
        session_id=session._mapping["id"] if session is not None else None,
    )
