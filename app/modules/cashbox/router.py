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


@router.get("/sessions", response_model=CursorPage[SessionOut])
async def list_sessions(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[SessionOut]:
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
    return await service.get_session(db, company_id=user.company_id, session_id=session_id)


@router.get("/sessions/{session_id}/report", response_model=SessionReportOut)
async def get_session_report(
    session_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SessionReportOut:
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
