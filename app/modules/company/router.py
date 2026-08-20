from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.company import service
from app.modules.company.schemas import CompanySettingsOut, CompanySettingsUpdateIn

router = APIRouter(prefix="/api/v1/company", tags=["company"])

_configure = require_permission("company.configure")


@router.get("/settings", response_model=CompanySettingsOut)
async def get_settings(
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CompanySettingsOut:
    return await service.get_settings(db, company_id=user.company_id)


@router.patch("/settings", response_model=CompanySettingsOut)
async def update_settings(
    body: CompanySettingsUpdateIn,
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CompanySettingsOut:
    return await service.update_settings(
        db, company_id=user.company_id, body=body, actor_id=user.id
    )
