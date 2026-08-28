from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.reports import service
from app.modules.reports.schemas import (
    ClosingHistoryOut,
    ClosingsBreakdownOut,
    DashboardOut,
    IncomeStatementOut,
    InventoryValuationOut,
    PawnPerformanceOut,
    PayablesOut,
    ProfitSummaryOut,
    StaleInventoryOut,
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


@router.get("/closings-breakdown", response_model=ClosingsBreakdownOut)
async def get_closings_breakdown(
    user: Annotated[CurrentUser, Depends(_closings)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> ClosingsBreakdownOut:
    """Módulo × concepto × medio × cuenta × día, sumado sobre TODAS las
    sesiones cerradas del rango en una sola consulta — reemplaza el patrón
    del front de pedir `GET /cashbox/sessions/{id}/report` una vez por cada
    sesión del rango (hasta 90 requests para 90 días, docs/PENDIENTES_
    FRONTEND.md #11). Mismos dos permisos que `/closings`: es un reporte del
    histórico de caja.
    """
    return await service.get_closings_breakdown(
        db, company_id=user.company_id, from_date=from_date, to_date=to_date
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


@router.get("/payables", response_model=PayablesOut)
async def get_payables(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PayablesOut:
    """Cuentas por pagar a proveedores, con antigüedad (0-30 / 31-60 / +60).

    Responde "¿cuánto debo, a quién, y desde hace cuánto?". Cada compra ya
    sabía si estaba pagada desde 00020, pero ninguna pantalla lo sumaba: el
    dato estaba guardado y la pregunta no tenía respuesta.

    La antigüedad se mide desde `entry_date` (cuándo entró la mercancía), que
    es la fecha desde la que el proveedor cuenta el plazo — cargar hoy una
    factura de hace dos meses no la vuelve reciente.
    """
    return await service.get_payables(db, company_id=user.company_id)


@router.get("/inventory-valuation", response_model=InventoryValuationOut)
async def get_inventory_valuation(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> InventoryValuationOut:
    """ "¿Cuánta plata tengo en mercancía?" — el activo más grande del negocio.

    Valorado **al costo**, que es lo correcto contablemente y lo que sale de la
    identificación específica. `retail_value` se expone aparte como referencia
    (qué se cobraría si se vendiera todo hoy) y NO es el valor del inventario:
    contar la utilidad antes de venderla es el error clásico.
    """
    return await service.get_inventory_valuation(db, company_id=user.company_id)


@router.get("/stale-inventory", response_model=StaleInventoryOut)
async def get_stale_inventory(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    threshold_days: Annotated[int, Query(ge=1, le=3650)] = 90,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> StaleInventoryOut:
    """Mercancía disponible sin rotación — plata congelada en la vitrina.

    Se mide sobre el lote disponible más ANTIGUO de cada producto: si algo
    entró hace un año y se repuso ayer, lo congelado es la pieza vieja, y usar
    la fecha nueva la escondería justo cuando más importa verla.
    """
    return await service.get_stale_inventory(
        db, company_id=user.company_id, threshold_days=threshold_days, limit=limit
    )


@router.get("/income-statement", response_model=IncomeStatementOut)
async def get_income_statement(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    from_date: Annotated[date, Query(description="Inclusivo, en la zona horaria de la empresa.")],
    to_date: Annotated[date, Query(description="Inclusivo, en la zona horaria de la empresa.")],
) -> IncomeStatementOut:
    """Estado de resultados: **ingresos − costo de ventas − gastos = utilidad**.

    Es la vista de arriba que faltaba: `/profit` cubre la tienda y
    `/pawn-performance` el empeño —bien separados, porque se miden distinto—
    pero nadie los sumaba en un solo resultado.

    Y corrige un número equivocado: la "utilidad operativa" que mostraba
    `/reportes` era `ingresos − gastos` y **nunca restaba el costo de ventas**,
    así que sobreestimaba la ganancia por todo lo que costó la mercancía.

    Sale de los DOCUMENTOS y no de los movimientos de caja: el desglose de
    caja solo cubre sesiones cerradas (faltaría lo de hoy), y una venta con
    Sistecrédito es ingreso aunque todavía no haya entrado la plata — el
    ingreso se reconoce al vender, no al cobrar.

    Los movimientos de CAPITAL (préstamos, abonos) y la compra de inventario
    se devuelven aparte, fuera del resultado: prestar no es gasto y cobrar no
    es ganancia; comprar mercancía es convertir efectivo en activo, y se
    vuelve gasto cuando se vende.
    """
    return await service.get_income_statement(
        db, company_id=user.company_id, from_date=from_date, to_date=to_date
    )
