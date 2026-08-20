from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency import require_idempotency_key
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.accounts import service
from app.modules.accounts.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountUpdateIn,
    SettlementIn,
    SettlementOut,
)

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

_view = require_permission("cashbox.view")
# Crear o editar cuentas es configuración del negocio, no operación diaria:
# usa el mismo permiso que el resto de la configuración de empresa.
_manage = require_permission("company.configure")


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    include_inactive: Annotated[bool, Query()] = False,
) -> list[AccountOut]:
    """Cuentas con su saldo.

    En una cuenta `settlement` (Sistecrédito) el saldo es lo que te DEBEN, no
    lo que tienes disponible.
    """
    return await service.list_accounts(
        db, company_id=user.company_id, include_inactive=include_inactive
    )


@router.post("", response_model=AccountOut, status_code=201)
async def create_account(
    body: AccountCreateIn,
    user: Annotated[CurrentUser, Depends(_manage)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AccountOut:
    return await service.create_account(db, company_id=user.company_id, body=body)


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: UUID,
    body: AccountUpdateIn,
    user: Annotated[CurrentUser, Depends(_manage)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> AccountOut:
    return await service.update_account(
        db, company_id=user.company_id, account_id=account_id, body=body
    )


@router.post("/{account_id}/settle", response_model=SettlementOut)
async def settle_account(
    account_id: UUID,
    body: SettlementIn,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    _idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SettlementOut:
    """Registra la liquidación de una cuenta por cobrar.

    Se informa cuánto se liquidó y cuánto entró realmente; **la comisión no se
    digita**: es la diferencia, y se deriva. Así el sistema no puede quedar
    desactualizado respecto al contrato con el convenio.
    """
    return await service.settle_account(
        db,
        company_id=user.company_id,
        account_id=account_id,
        body=body,
        actor_id=user.id,
    )
