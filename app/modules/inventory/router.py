from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.inventory import service
from app.modules.inventory.schemas import (
    EntryCreateIn,
    EntryOut,
    ExitCreateIn,
    ExitOut,
    ItemOut,
    ItemPublishIn,
    ItemUpdateIn,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

_view = require_permission("inventory.view")
_create = require_permission("inventory.create")
_exit_perm = require_permission("inventory.exit")


@router.post("/entries", response_model=EntryOut, status_code=201)
async def create_entry(
    body: EntryCreateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> EntryOut:
    return await service.create_entry(
        db, company_id=user.company_id, body=body, registered_by=user.id
    )


@router.get("/entries", response_model=CursorPage[EntryOut])
async def list_entries(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[EntryOut]:
    return await service.list_entries(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.get("/entries/{entry_id}", response_model=EntryOut)
async def get_entry(
    entry_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> EntryOut:
    return await service.get_entry(db, company_id=user.company_id, entry_id=entry_id)


@router.post("/exits", response_model=ExitOut, status_code=201)
async def create_exit(
    body: ExitCreateIn,
    user: Annotated[CurrentUser, Depends(_exit_perm)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ExitOut:
    return await service.create_exit(
        db, company_id=user.company_id, body=body, registered_by=user.id
    )


@router.get("/exits", response_model=CursorPage[ExitOut])
async def list_exits(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[ExitOut]:
    return await service.list_exits(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.get("/items", response_model=CursorPage[ItemOut])
async def list_items(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
) -> CursorPage[ItemOut]:
    return await service.list_items(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        status_filter=status,
    )


@router.get("/items/{item_id}", response_model=ItemOut)
async def get_item(
    item_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ItemOut:
    return await service.get_item(db, company_id=user.company_id, item_id=item_id)


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: UUID,
    body: ItemUpdateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ItemOut:
    return await service.update_item(db, company_id=user.company_id, item_id=item_id, body=body)


@router.post("/items/{item_id}/publish", response_model=ItemOut)
async def publish_item(
    item_id: UUID,
    body: ItemPublishIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ItemOut:
    return await service.publish_item(db, company_id=user.company_id, item_id=item_id, body=body)
