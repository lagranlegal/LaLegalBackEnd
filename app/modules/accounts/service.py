from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.modules.accounts import repository
from app.modules.accounts.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountUpdateIn,
    SettlementIn,
    SettlementOut,
)
from app.modules.cashbox import integration as cashbox_integration
from app.modules.identity import repository as identity_repo


def _row_to_account(row: Row[Any], balance: Decimal | None = None) -> AccountOut:
    m = row._mapping
    return AccountOut(
        id=m["id"],
        name=m["name"],
        type=m["type"],
        reference=m["reference"],
        is_default=m["is_default"],
        active=m["active"],
        balance=balance if balance is not None else m["balance"],
        created_at=m["created_at"],
    )


async def list_accounts(
    db: AsyncSession, *, company_id: UUID, include_inactive: bool = False
) -> list[AccountOut]:
    rows = await repository.list_accounts(
        db, company_id=company_id, include_inactive=include_inactive
    )
    return [_row_to_account(r) for r in rows]


async def create_account(
    db: AsyncSession, *, company_id: UUID, body: AccountCreateIn
) -> AccountOut:
    if body.is_default:
        await repository.clear_default(db, company_id=company_id, account_type=body.type)

    account_id = uuid4()
    await repository.insert_account(
        db,
        account_id=account_id,
        company_id=company_id,
        name=body.name,
        account_type=body.type,
        reference=body.reference,
        is_default=body.is_default,
    )
    return await get_account(db, company_id=company_id, account_id=account_id)


async def get_account(db: AsyncSession, *, company_id: UUID, account_id: UUID) -> AccountOut:
    row = await repository.get_account(db, company_id=company_id, account_id=account_id)
    if row is None:
        raise NotFoundError("La cuenta no existe en esta empresa.")
    balance = await repository.account_balance(db, company_id=company_id, account_id=account_id)
    return _row_to_account(row, balance)


async def update_account(
    db: AsyncSession, *, company_id: UUID, account_id: UUID, body: AccountUpdateIn
) -> AccountOut:
    row = await repository.get_account(db, company_id=company_id, account_id=account_id)
    if row is None:
        raise NotFoundError("La cuenta no existe en esta empresa.")

    fields = body.model_dump(exclude_unset=True)
    if fields.get("is_default"):
        await repository.clear_default(db, company_id=company_id, account_type=row._mapping["type"])
    if fields.get("active") is False and row._mapping["is_default"]:
        # Desactivar la cuenta por defecto dejaría los cobros sin dónde caer.
        raise ConflictError(
            "No se puede desactivar la cuenta predeterminada. "
            "Marca otra como predeterminada primero."
        )

    await repository.update_account_fields(
        db, company_id=company_id, account_id=account_id, fields=fields
    )
    return await get_account(db, company_id=company_id, account_id=account_id)


async def settle_account(
    db: AsyncSession,
    *,
    company_id: UUID,
    account_id: UUID,
    body: SettlementIn,
    actor_id: UUID,
) -> SettlementOut:
    """Liquida una cuenta por cobrar: Sistecrédito consigna lo que debía.

    Genera DOS movimientos en la misma transacción:
      · salida de la cuenta por cobrar por lo liquidado
      · entrada a la cuenta destino por lo efectivamente recibido

    La diferencia es la comisión, y NO se digita ni se configura: se deriva.
    Así el sistema no puede quedar desactualizado respecto al contrato con el
    convenio, y de paso queda medible cuánto cuesta el convenio al mes — que
    es información de negociación, no solo contable.

    La comisión no genera su propio movimiento: no es plata que salió de
    ningún lado, es plata que nunca llegó. Registrarla como egreso la contaría
    dos veces (ya está implícita en que entró menos de lo que se liquidó).
    """
    origen = await repository.get_account(db, company_id=company_id, account_id=account_id)
    if origen is None:
        raise NotFoundError("La cuenta a liquidar no existe en esta empresa.")
    if origen._mapping["type"] != "settlement":
        raise AppError(
            "Solo se liquidan cuentas por cobrar. Una cuenta de efectivo o banco "
            "no tiene nada pendiente de liquidar.",
            details={"type": origen._mapping["type"]},
        )

    destino = await repository.get_account(db, company_id=company_id, account_id=body.to_account_id)
    if destino is None:
        raise NotFoundError("La cuenta destino no existe en esta empresa.")
    if destino._mapping["type"] == "settlement":
        raise AppError("La cuenta destino no puede ser otra cuenta por cobrar.")

    if body.amount_received > body.amount_settled:
        raise AppError(
            "Lo recibido no puede superar lo liquidado: la diferencia es la comisión "
            "del convenio, nunca puede ser negativa.",
            details={
                "amount_settled": str(body.amount_settled),
                "amount_received": str(body.amount_received),
            },
        )

    pendiente = await repository.account_balance(db, company_id=company_id, account_id=account_id)
    if body.amount_settled > pendiente:
        raise AppError(
            "No se puede liquidar más de lo que está pendiente de cobro.",
            details={"pendiente": str(pendiente), "amount_settled": str(body.amount_settled)},
        )

    # El destino puede ser efectivo (raro pero válido: alguien cobra en
    # ventanilla). Si lo es, exige caja abierta, igual que cualquier ingreso
    # de efectivo — el resto de cuentas no la necesita.
    session = await cashbox_integration.get_open_session(db, company_id=company_id)
    if destino._mapping["type"] == "cash" and session is None:
        raise AppError("No hay una sesión de caja abierta para recibir efectivo.")

    session_id = session._mapping["id"] if session is not None else None
    if session_id is not None:
        await cashbox_integration.record_movement(
            db,
            session_id=session_id,
            company_id=company_id,
            module="store",
            direction="out",
            concept="adjustment",
            amount=body.amount_settled,
            payment_method="other",
            reference_type="settlement",
            reference_id=account_id,
            created_by=actor_id,
            notes=f"Liquidación de {origen._mapping['name']}",
            account_id=account_id,
        )
        await cashbox_integration.record_movement(
            db,
            session_id=session_id,
            company_id=company_id,
            module="store",
            direction="in",
            concept="adjustment",
            amount=body.amount_received,
            payment_method="cash" if destino._mapping["type"] == "cash" else "transfer",
            reference_type="settlement",
            reference_id=account_id,
            created_by=actor_id,
            notes=body.notes or f"Recibido de {origen._mapping['name']}",
            account_id=body.to_account_id,
        )

    comision = body.amount_settled - body.amount_received
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="cashbox",
        action="settle_account",
        entity_type="account",
        entity_id=account_id,
        after={
            "settled": str(body.amount_settled),
            "received": str(body.amount_received),
            "commission": str(comision),
        },
    )

    return SettlementOut(
        settled=body.amount_settled,
        received=body.amount_received,
        commission=comision,
        commission_pct=(
            (comision / body.amount_settled * 100).quantize(Decimal("0.01"))
            if body.amount_settled > 0
            else None
        ),
        new_pending_balance=pendiente - body.amount_settled,
    )
