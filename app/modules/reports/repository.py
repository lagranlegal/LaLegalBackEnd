from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_CLOSING_COLUMNS = (
    "id, session_date, opening_balance, expected_cash, counted_cash, difference, "
    "difference_reason, closed_by, closed_at"
)


async def contract_kpis(db: AsyncSession, *, company_id: UUID, today: date) -> Row[Any]:
    result = await db.execute(
        text(
            """
            select
              count(*) filter (where status = 'active') as active_count,
              count(*) filter (where status = 'in_arrears') as in_arrears_count,
              count(*) filter (where status = 'in_extension') as in_extension_count,
              count(*) filter (
                where status = 'in_extension' and extension_ends_at < :today
              ) as ready_for_auction_count,
              count(*) filter (where status = 'auctioned') as auctioned_count,
              coalesce(
                sum(capital_balance) filter (
                  where status in ('active', 'in_arrears', 'in_extension')
                ),
                0
              ) as capital_outstanding
            from public.contract
            where company_id = :company_id
            """
        ),
        {"company_id": str(company_id), "today": today},
    )
    return result.one()


async def sales_kpis(db: AsyncSession, *, company_id: UUID, tz_name: str, today: date) -> Row[Any]:
    result = await db.execute(
        text(
            """
            select
              coalesce(
                sum(total) filter (where (sold_at at time zone :tz)::date = :today), 0
              ) as today_total,
              count(*) filter (where (sold_at at time zone :tz)::date = :today) as today_count,
              coalesce(
                sum(total) filter (
                  where date_trunc('month', sold_at at time zone :tz)
                        = date_trunc('month', :today)
                ),
                0
              ) as month_total
            from public.sale
            where company_id = :company_id and status = 'completed'
            """
        ),
        {"company_id": str(company_id), "tz": tz_name, "today": today},
    )
    return result.one()


async def inventory_kpis(db: AsyncSession, *, company_id: UUID) -> Row[Any]:
    result = await db.execute(
        text(
            """
            select
              count(*) filter (where status = 'available') as available_count,
              coalesce(
                sum(cost * quantity) filter (where status = 'available'), 0
              ) as available_value,
              count(*) filter (where status = 'draft') as draft_count
            from public.inventory_item
            where company_id = :company_id
            """
        ),
        {"company_id": str(company_id)},
    )
    return result.one()


async def current_open_session(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select id, opened_at, opening_balance
            from public.cash_session
            where company_id = :company_id and status = 'open'
            order by opened_at desc
            limit 1
            """
        ),
        {"company_id": str(company_id)},
    )
    return result.first()


async def list_closings(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    from_date: date | None,
    to_date: date | None,
) -> list[Row[Any]]:
    query = (
        f"select {_CLOSING_COLUMNS} from public.cash_session "
        "where company_id = :company_id and status = 'closed'"
    )
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if from_date is not None:
        query += " and session_date >= :from_date"
        params["from_date"] = from_date
    if to_date is not None:
        query += " and session_date <= :to_date"
        params["to_date"] = to_date
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def profit_summary(
    db: AsyncSession, *, company_id: UUID, tz_name: str, from_date: date, to_date: date
) -> Row[Any]:
    """Utilidad BRUTA del período: ingreso por ventas menos su costo de ventas.

    El costo sale de `sale_line.unit_cost` —congelado al vender (00019)— y no
    de `inventory_item.cost`: un reporte de un período cerrado no debe cambiar
    porque alguien corrija hoy el costo de un artículo.

    Solo ventas `completed`. Una venta anulada no generó ingreso ni consumió
    inventario (la anulación repone el stock), así que incluirla inflaría
    ambos lados y ensuciaría el margen.

    `discount_amount` se resta del ingreso: es un menor ingreso real, no un
    gasto. Vive en `sale`, no en la línea, así que se agrega aparte y se
    descuenta del total (por eso el subquery en vez de un join plano — un join
    con las líneas repetiría el descuento por cada línea de la venta).

    Las fechas se comparan en la zona horaria de la EMPRESA (§10
    ARCHITECTURE.md), no en UTC: `sold_at` es timestamptz y el "hoy" del
    negocio termina a medianoche de Bogotá, no de Londres.
    """
    result = await db.execute(
        text(
            """
            with ventas as (
                select id, discount_amount
                from public.sale
                where company_id = :company_id
                  and status = 'completed'
                  and (sold_at at time zone :tz)::date between :from_date and :to_date
            ),
            lineas as (
                select
                  coalesce(sum(sl.subtotal), 0)                  as bruto,
                  coalesce(sum(sl.unit_cost * sl.quantity), 0)   as costo,
                  coalesce(sum(sl.quantity), 0)                  as unidades
                from public.sale_line sl
                join ventas v on v.id = sl.sale_id
                where sl.company_id = :company_id
            )
            select
              (select count(*) from ventas)                                as sale_count,
              (select coalesce(sum(discount_amount), 0) from ventas)       as discounts,
              lineas.bruto                                                 as gross_revenue,
              lineas.costo                                                 as cost_of_goods_sold,
              lineas.unidades                                              as units_sold
            from lineas
            """
        ),
        {
            "company_id": str(company_id),
            "tz": tz_name,
            "from_date": from_date,
            "to_date": to_date,
        },
    )
    return result.one()


async def pawn_performance(
    db: AsyncSession, *, company_id: UUID, tz_name: str, from_date: date, to_date: date
) -> Row[Any]:
    """Rentabilidad del empeño. A diferencia de la tienda, acá NO hay costo de
    ventas: la rentabilidad son los intereses cobrados sobre el capital
    prestado — rendimiento sobre capital, no margen sobre costo.

    Los intereses salen de `contract_payment`, el documento, y NO de los
    movimientos de caja como hace `/reportes` hoy. Dos motivos: el desglose de
    caja solo cubre sesiones CERRADAS (los abonos de hoy no aparecerían) y
    agrupa por concepto sin separar el descuento de interés, que sí importa
    acá porque erosiona el rendimiento y es una acción con permiso especial.

    `capital_outstanding` es el corte de HOY, no del final del rango: el
    esquema no guarda `closed_at` en `contract` ni un histórico de saldos, así
    que no hay forma exacta de saber cuánta cartera había en una fecha pasada.
    Se devuelve tal cual, y el llamador lo rotula como corte actual en vez de
    fabricar una reconstrucción aproximada — un número financiero inventado es
    peor que uno ausente.
    """
    result = await db.execute(
        text(
            """
            with pagos as (
                select
                  coalesce(sum(interest_amount), 0) as interest_collected,
                  coalesce(sum(capital_amount), 0)  as capital_recovered,
                  coalesce(sum(discount_amount), 0) as interest_discounts,
                  count(*)                          as payment_count
                from public.contract_payment
                where company_id = :company_id
                  and (paid_at at time zone :tz)::date between :from_date and :to_date
            ),
            nuevos as (
                select
                  coalesce(sum(principal), 0) as capital_disbursed,
                  count(*)                    as contracts_opened
                from public.contract
                where company_id = :company_id
                  and start_date between :from_date and :to_date
            ),
            cartera as (
                select
                  coalesce(
                    sum(capital_balance) filter (
                      where status in ('active', 'in_arrears', 'in_extension')
                    ), 0
                  ) as capital_outstanding,
                  count(*) filter (
                    where status in ('active', 'in_arrears', 'in_extension')
                  ) as open_contracts
                from public.contract
                where company_id = :company_id
            )
            select
              pagos.interest_collected, pagos.capital_recovered,
              pagos.interest_discounts, pagos.payment_count,
              nuevos.capital_disbursed, nuevos.contracts_opened,
              cartera.capital_outstanding, cartera.open_contracts
            from pagos, nuevos, cartera
            """
        ),
        {
            "company_id": str(company_id),
            "tz": tz_name,
            "from_date": from_date,
            "to_date": to_date,
        },
    )
    return result.one()
