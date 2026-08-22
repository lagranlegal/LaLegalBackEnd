from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency import require_idempotency_key
from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.accounts import service
from app.modules.accounts.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountStatementOut,
    AccountUpdateIn,
    SettlementIn,
    SettlementOut,
    TransferIn,
    TransferOut,
)

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

_view = require_permission("accounts.view")
# Crear o editar cuentas es configuración del negocio, no operación diaria:
# usa el mismo permiso que el resto de la configuración de empresa.
_manage = require_permission("accounts.manage")
# Liquidar MUEVE PLATA: genera dos movimientos y baja el saldo por cobrar.
# Estuvo detrás de `cashbox.view` —un permiso de solo lectura— hasta 00029,
# o sea que cualquiera que pudiera mirar la caja podía liquidar Sistecrédito.
_settle = require_permission("accounts.settle")
# Trasladar también MUEVE PLATA, y va aparte de `manage` por la misma razón
# que `settle` (00032): quien administra el catálogo de cuentas no
# necesariamente puede sacar el efectivo del cajón y llevarlo al banco.
_transfer = require_permission("accounts.transfer")


@router.post("/transfers", response_model=TransferOut, status_code=201)
async def create_transfer(
    body: TransferIn,
    user: Annotated[CurrentUser, Depends(_transfer)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> TransferOut:
    """Mueve plata entre dos cuentas propias — típicamente consignar en el
    banco el efectivo del día.

    **No es ingreso ni egreso**: es la misma plata en otro bolsillo, así que
    no toca el estado de resultados. Genera dos movimientos
    (`transfer_out` / `transfer_in`) que los reportes excluyen del cálculo de
    ingresos y gastos.

    Si el origen es la cuenta de efectivo **exige caja abierta** y baja el
    efectivo esperado del cierre — que es lo correcto: se consignó, ya no está
    en el cajón. Por eso el traslado va **antes** de cerrar: una sesión
    cerrada es inmutable y meterle un movimiento invalidaría un acta ya
    cuadrada.
    """
    return await service.create_transfer(
        db,
        company_id=user.company_id,
        body=body,
        actor_id=user.id,
        idempotency_key=idempotency_key,
    )


@router.get("/transfers", response_model=CursorPage[TransferOut])
async def list_transfers(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CursorPage[TransferOut]:
    return await service.list_transfers(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


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
    user: Annotated[CurrentUser, Depends(_settle)],
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


@router.get("/{account_id}/statement", response_model=AccountStatementOut)
async def get_statement(
    account_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    from_date: Annotated[date, Query(description="Inclusivo, en la zona horaria de la empresa.")],
    to_date: Annotated[date, Query(description="Inclusivo, en la zona horaria de la empresa.")],
) -> AccountStatementOut:
    """Extracto de la cuenta: movimientos con **saldo corriente**, para
    conciliar contra el extracto real del banco.

    Completa lo que 00024 dejó escrito y a medias — *"solo las cuentas `cash`
    entran al arqueo; el resto lleva saldo corriente y se concilia aparte"*.
    El saldo ya se mostraba, pero no CÓMO se llegó a él, y sin eso no hay
    forma de encontrar una diferencia contra el banco.

    En cuentas de **efectivo** `has_running_balance` viene en `false` y los
    saldos en `null`. No es una carencia: la base del cajón se redeclara en
    cada apertura y no es un movimiento, así que acumular el histórico daría
    un número sin significado. El efectivo se verifica **contando**, en el
    arqueo. Sus movimientos sí se devuelven — sirven para ver qué pasó por el
    cajón.
    """
    return await service.get_statement(
        db,
        company_id=user.company_id,
        account_id=account_id,
        from_date=from_date,
        to_date=to_date,
    )
