from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import AppError, CashSessionNotOpenError, ConflictError, NotFoundError
from app.modules.accounts import repository
from app.modules.accounts.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountStatementOut,
    AccountUpdateIn,
    SettlementIn,
    SettlementOut,
    StatementLineOut,
    TransferIn,
    TransferOut,
)
from app.modules.cashbox import integration as cashbox_integration
from app.modules.identity import repository as identity_repo
from app.modules.platform import integration as platform_integration


def _row_to_account(row: Row[Any], balance: Decimal | None = None) -> AccountOut:
    m = row._mapping
    return AccountOut(
        id=m["id"],
        name=m["name"],
        type=m["type"],
        reference=m["reference"],
        is_default=m["is_default"],
        active=m["active"],
        opening_balance=m["opening_balance"],
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
        opening_balance=body.opening_balance,
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
            # Conceptos propios desde 00038: un "ajuste" significa que el
            # sistema no cuadra con la realidad. Una liquidación sí cuadra —
            # es la operación normal que cierra toda venta con Sistecrédito.
            concept="settlement_out",
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
            concept="settlement_in",
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


def _row_to_transfer(row: Row[Any], *, from_balance: Decimal, to_balance: Decimal) -> TransferOut:
    m = row._mapping
    return TransferOut(
        id=m["id"],
        number=m["number"],
        from_account_id=m["from_account_id"],
        from_account_name=m["from_account_name"],
        to_account_id=m["to_account_id"],
        to_account_name=m["to_account_name"],
        amount=m["amount"],
        transfer_date=m["transfer_date"],
        notes=m["notes"],
        created_at=m["created_at"],
        from_balance=from_balance,
        to_balance=to_balance,
    )


async def create_transfer(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: TransferIn,
    actor_id: UUID,
    idempotency_key: str,
) -> TransferOut:
    """Mueve plata entre dos cuentas propias. El caso típico: consignar en el
    banco el efectivo del día.

    NO ES INGRESO NI EGRESO. Es la misma plata en otro bolsillo: no toca el
    estado de resultados, solo mueve saldos. Es el mismo principio que este
    proyecto ya pagó caro en los contratos — "el interés es ingreso; el
    capital recuperado no" — aplicado al efectivo. Registrar una consignación
    como gasto falsearía la utilidad del período por el monto consignado, que
    en una compraventa es prácticamente toda la caja del día.

    Genera DOS movimientos con conceptos propios (`transfer_out` /
    `transfer_in`) y no con `adjustment`: un ajuste significa "el sistema no
    cuadra con la realidad"; un traslado sí cuadra. Además los conceptos
    propios permiten EXCLUIRLOS del cálculo de ingresos y gastos sin
    ambigüedad — contarlos inventaría movimiento de negocio donde solo hubo
    un cambio de bolsillo.
    """
    existing = await repository.find_transfer_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return await get_transfer(db, company_id=company_id, transfer_id=existing._mapping["id"])

    if body.from_account_id == body.to_account_id:
        raise AppError(
            "El origen y el destino no pueden ser la misma cuenta: eso no mueve "
            "nada y dejaría dos movimientos que se anulan entre sí."
        )

    origen = await repository.get_account(
        db, company_id=company_id, account_id=body.from_account_id
    )
    if origen is None:
        raise NotFoundError("La cuenta de origen no existe en esta empresa.")
    destino = await repository.get_account(db, company_id=company_id, account_id=body.to_account_id)
    if destino is None:
        raise NotFoundError("La cuenta destino no existe en esta empresa.")

    # Una cuenta por cobrar no puede ser origen: es plata que todavía te
    # deben, no un saldo disponible. Sacarla de ahí sería inventar que ya
    # llegó. Su única salida legítima es la LIQUIDACIÓN, que además registra
    # cuánto llegó de menos (la comisión) — información que un traslado no
    # tiene dónde poner, porque en un traslado llega exactamente lo que salió.
    if origen._mapping["type"] == "settlement":
        raise AppError(
            "Una cuenta por cobrar no puede ser el origen de un traslado. Para "
            "registrar lo que el convenio consignó usa la liquidación, que "
            "además calcula la comisión.",
            details={"from_account_id": str(body.from_account_id)},
            code="ACCOUNT_CANNOT_FUND_PAYMENT",
        )
    if destino._mapping["type"] == "settlement":
        raise AppError(
            "No se puede trasladar plata HACIA una cuenta por cobrar: esa cuenta "
            "refleja lo que un convenio te debe, y eso lo genera vender, no "
            "consignar.",
            details={"to_account_id": str(body.to_account_id)},
        )

    today = await platform_integration.get_company_today(db, company_id=company_id)
    transfer_date = body.transfer_date or today
    if transfer_date > today:
        raise AppError(
            "`transfer_date` no puede ser una fecha futura.",
            details={"transfer_date": str(transfer_date), "today": str(today)},
        )

    saldo_origen = await repository.account_balance(
        db, company_id=company_id, account_id=body.from_account_id
    )
    if body.amount > saldo_origen:
        raise AppError(
            "No se puede trasladar más de lo que hay en la cuenta de origen.",
            details={"disponible": str(saldo_origen), "amount": str(body.amount)},
        )

    # Sacar efectivo del cajón exige el cajón abierto, igual que cualquier
    # otro movimiento de efectivo: sin sesión el arqueo no podría cuadrar. Y
    # es deliberado que el traslado vaya ANTES del cierre — una sesión cerrada
    # es inmutable, así que meterle el movimiento después invalidaría un acta
    # ya cuadrada e impresa.
    session = await cashbox_integration.get_open_session(db, company_id=company_id)
    toca_efectivo = "cash" in (origen._mapping["type"], destino._mapping["type"])
    if toca_efectivo and session is None:
        raise CashSessionNotOpenError(
            "No hay una sesión de caja abierta. Consigna el efectivo antes de "
            "cerrar la caja: un cierre ya firmado no se puede modificar."
        )
    session_id = session._mapping["id"] if session is not None else None

    transfer_id = uuid4()
    number = await repository.next_transfer_number(db, company_id=company_id)
    await repository.insert_transfer(
        db,
        transfer_id=transfer_id,
        company_id=company_id,
        number=number,
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount=body.amount,
        transfer_date=transfer_date,
        notes=body.notes,
        created_by=actor_id,
        idempotency_key=idempotency_key,
    )

    nota = body.notes or f"Traslado a {destino._mapping['name']}"
    await cashbox_integration.record_movement(
        db,
        session_id=session_id,
        company_id=company_id,
        module="general",
        direction="out",
        concept="transfer_out",
        amount=body.amount,
        payment_method="cash" if origen._mapping["type"] == "cash" else "transfer",
        reference_type="account_transfer",
        reference_id=transfer_id,
        created_by=actor_id,
        notes=nota,
        account_id=body.from_account_id,
    )
    await cashbox_integration.record_movement(
        db,
        session_id=session_id,
        company_id=company_id,
        module="general",
        direction="in",
        concept="transfer_in",
        amount=body.amount,
        payment_method="cash" if destino._mapping["type"] == "cash" else "transfer",
        reference_type="account_transfer",
        reference_id=transfer_id,
        created_by=actor_id,
        notes=f"Traslado desde {origen._mapping['name']}",
        account_id=body.to_account_id,
    )

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="cashbox",
        action="account_transfer",
        entity_type="account_transfer",
        entity_id=transfer_id,
        after={
            "from": origen._mapping["name"],
            "to": destino._mapping["name"],
            "amount": str(body.amount),
            "transfer_date": str(transfer_date),
        },
    )

    return await get_transfer(db, company_id=company_id, transfer_id=transfer_id)


async def get_transfer(db: AsyncSession, *, company_id: UUID, transfer_id: UUID) -> TransferOut:
    row = await repository.get_transfer(db, company_id=company_id, transfer_id=transfer_id)
    if row is None:
        raise NotFoundError("El traslado no existe en esta empresa.")
    m = row._mapping
    return _row_to_transfer(
        row,
        from_balance=await repository.account_balance(
            db, company_id=company_id, account_id=m["from_account_id"]
        ),
        to_balance=await repository.account_balance(
            db, company_id=company_id, account_id=m["to_account_id"]
        ),
    )


async def list_transfers(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[TransferOut]:
    rows = await repository.list_transfers(db, company_id=company_id, cursor=cursor, limit=limit)
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    out = []
    for row in page.items:
        m = row._mapping
        out.append(
            _row_to_transfer(
                row,
                from_balance=await repository.account_balance(
                    db, company_id=company_id, account_id=m["from_account_id"]
                ),
                to_balance=await repository.account_balance(
                    db, company_id=company_id, account_id=m["to_account_id"]
                ),
            )
        )
    return CursorPage(items=out, next_cursor=page.next_cursor)


async def get_statement(
    db: AsyncSession,
    *,
    company_id: UUID,
    account_id: UUID,
    from_date: date,
    to_date: date,
) -> AccountStatementOut:
    """Extracto de una cuenta, para conciliar contra el del banco.

    Completa la idea que 00024 dejó escrita y a medias: *"solo las cuentas
    `cash` entran al arqueo — el resto lleva saldo corriente y se concilia
    aparte"*. El saldo existía; el "aparte" nunca se construyó, así que la
    pantalla de Cuentas decía cuánto hay en el banco pero no cómo se llegó
    ahí — y sin eso no se puede cuadrar.

    EN EFECTIVO NO HAY SALDO CORRIENTE, y no es una carencia: la base del
    cajón se vuelve a declarar en cada apertura y no es un movimiento, así que
    acumular el histórico daría un número sin significado. El efectivo se
    verifica CONTANDO. Se devuelven igual sus movimientos —sirven para ver qué
    pasó por el cajón— pero sin saldo y diciéndolo.
    """
    row = await repository.get_account(db, company_id=company_id, account_id=account_id)
    if row is None:
        raise NotFoundError("La cuenta no existe en esta empresa.")
    if from_date > to_date:
        raise AppError("`from_date` no puede ser posterior a `to_date`.")

    tipo = str(row._mapping["type"])
    tz_name = await platform_integration.get_company_timezone(db, company_id=company_id)
    acumula = tipo != "cash"

    saldo_inicial = (
        await repository.balance_before(
            db,
            company_id=company_id,
            account_id=account_id,
            from_date=from_date,
            tz_name=tz_name,
        )
        if acumula
        else None
    )

    movimientos = await repository.account_movements(
        db,
        company_id=company_id,
        account_id=account_id,
        from_date=from_date,
        to_date=to_date,
        tz_name=tz_name,
    )

    corriente = saldo_inicial if saldo_inicial is not None else Decimal("0")
    total_in = Decimal("0")
    total_out = Decimal("0")
    lineas: list[StatementLineOut] = []
    for m in movimientos:
        d = m._mapping
        monto = Decimal(str(d["amount"]))
        if d["direction"] == "in":
            total_in += monto
            corriente += monto
        else:
            total_out += monto
            corriente -= monto
        lineas.append(
            StatementLineOut(
                movement_id=d["id"],
                created_at=d["created_at"],
                module=d["module"],
                concept=d["concept"],
                direction=d["direction"],
                amount=monto,
                payment_method=d["payment_method"],
                notes=d["notes"],
                reference_type=d["reference_type"],
                reference_id=d["reference_id"],
                running_balance=corriente if acumula else None,
            )
        )

    return AccountStatementOut(
        account_id=account_id,
        name=row._mapping["name"],
        type=tipo,
        from_date=from_date,
        to_date=to_date,
        opening_balance=saldo_inicial,
        total_in=total_in,
        total_out=total_out,
        closing_balance=corriente if acumula else None,
        has_running_balance=acumula,
        lines=lineas,
    )
