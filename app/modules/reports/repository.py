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


async def payables_by_supplier(
    db: AsyncSession, *, company_id: UUID, as_of: date
) -> list[Row[Any]]:
    """Compras pendientes de pago, agrupadas por proveedor y por antigüedad.

    Solo `origin_type = 'purchase'`: los demás orígenes no le entregan plata a
    nadie, así que "sin pagar" no significa nada en ellos y contarlos inflaría
    la deuda con proveedores.

    La antigüedad se mide contra `entry_date` —cuándo entró la mercancía— y no
    contra `created_at`: cargar hoy una factura de hace dos meses no la vuelve
    reciente, y es la fecha desde la que el proveedor cuenta el plazo.

    El proveedor se saca por LEFT JOIN: `supplier_id` es opcional en el
    esquema, y una deuda sin proveedor asignado tiene que seguir apareciendo
    (esconderla sería el peor resultado posible en un reporte de deudas).
    """
    result = await db.execute(
        text(
            """
            select
              e.supplier_id,
              coalesce(s.name, 'Sin proveedor asignado') as supplier_name,
              count(*)                                   as entry_count,
              sum(e.total_cost)                          as total,
              sum(e.total_cost) filter (
                where :as_of - e.entry_date <= 30)       as days_0_30,
              sum(e.total_cost) filter (
                where :as_of - e.entry_date between 31 and 60) as days_31_60,
              sum(e.total_cost) filter (
                where :as_of - e.entry_date > 60)        as days_over_60,
              min(e.entry_date)                          as oldest_entry_date
            from public.inventory_entry e
            left join public.supplier s
              on s.id = e.supplier_id and s.company_id = e.company_id
            where e.company_id = :cid
              and e.origin_type = 'purchase'
              and e.paid_at is null
            group by e.supplier_id, s.name
            order by sum(e.total_cost) desc
            """
        ),
        {"cid": str(company_id), "as_of": as_of},
    )
    return list(result.all())


async def inventory_valuation(db: AsyncSession, *, company_id: UUID) -> list[Row[Any]]:
    """Valor del inventario disponible, por categoría de primer nivel.

    Cuenta SOLO `status = 'available'`: un borrador no se puede vender y un
    dado de baja ya no existe. Incluir borradores inflaría el activo con
    mercancía que ni siquiera tiene precio.

    El costo sale del LOTE (identificación específica, nunca promediado); el
    precio sale del PRODUCTO, que es donde vive desde 00022.
    """
    result = await db.execute(
        text(
            """
            select
              p.cat1_id,
              coalesce(c.name, 'Sin categoría')          as cat1_name,
              sum(i.quantity)                            as units,
              count(*)                                   as lot_count,
              sum(i.cost * i.quantity)                   as cost_value,
              sum(coalesce(p.sale_price, 0) * i.quantity) as retail_value
            from public.inventory_item i
            join public.product p
              on p.id = i.product_id and p.company_id = i.company_id
            left join public.category c
              on c.id = p.cat1_id and c.company_id = p.company_id
            where i.company_id = :cid and i.status = 'available'
            group by p.cat1_id, c.name
            order by sum(i.cost * i.quantity) desc
            """
        ),
        {"cid": str(company_id)},
    )
    return list(result.all())


async def stale_inventory(
    db: AsyncSession, *, company_id: UUID, as_of: date, threshold_days: int, limit: int
) -> list[Row[Any]]:
    """Productos disponibles cuyo lote más antiguo lleva más de N días.

    Se mide sobre el lote MÁS ANTIGUO todavía disponible y no sobre el más
    reciente: si algo entró hace un año y se repuso ayer, lo que está
    congelado es la pieza vieja, y usar la fecha nueva la escondería justo
    cuando más importa verla.
    """
    result = await db.execute(
        text(
            """
            select
              p.id                       as product_id,
              p.code                     as product_code,
              p.name                     as product_name,
              sum(i.quantity)            as units,
              sum(i.cost * i.quantity)   as cost_value,
              (:as_of - min(i.entry_date)) as days_in_stock
            from public.inventory_item i
            join public.product p
              on p.id = i.product_id and p.company_id = i.company_id
            where i.company_id = :cid and i.status = 'available'
            group by p.id, p.code, p.name
            having (:as_of - min(i.entry_date)) >= :threshold
            order by (:as_of - min(i.entry_date)) desc
            limit :limit
            """
        ),
        {
            "cid": str(company_id),
            "as_of": as_of,
            "threshold": threshold_days,
            "limit": limit,
        },
    )
    return list(result.all())
