from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.cashbox import service
from app.modules.cashbox.schemas import (
    ExpenseCategoryCreateIn,
    ExpenseCategoryOut,
    ExpenseCreateIn,
    ExpenseOut,
    SessionCloseIn,
    SessionOpenIn,
    SessionOut,
    SessionReopenIn,
    SessionReportOut,
)

router = APIRouter(prefix="/api/v1/cashbox", tags=["cashbox"])

_view = require_permission("cashbox.view")
# 00031: el LISTADO de sesiones es histórico por definición — la de hoy sale
# por `/sessions/current`. El detalle y el reporte de UNA sesión se chequean
# dentro del service (`assert_can_read_session`), porque ahí el permiso
# depende de si esa sesión es la de hoy o la de un turno anterior.
_view_history = require_permission("cashbox.view_history")
_open_close = require_permission("cashbox.open_close")
_reopen = require_permission("cashbox.reopen")
_expense = require_permission("cashbox.expense")


@router.post("/sessions/open", response_model=SessionOut, status_code=201)
async def open_session(
    body: SessionOpenIn,
    user: Annotated[CurrentUser, Depends(_open_close)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SessionOut:
    return await service.open_session(
        db, company_id=user.company_id, opened_by=user.id, opening_balance=body.opening_balance
    )


@router.get("/sessions/current", response_model=SessionOut)
async def get_current_session(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SessionOut:
    return await service.get_current_session(db, company_id=user.company_id)


@router.get("/sessions/today", response_model=SessionOut)
async def get_today_session(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SessionOut:
    """La sesión de HOY, abierta o ya cerrada (404 si no se ha abierto).

    Responde "¿qué pasó con la caja hoy?" con `cashbox.view`. Antes el front
    lo deducía de `GET /reports/closings`, que desde 00031 exige permiso de
    histórico — un cajero habría necesitado ver los cierres de todo el negocio
    para saber si ya había cerrado su propio turno.
    """
    return await service.get_today_session(db, company_id=user.company_id)


@router.get("/sessions", response_model=CursorPage[SessionOut])
async def list_sessions(
    user: Annotated[CurrentUser, Depends(_view_history)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[SessionOut]:
    """Histórico de turnos. La sesión en curso sale por `/sessions/current`,
    que solo pide `cashbox.view`: un cajero puede operar su día sin poder
    revisar los cierres de días anteriores.
    """
    return await service.list_sessions(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SessionOut:
    """La de hoy con `cashbox.view`; la de un turno anterior exige además
    `cashbox.view_history` (00031)."""
    await service.assert_can_read_session(
        db, company_id=user.company_id, session_id=session_id, role_id=user.role_id
    )
    return await service.get_session(db, company_id=user.company_id, session_id=session_id)


@router.get("/sessions/{session_id}/report", response_model=SessionReportOut)
async def get_session_report(
    session_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SessionReportOut:
    """El acta del turno de hoy con `cashbox.view` —hace falta para cerrarlo—;
    la de cualquier otro exige además `cashbox.view_history`."""
    await service.assert_can_read_session(
        db, company_id=user.company_id, session_id=session_id, role_id=user.role_id
    )
    return await service.get_report(db, company_id=user.company_id, session_id=session_id)


@router.post("/sessions/{session_id}/close", response_model=SessionOut)
async def close_session(
    session_id: UUID,
    body: SessionCloseIn,
    user: Annotated[CurrentUser, Depends(_open_close)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SessionOut:
    return await service.close_session(
        db, company_id=user.company_id, session_id=session_id, body=body, closed_by=user.id
    )


@router.post("/sessions/{session_id}/reopen", response_model=SessionOut)
async def reopen_session(
    session_id: UUID,
    body: SessionReopenIn,
    user: Annotated[CurrentUser, Depends(_reopen)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SessionOut:
    return await service.reopen_session(
        db, company_id=user.company_id, session_id=session_id, reason=body.reason, actor_id=user.id
    )


@router.get("/expense-categories", response_model=list[ExpenseCategoryOut])
async def list_expense_categories(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[ExpenseCategoryOut]:
    return await service.list_expense_categories(db, company_id=user.company_id)


@router.post("/expense-categories", response_model=ExpenseCategoryOut, status_code=201)
async def create_expense_category(
    body: ExpenseCategoryCreateIn,
    user: Annotated[CurrentUser, Depends(_expense)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ExpenseCategoryOut:
    return await service.create_expense_category(db, company_id=user.company_id, body=body)


@router.get("/expenses", response_model=CursorPage[ExpenseOut])
async def list_expenses(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    session_id: Annotated[UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CursorPage[ExpenseOut]:
    return await service.list_expenses(
        db,
        company_id=user.company_id,
        session_id=session_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
async def create_expense(
    body: ExpenseCreateIn,
    user: Annotated[CurrentUser, Depends(_expense)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ExpenseOut:
    return await service.create_expense(
        db, company_id=user.company_id, body=body, registered_by=user.id
    )
