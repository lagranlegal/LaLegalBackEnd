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
