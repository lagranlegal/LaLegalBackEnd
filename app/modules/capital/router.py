from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency import require_idempotency_key
from app.common.pagination import CursorPage, decode_date_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.capital import service
from app.modules.capital.schemas import (
    CapitalMovementOut,
    CapitalPositionOut,
    ContributionIn,
    WithdrawalIn,
)

router = APIRouter(prefix="/api/v1/capital", tags=["capital"])

# Tres permisos y no uno, porque no son la misma decisión (00054). Ver la
# migración para el razonamiento completo; en corto: ver el patrimonio del
# dueño no es dato de mostrador, meter plata es benigno, y SACARLA es la
# única operación de la app que le quita capital a la empresa sin nada a
# cambio.
_view = require_permission("capital.view")
_contribute = require_permission("capital.contribute")
_withdraw = require_permission("capital.withdraw")


@router.post("/contributions", response_model=CapitalMovementOut, status_code=201)
async def create_contribution(
    body: ContributionIn,
    user: Annotated[CurrentUser, Depends(_contribute)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> CapitalMovementOut:
    """**Aporte de capital**: el dueño mete plata al negocio.

    El caso típico es el que motivó el módulo: están bajos de capital para
    prestar y el dueño inyecta dinero para seguir trabajando.

    **No es un ingreso.** No se vendió nada ni se cobró un interés: es
    patrimonio. Genera un `cash_movement` con concepto propio
    (`owner_contribution`) y **no toca el estado de resultados** — que lee
    documentos de venta, abono y gasto, y este no es ninguno de los tres.

    Si la cuenta destino es de efectivo **exige caja abierta**: no se pueden
    meter billetes a un cajón cerrado, y sin sesión el arqueo no cuadraría.
    Por transferencia o a una cuenta de banco funciona a cualquier hora.
    """
    return await service.create_contribution(
        db,
        company_id=user.company_id,
        body=body,
        actor_id=user.id,
        idempotency_key=idempotency_key,
    )


@router.post("/withdrawals", response_model=CapitalMovementOut, status_code=201)
async def create_withdrawal(
    body: WithdrawalIn,
    user: Annotated[CurrentUser, Depends(_withdraw)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> CapitalMovementOut:
    """**Retiro del dueño**: utilidades o devolución de capital.

    **No es un gasto.** Registrarlo como tal falsearía la utilidad del
    período por todo el monto retirado — el mismo error que este proyecto ya
    pagó tres veces ("prestar no es un gasto, cobrar no es una ganancia").

    **No se bloquea si no hay utilidad**, y es deliberado: el dueño puede
    retirar su propio capital y está en su derecho. Lo que la app hace es
    decirle qué está haciendo — consultar `GET /capital/position` antes de
    confirmar y mostrarle la utilidad del período, lo ya retirado y **dónde
    está realmente la plata**. Mismo criterio que el LTV y el plazo de
    devolución: advertir sin estorbar.

    Lo único que sí se rechaza es retirar de una cuenta más de lo que tiene:
    eso no es una política de negocio, es un imposible físico.

    `notes` es obligatorio. Un retiro sin motivo es la clase de línea que
    nadie puede explicar seis meses después, y es plata que salió.
    """
    return await service.create_withdrawal(
        db,
        company_id=user.company_id,
        body=body,
        actor_id=user.id,
        idempotency_key=idempotency_key,
    )


@router.get("/position", response_model=CapitalPositionOut)
async def get_position(
    from_date: Annotated[date, Query()],
    to_date: Annotated[date, Query()],
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CapitalPositionOut:
    """**¿Cuánto se puede retirar, y dónde está la plata?**

    La pregunta que el dueño no puede contestar de memoria. En una
    compraventa la mayor parte del capital **no está en el cajón**: está
    prestado y en vitrina. Retirar "lo que hay en caja" no es retirar
    utilidad — es descapitalizar.

    Devuelve la utilidad del período (misma definición que
    `/reports/income-statement`, calculada por el mismo código), los aportes
    y retiros ya registrados, y el capital repartido en sus tres formas:
    disponible (cajón + bóveda + banco), prestado, e inventario **al costo**
    — nunca al precio de venta, que sería contar la utilidad antes de
    venderla.

    `distributable` puede salir **negativo** a propósito: significa que lo
    retirado en el período ya superó la utilidad, o sea que se está sacando
    capital. Ese número es el aviso.
    """
    return await service.get_position(
        db, company_id=user.company_id, from_date=from_date, to_date=to_date
    )


@router.get("/movements", response_model=CursorPage[CapitalMovementOut])
async def list_movements(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    direction: Annotated[str | None, Query(pattern="^(contribution|withdrawal)$")] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CursorPage[CapitalMovementOut]:
    """Historial de aportes y retiros, **del más reciente al más antiguo**.

    Ordenado por la fecha del DOCUMENTO, no por `created_at` ni por `id`: el
    dueño puede registrar el lunes el aporte que hizo el viernes, y ese
    aporte pertenece al viernes. Un histórico de plata ordenado por un UUID
    aleatorio pagina bien y no se puede leer.
    """
    return await service.list_movements(
        db,
        company_id=user.company_id,
        cursor=decode_date_cursor(cursor) if cursor else None,
        limit=limit,
        direction=direction,
    )


@router.get("/movements/{movement_id}", response_model=CapitalMovementOut)
async def get_movement(
    movement_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CapitalMovementOut:
    return await service.get_movement(db, company_id=user.company_id, movement_id=movement_id)
