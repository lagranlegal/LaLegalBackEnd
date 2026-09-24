"""Lo que otros módulos pueden preguntarle a `reports` (CLAUDE.md regla 2 —
nunca importar `reports.service` desde otro módulo, solo esto).

Hoy hay una sola pregunta, y viene del módulo `capital`: **¿cuánta utilidad
hubo en el período?** El dueño la necesita antes de retirar plata, porque un
retiro mayor a la utilidad es una devolución de capital se llame como se
llame — y en una compraventa eso es lo que descapitaliza.

La definición NO se reimplementa acá: se delega en `get_income_statement`,
que ya la resuelve una sola vez (ingresos − costo de ventas − gastos) con
todas sus salvedades documentadas. Dos formas de calcular la misma utilidad
terminan divergiendo, y este proyecto ya tuvo dos cifras contradiciéndose en
la misma pantalla.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports import service


async def get_operating_profit(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> Decimal:
    """Utilidad operativa del período: ingresos − costo de ventas − gastos.

    NO incluye los movimientos de capital del dueño, y no hace falta
    excluirlos: `get_income_statement` lee DOCUMENTOS (`sale`,
    `contract_payment`, `expense`), nunca `cash_movement`. Un aporte o un
    retiro no es ninguno de esos tres, así que queda fuera del resultado por
    construcción — sin una línea de exclusión que alguien pueda olvidar.
    """
    estado = await service.get_income_statement(
        db, company_id=company_id, from_date=from_date, to_date=to_date
    )
    return estado.operating_profit


async def get_stale_inventory_summary(
    db: AsyncSession, *, company_id: UUID, threshold_days: int = 90
) -> dict[str, object]:
    """Para el resumen SEMANAL a la empresa (docs/NOTIFICACIONES.md §2.4, E7):
    los totales del universo, no la lista — el detalle está en la pantalla.
    Mismo umbral por defecto que `GET /reports/stale-inventory`."""
    stale = await service.get_stale_inventory(
        db, company_id=company_id, threshold_days=threshold_days, limit=1
    )
    return {
        "threshold_days": stale.threshold_days,
        "product_count": stale.product_count,
        "total_cost_value": str(stale.total_cost_value),
    }


async def get_payables_summary(db: AsyncSession, *, company_id: UUID) -> dict[str, object]:
    """Para el resumen SEMANAL (§2.4, E5). El sistema no guarda fecha de
    vencimiento de una compra a crédito, así que "vencida" no existe: se
    reporta el total y la franja de más de 60 días de `GET /reports/payables`."""
    payables = await service.get_payables(db, company_id=company_id)
    return {
        "total": str(payables.total),
        "entry_count": payables.entry_count,
        "days_over_60": str(payables.days_over_60),
    }
