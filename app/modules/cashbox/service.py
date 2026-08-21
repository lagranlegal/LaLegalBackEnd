from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core import security
from app.core.errors import (
    AppError,
    CashSessionNotOpenError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.cashbox import integration, repository
from app.modules.cashbox.schemas import (
    BreakdownLineOut,
    ExpenseCategoryCreateIn,
    ExpenseCategoryOut,
    ExpenseCreateIn,
    ExpenseOut,
    SessionCloseIn,
    SessionOut,
    SessionReportOut,
)
from app.modules.identity import repository as identity_repo
from app.modules.platform import integration as platform_integration


def _row_to_session(row: Row[Any]) -> SessionOut:
    m = row._mapping
    return SessionOut(
        id=m["id"],
        register_id=m["register_id"],
        session_date=m["session_date"],
        opened_by=m["opened_by"],
        opened_at=m["opened_at"],
        opening_balance=m["opening_balance"],
        expected_cash=m["expected_cash"],
        counted_cash=m["counted_cash"],
        difference=m["difference"],
        difference_reason=m["difference_reason"],
        closed_by=m["closed_by"],
        closed_at=m["closed_at"],
        status=m["status"],
    )


def _row_to_expense(row: Row[Any]) -> ExpenseOut:
    m = row._mapping
    return ExpenseOut(
        id=m["id"],
        session_id=m["session_id"],
        module=m["module"],
        category_id=m["category_id"],
        description=m["description"],
        amount=m["amount"],
        payment_method=m["payment_method"],
        receipt_url=m["receipt_url"],
        created_at=m["created_at"],
    )


async def open_session(
    db: AsyncSession, *, company_id: UUID, opened_by: UUID, opening_balance: Decimal
) -> SessionOut:
    register = await repository.get_active_register(db, company_id=company_id)
    if register is None:
        raise NotFoundError("La empresa no tiene una caja activa configurada.")
    register_id = register._mapping["id"]
    today = await platform_integration.get_company_today(db, company_id=company_id)

    if await repository.get_open_session_for_register(db, register_id=register_id) is not None:
        raise ConflictError("Ya hay una sesión de caja abierta.", code="CASH_SESSION_ALREADY_OPEN")
    if await repository.session_exists_for_date(db, register_id=register_id, session_date=today):
        raise ConflictError(
            "La caja de hoy ya se cerró; no se puede abrir otra el mismo día.",
            code="CASH_SESSION_ALREADY_CLOSED_TODAY",
        )

    session_id = uuid4()
    await repository.insert_session(
        db,
        session_id=session_id,
        company_id=company_id,
        register_id=register_id,
        opened_by=opened_by,
        opening_balance=opening_balance,
        session_date=today,
    )
    row = await repository.get_session(db, company_id=company_id, session_id=session_id)
    assert row is not None
    return _row_to_session(row)


async def get_current_session(db: AsyncSession, *, company_id: UUID) -> SessionOut:
    register = await repository.get_active_register(db, company_id=company_id)
    if register is None:
        raise NotFoundError("La empresa no tiene una caja activa configurada.")
    row = await repository.get_open_session_for_register(db, register_id=register._mapping["id"])
    if row is None:
        raise NotFoundError("No hay una sesión de caja abierta.")
    full_row = await repository.get_session(
        db, company_id=company_id, session_id=row._mapping["id"]
    )
    assert full_row is not None
    return _row_to_session(full_row)


async def get_today_session(db: AsyncSession, *, company_id: UUID) -> SessionOut:
    """La sesión de HOY, esté abierta o ya cerrada.

    `/sessions/current` solo devuelve las abiertas, así que para saber "¿ya
    cerré hoy?" el front tenía que rebuscar en `GET /reports/closings`
    filtrando por la fecha de hoy — un rodeo que además arrastraba un hallazgo
    documentado (el listado de sesiones pagina ascendente, así que `limit=1`
    daba la MÁS VIEJA, no la más reciente).

    Desde 00031 ese rodeo se volvió un problema de permisos y no solo de
    elegancia: `/reports/closings` exige `cashbox.view_history`, así que un
    cajero terminaba necesitando permiso de histórico para saber si ya había
    cerrado su propio turno. Este endpoint responde esa pregunta con
    `cashbox.view`, que es a quien le corresponde.
    """
    register = await repository.get_active_register(db, company_id=company_id)
    if register is None:
        raise NotFoundError("La empresa no tiene una caja activa configurada.")
    today = await platform_integration.get_company_today(db, company_id=company_id)
    row = await repository.get_session_for_date(
        db, company_id=company_id, register_id=register._mapping["id"], session_date=today
    )
    if row is None:
        raise NotFoundError("Todavía no se ha abierto la caja hoy.")
    full_row = await repository.get_session(
        db, company_id=company_id, session_id=row._mapping["id"]
    )
    assert full_row is not None
    return _row_to_session(full_row)


async def assert_can_read_session(
    db: AsyncSession, *, company_id: UUID, session_id: UUID, role_id: UUID
) -> None:
    """`cashbox.view` alcanza para la sesión de HOY; el resto es histórico.

    Quien maneja la caja necesita su turno para operar y para cerrarlo esta
    noche. No necesita —y muchas veces no debe— ver cuánto se movió el mes
    pasado ni qué descuadres hubo en turnos ajenos. Hasta 00031 `cashbox.view`
    abría las dos cosas y no había forma de dar "solo el día de hoy".

    El corte es la FECHA DE LA SESIÓN contra el hoy de la empresa, no el
    estado: una sesión de hoy ya cerrada sigue siendo del turno de quien la
    cerró (necesita poder imprimir su acta), y una sesión abierta que quedó
    de ayer —porque nadie cerró— sigue siendo la sesión en curso.
    """
    row = await repository.get_session(db, company_id=company_id, session_id=session_id)
    if row is None:
        raise NotFoundError("La sesión de caja no existe en esta empresa.")

    today = await platform_integration.get_company_today(db, company_id=company_id)
    if row._mapping["session_date"] == today or row._mapping["status"] == "open":
        return

    if not await security.has_permission(db, role_id, "cashbox.view_history"):
        raise PermissionDeniedError(
            "Solo puedes ver la caja del día de hoy. Ver turnos anteriores "
            "necesita el permiso de histórico de caja.",
            details={"permission": "cashbox.view_history"},
        )


async def get_session(db: AsyncSession, *, company_id: UUID, session_id: UUID) -> SessionOut:
    row = await repository.get_session(db, company_id=company_id, session_id=session_id)
    if row is None:
        raise NotFoundError("La sesión de caja no existe en esta empresa.")
    return _row_to_session(row)


async def list_sessions(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[SessionOut]:
    rows = await repository.list_sessions(db, company_id=company_id, cursor=cursor, limit=limit)
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_session(r) for r in page.items], next_cursor=page.next_cursor)


async def _expected_cash(
    db: AsyncSession, *, company_id: UUID, session_id: UUID, opening_balance: Decimal
) -> tuple[Decimal, list[Row[Any]]]:
    lines = await repository.movement_breakdown(db, company_id=company_id, session_id=session_id)
    # Lo que debería haber EN EL CAJÓN sale del TIPO DE CUENTA, no del medio
    # de pago. Desde 00027 la cuenta es la autoridad sobre dónde quedó la
    # plata: un cobro marcado "efectivo" pero asignado a una cuenta bancaria
    # no está en el cajón, y contarlo dejaría el cierre descuadrado contra un
    # arqueo que nunca lo va a encontrar. Es el mismo criterio que usa
    # `accounts.list_accounts` para el saldo de una cuenta `cash`.
    cash_net = Decimal("0")
    for line in lines:
        m = line._mapping
        if m["account_type"] != "cash":
            continue
        cash_net += m["total"] if m["direction"] == "in" else -m["total"]
    return opening_balance + cash_net, lines


async def get_report(db: AsyncSession, *, company_id: UUID, session_id: UUID) -> SessionReportOut:
    row = await repository.get_session(db, company_id=company_id, session_id=session_id)
    if row is None:
        raise NotFoundError("La sesión de caja no existe en esta empresa.")
    m = row._mapping
    expected_cash, lines = await _expected_cash(
        db, company_id=company_id, session_id=session_id, opening_balance=m["opening_balance"]
    )
    return SessionReportOut(
        session_id=session_id,
        status=m["status"],
        opening_balance=m["opening_balance"],
        expected_cash=expected_cash,
        lines=[
            BreakdownLineOut(
                module=line_row._mapping["module"],
                direction=line_row._mapping["direction"],
                concept=line_row._mapping["concept"],
                payment_method=line_row._mapping["payment_method"],
                account_id=line_row._mapping["account_id"],
                account_name=line_row._mapping["account_name"],
                account_type=line_row._mapping["account_type"],
                total=line_row._mapping["total"],
            )
            for line_row in lines
        ],
    )


async def close_session(
    db: AsyncSession,
    *,
    company_id: UUID,
    session_id: UUID,
    body: SessionCloseIn,
    closed_by: UUID,
) -> SessionOut:
    row = await repository.get_session(db, company_id=company_id, session_id=session_id)
    if row is None:
        raise NotFoundError("La sesión de caja no existe en esta empresa.")
    m = row._mapping
    if m["status"] != "open":
        raise ConflictError("La sesión ya está cerrada.", code="CASH_SESSION_NOT_OPEN")

    expected_cash, _lines = await _expected_cash(
        db, company_id=company_id, session_id=session_id, opening_balance=m["opening_balance"]
    )
    difference = body.counted_cash - expected_cash
    if difference != 0 and not body.difference_reason:
        raise AppError(
            "Todo descuadre exige justificación (sin tolerancia).",
            details={"difference": str(difference)},
        )

    await repository.close_session(
        db,
        company_id=company_id,
        session_id=session_id,
        expected_cash=expected_cash,
        counted_cash=body.counted_cash,
        difference=difference,
        difference_reason=body.difference_reason,
        closed_by=closed_by,
    )
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=closed_by,
        module="cashbox",
        action="close_session",
        entity_type="cash_session",
        entity_id=session_id,
        after={
            "expected_cash": str(expected_cash),
            "counted_cash": str(body.counted_cash),
            "difference": str(difference),
        },
    )
    return await get_session(db, company_id=company_id, session_id=session_id)


async def reopen_session(
    db: AsyncSession, *, company_id: UUID, session_id: UUID, reason: str, actor_id: UUID
) -> SessionOut:
    row = await repository.get_session(db, company_id=company_id, session_id=session_id)
    if row is None:
        raise NotFoundError("La sesión de caja no existe en esta empresa.")
    m = row._mapping
    if m["status"] != "closed":
        raise ConflictError("Solo se puede reabrir una sesión cerrada.")

    if await repository.get_open_session_for_register(db, register_id=m["register_id"]) is not None:
        raise ConflictError(
            "Ya hay otra sesión abierta para esta caja; ciérrala antes de reabrir esta.",
            code="CASH_SESSION_ALREADY_OPEN",
        )

    await repository.reopen_session(db, company_id=company_id, session_id=session_id)
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="cashbox",
        action="reopen_session",
        entity_type="cash_session",
        entity_id=session_id,
        before={"status": "closed"},
        after={"status": "open", "reason": reason},
    )
    return await get_session(db, company_id=company_id, session_id=session_id)


async def create_expense_category(
    db: AsyncSession, *, company_id: UUID, body: ExpenseCategoryCreateIn
) -> ExpenseCategoryOut:
    if await repository.category_name_exists(db, company_id=company_id, name=body.name):
        raise ConflictError("Ya existe una categoría de gasto con ese nombre.")
    category_id = uuid4()
    await repository.insert_expense_category(
        db, category_id=category_id, company_id=company_id, name=body.name
    )
    row = await repository.get_expense_category(db, company_id=company_id, category_id=category_id)
    assert row is not None
    m = row._mapping
    return ExpenseCategoryOut(id=m["id"], name=m["name"], active=m["active"])


async def list_expense_categories(
    db: AsyncSession, *, company_id: UUID
) -> list[ExpenseCategoryOut]:
    rows = await repository.list_expense_categories(db, company_id=company_id)
    return [
        ExpenseCategoryOut(
            id=r._mapping["id"], name=r._mapping["name"], active=r._mapping["active"]
        )
        for r in rows
    ]


async def create_expense(
    db: AsyncSession, *, company_id: UUID, body: ExpenseCreateIn, registered_by: UUID
) -> ExpenseOut:
    category = await repository.get_expense_category(
        db, company_id=company_id, category_id=body.category_id
    )
    if category is None:
        raise NotFoundError("La categoría de gasto no existe en esta empresa.")

    register = await repository.get_active_register(db, company_id=company_id)
    if register is None:
        raise NotFoundError("La empresa no tiene una caja activa configurada.")
    session = await repository.get_open_session_for_register(
        db, register_id=register._mapping["id"]
    )
    if session is None:
        raise CashSessionNotOpenError("No hay una sesión de caja abierta para registrar el gasto.")
    session_id = session._mapping["id"]

    expense_id = uuid4()
    await repository.insert_expense(
        db,
        expense_id=expense_id,
        company_id=company_id,
        session_id=session_id,
        module=body.module,
        category_id=body.category_id,
        description=body.description,
        amount=body.amount,
        payment_method=body.payment_method,
        receipt_url=body.receipt_url,
        registered_by=registered_by,
    )
    # Un gasto SALE: no puede financiarse desde una cuenta por cobrar.
    resolved = await integration.resolve_account_for_movement(
        db,
        company_id=company_id,
        payment_method=body.payment_method,
        account_id=body.account_id,
        direction="out",
    )
    await integration.record_movement(
        db,
        session_id=resolved.session_id,
        company_id=company_id,
        module=body.module,
        direction="out",
        concept="expense",
        amount=body.amount,
        payment_method=body.payment_method,
        reference_type="expense",
        reference_id=expense_id,
        created_by=registered_by,
        account_id=resolved.account_id,
    )
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=registered_by,
        module="cashbox",
        action="create_expense",
        entity_type="expense",
        entity_id=expense_id,
        after={"amount": str(body.amount), "description": body.description},
    )

    row = await repository.get_expense(db, company_id=company_id, expense_id=expense_id)
    assert row is not None
    return _row_to_expense(row)


async def list_expenses(
    db: AsyncSession,
    *,
    company_id: UUID,
    session_id: UUID | None,
    cursor: UUID | None,
    limit: int,
) -> CursorPage[ExpenseOut]:
    rows = await repository.list_expenses(
        db, company_id=company_id, session_id=session_id, cursor=cursor, limit=limit
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_expense(r) for r in page.items], next_cursor=page.next_cursor)
