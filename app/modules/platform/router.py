from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.db import get_db
from app.core.security import TokenClaims, require_super_admin
from app.modules.platform import service
from app.modules.platform.schemas import (
    CompanyCreateIn,
    CompanyOut,
    PlanOut,
    SubscriptionEventOut,
    SubscriptionExtendIn,
)

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


@router.post("/companies", response_model=CompanyOut, status_code=201)
async def create_company(
    body: CompanyCreateIn,
    _claims: Annotated[TokenClaims, Depends(require_super_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyOut:
    return await service.create_company_defaults(
        db,
        name=body.name,
        plan_code=body.plan_code,
        subscription_expires_at=body.subscription_expires_at,
        first_admin_email=body.first_admin_email,
        first_admin_full_name=body.first_admin_full_name,
    )


@router.get("/companies", response_model=CursorPage[CompanyOut])
async def list_companies(
    _claims: Annotated[TokenClaims, Depends(require_super_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[CompanyOut]:
    return await service.list_companies(
        db, cursor=decode_cursor(cursor) if cursor else None, limit=limit
    )


@router.get("/companies/{company_id}", response_model=CompanyOut)
async def get_company(
    company_id: UUID,
    _claims: Annotated[TokenClaims, Depends(require_super_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyOut:
    return await service.get_company(db, company_id=company_id)


@router.post("/companies/{company_id}/suspend", response_model=CompanyOut)
async def suspend_company(
    company_id: UUID,
    claims: Annotated[TokenClaims, Depends(require_super_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyOut:
    return await service.suspend_company(db, company_id=company_id, actor_id=claims.sub)


@router.post("/companies/{company_id}/activate", response_model=CompanyOut)
async def activate_company(
    company_id: UUID,
    claims: Annotated[TokenClaims, Depends(require_super_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyOut:
    return await service.activate_company(db, company_id=company_id, actor_id=claims.sub)


@router.post("/companies/{company_id}/subscription/extend", status_code=204)
async def extend_subscription(
    company_id: UUID,
    body: SubscriptionExtendIn,
    claims: Annotated[TokenClaims, Depends(require_super_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.extend_subscription(
        db,
        company_id=company_id,
        new_expires_at=body.new_expires_at,
        notes=body.notes,
        actor_id=claims.sub,
        amount=body.amount,
    )


@router.get(
    "/companies/{company_id}/subscription/events",
    response_model=CursorPage[SubscriptionEventOut],
)
async def list_subscription_events(
    company_id: UUID,
    _claims: Annotated[TokenClaims, Depends(require_super_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: str | None = None,
    limit: int = 50,
) -> CursorPage[SubscriptionEventOut]:
    """Historial comercial de la empresa: altas, renovaciones (con monto y
    notas), suspensiones, reactivaciones y vencimientos. Distinto del
    `audit_log`, que es el registro de seguridad y además es tenant-scoped
    por RLS — un super-admin no puede leer el de otra empresa.
    """
    return await service.list_subscription_events(
        db,
        company_id=company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(
    _claims: Annotated[TokenClaims, Depends(require_super_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PlanOut]:
    return await service.list_plans(db)
