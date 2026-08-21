from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.reports import service
from app.modules.reports.schemas import (
    ClosingHistoryOut,
    DashboardOut,
    PawnPerformanceOut,
    ProfitSummaryOut,
)

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

_view = require_permission("reports.view")


async def _closings(
    user: Annotated[CurrentUser, Depends(_view)],
    _history: Annotated[CurrentUser, Depends(require_permission("cashbox.view_history"))],
) -> CurrentUser:
    """Los DOS permisos: es un reporte (`reports.view`) del histórico de caja
    (`cashbox.view_history`, 00031). Componer dos `Depends` es suficiente —
    FastAPI resuelve ambos y cualquiera de los dos aborta con 403."""
    return user


@router.get("/dashboard", response_model=DashboardOut)
async def get_dashboard(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> DashboardOut:
    return await service.get_dashboard(db, company_id=user.company_id)


@router.get("/closings", response_model=CursorPage[ClosingHistoryOut])
async def list_closings(
    user: Annotated[CurrentUser, Depends(_closings)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> CursorPage[ClosingHistoryOut]:
    """Exige `reports.view` **y** `cashbox.view_history` (00031).

    Es el mismo dato que `GET /cashbox/sessions`, expuesto desde el módulo de
    reportes. Si se le quita el histórico al cajero por un lado y se le deja
    esta puerta abierta por el otro, el permiso no restringe nada — sería un
    control que se rodea escribiendo otra URL.
    """
    return await service.list_closings(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/profit", response_model=ProfitSummaryOut)
async def get_profit_summary(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    from_date: Annotated[date, Query(description="Inclusivo, en la zona horaria de la empresa.")],
    to_date: Annotated[date, Query(description="Inclusivo, en la zona horaria de la empresa.")],
) -> ProfitSummaryOut:
    """Utilidad BRUTA del período: lo que entró por ventas menos lo que
    costó la mercancía vendida. Responde "¿cuánto gané con lo que vendí?",
    que hasta ahora no tenía respuesta en ningún endpoint.

    No descuenta gastos operativos (esos viven en caja y se reportan aparte)
    ni cubre el módulo de empeño, cuya rentabilidad son los intereses
    cobrados y no tiene costo de ventas asociado.
    """
    return await service.get_profit_summary(
        db, company_id=user.company_id, from_date=from_date, to_date=to_date
    )


@router.get("/pawn-performance", response_model=PawnPerformanceOut)
async def get_pawn_performance(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    from_date: Annotated[date, Query(description="Inclusivo, en la zona horaria de la empresa.")],
    to_date: Annotated[date, Query(description="Inclusivo, en la zona horaria de la empresa.")],
) -> PawnPerformanceOut:
    """Rentabilidad del empeño: intereses cobrados sobre el capital prestado.

    Complementa `/reports/profit`, que cubre la tienda. Son preguntas
    distintas: la tienda tiene costo de ventas y se mide por margen; el
    empeño no tiene costo de ventas y se mide por rendimiento sobre el
    capital inmovilizado en la cartera.

    Los intereses salen de `contract_payment` (el documento) y no de los
    movimientos de caja: el desglose de caja solo cubre sesiones cerradas y
    no separa el descuento de interés, que acá importa porque erosiona el
    rendimiento.
    """
    return await service.get_pawn_performance(
        db, company_id=user.company_id, from_date=from_date, to_date=to_date
    )
