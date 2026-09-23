from datetime import date
from decimal import Decimal
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


async def closings_breakdown(
    db: AsyncSession, *, company_id: UUID, from_date: date | None, to_date: date | None
) -> list[Row[Any]]:
    """Módulo × concepto × medio × cuenta × DÍA, sumado sobre todas las
    sesiones cerradas del rango — una sola consulta en vez de pedir el acta
    sesión por sesión (`GET /cashbox/sessions/{id}/report` × N, lo que hacía
    el front hasta ahora para armar Reportes).

    Se agrupa por `session_date`, no por `session_id`: la regla de negocio
    ("una sesión por caja por día") garantiza que nunca hay dos sesiones
    cerradas el mismo día, así que agrupar por fecha es exactamente lo mismo
    que agrupar por sesión, con una columna menos.

    A diferencia de `cashbox.repository.movement_breakdown` (usada para
    calcular `expected_cash` de UNA sesión), acá NO se filtra por
    `account_type='cash'` — esa cuenta es "cuánto debería haber en el cajón
    HOY", sin sentido sumado sobre varios días. El front decide qué hacer
    con cada línea, igual que ya hace con las de una sola sesión.
    """
    query = (
        "select m.module, m.direction, m.concept, m.payment_method, "
        "       a.id as account_id, a.name as account_name, a.type as account_type, "
        "       cs.session_date, sum(m.amount) as total "
        "from public.cash_movement m "
        "join public.account a on a.id = m.account_id "
        "join public.cash_session cs on cs.id = m.session_id "
        "where m.company_id = :company_id and cs.status = 'closed'"
    )
    params: dict[str, Any] = {"company_id": str(company_id)}
    if from_date is not None:
        query += " and cs.session_date >= :from_date"
        params["from_date"] = from_date
    if to_date is not None:
        query += " and cs.session_date <= :to_date"
        params["to_date"] = to_date
    query += (
        " group by m.module, m.direction, m.concept, m.payment_method, a.id, a.name, a.type,"
        " cs.session_date"
        " order by cs.session_date, a.type, a.name, m.module, m.direction, m.concept"
    )
    result = await db.execute(text(query), params)
    return list(result.all())


async def profit_summary(
    db: AsyncSession, *, company_id: UUID, tz_name: str, from_date: date, to_date: date
) -> Row[Any]:
    """Utilidad BRUTA del período: ingreso por ventas menos su costo de ventas,
    **neto de las devoluciones del período**.

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

    --- DEVOLUCIONES (F21-12) ------------------------------------------------

    Una devolución es **contra-ingreso** (*devoluciones en ventas*), NO una
    borradura de la venta original, y cae en el período de la DEVOLUCIÓN.

    Tres motivos, y los tres ya estaban en el proyecto:

      1. Es la doctrina que este módulo ya aplica: *"el estado de resultados
         sale de los DOCUMENTOS, no de los movimientos de caja"*. Una
         devolución **es un documento** (`sale_return`, 00042), igual que
         `sale`, `contract_payment` y `expense`. Leerla acá es aplicar la
         regla que ya existe, no inventar una.
      2. Cambiar `sale.status` sería PEOR: una devolución parcial sacaría la
         venta ENTERA del resultado, y reescribiría hacia atrás un mes ya
         cerrado (que es justo el defecto F21-15).
      3. `sale_return.return_date` existe, así que el contra-ingreso cae en su
         propio período y un mes cerrado no cambia retroactivamente.

    `return_date` es un `date` puro, no un `timestamptz`: se compara directo
    contra el rango, sin `at time zone`. La fecha de una devolución ya es la
    fecha del negocio (la fija el servicio con `get_company_today`), así que
    convertirla otra vez la correría un día.

    El costo devuelto sale de `sale_return_line.unit_cost` —heredado de la
    línea de venta, identificación específica— y **NO se recalcula**: es el
    mismo hecho histórico congelado al vender.

    **Y con eso el doble conteo se cierra solo.** Que el artículo devuelto
    vuelva a `available` (`sales/service.py`) y sume otra vez en la
    valorización del inventario es CORRECTO: volvió a ser inventario de
    verdad. El doble conteo era el síntoma de no restar su costo del costo de
    ventas, no un defecto aparte — quien "arregle" también la valorización
    estaría restando dos veces.

    Solo se cuentan devoluciones de ventas `completed`, igual que el ingreso:
    si la venta se anula después, su ingreso desaparece entero de su propio
    período y restar además la devolución lo descontaría dos veces.
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
            ),
            -- Bruto de CADA venta que tiene devoluciones en el rango: es el
            -- denominador del prorrateo del descuento. Se calcula aparte (y
            -- no con un join a las líneas) por el mismo motivo de siempre:
            -- un join plano repetiría el descuento una vez por línea.
            devueltas as (
                select distinct r.sale_id
                from public.sale_return r
                where r.company_id = :company_id
                  and r.return_date between :from_date and :to_date
            ),
            bruto_por_venta as (
                select sl.sale_id, coalesce(sum(sl.subtotal), 0) as bruto_venta
                from public.sale_line sl
                join devueltas d on d.sale_id = sl.sale_id
                where sl.company_id = :company_id
                group by sl.sale_id
            ),
            -- PRORRATEO DEL DESCUENTO: el descuento vive en la CABECERA de la
            -- venta, así que una devolución parcial solo puede llevarse la
            -- parte proporcional. Se prorratea por PARTICIPACIÓN EN EL BRUTO
            -- de la venta —`quantity * unit_price` sobre el bruto total— y no
            -- por unidades: un descuento de 10.000 sobre una venta de una
            -- cadena de 900.000 y un anillo de 100.000 no se reparte 50/50.
            -- Sin el prorrateo se restaría el ingreso BRUTO de lo devuelto y
            -- saldría más plata del resultado de la que entró.
            --
            -- Se redondea POR LÍNEA a 2 decimales, igual que `subtotal` al
            -- vender. Devolver una venta completa en varias devoluciones
            -- puede dejar un residuo de centavos contra `discount_amount`;
            -- repartirlo exigiría saber cuál devolución es "la última", que
            -- es un dato que no existe al consultar.
            devoluciones as (
                select
                  count(distinct r.id)                                      as return_count,
                  coalesce(sum(round(srl.quantity * sl.unit_price, 2)), 0)  as bruto,
                  coalesce(sum(round(srl.quantity * srl.unit_cost, 2)), 0)  as costo,
                  coalesce(
                    sum(
                      round(
                        s.discount_amount * (srl.quantity * sl.unit_price)
                        / nullif(bv.bruto_venta, 0),
                        2
                      )
                    ),
                    0
                  )                                                         as descuento
                from public.sale_return r
                join public.sale_return_line srl
                  on srl.return_id = r.id and srl.company_id = r.company_id
                join public.sale_line sl
                  on sl.id = srl.sale_line_id and sl.company_id = srl.company_id
                join public.sale s
                  on s.id = r.sale_id and s.company_id = r.company_id
                join bruto_por_venta bv on bv.sale_id = r.sale_id
                where r.company_id = :company_id
                  and s.status = 'completed'
                  and r.return_date between :from_date and :to_date
            )
            select
              (select count(*) from ventas)                                as sale_count,
              (select coalesce(sum(discount_amount), 0) from ventas)       as discounts,
              lineas.bruto                                                 as gross_revenue,
              lineas.costo                                                 as cost_of_goods_sold,
              lineas.unidades                                              as units_sold,
              devoluciones.return_count                                    as return_count,
              devoluciones.bruto                                           as returns_gross,
              devoluciones.descuento                                       as returns_discounts,
              devoluciones.costo                                           as returns_cost
            from lineas, devoluciones
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
    """Productos disponibles cuyo lote más antiguo lleva N días o más.

    Se mide sobre el lote MÁS ANTIGUO todavía disponible y no sobre el más
    reciente: si algo entró hace un año y se repuso ayer, lo que está
    congelado es la pieza vieja, y usar la fecha nueva la escondería justo
    cuando más importa verla.

    El umbral es `>=` a propósito: el producto que ACABA de cruzar los N días
    es justamente el que se quiere ver el primer día, no el segundo.

    Cada fila trae además `total_product_count` y `total_cost_value`, que son
    del UNIVERSO COMPLETO y no de la página (F21-25). Van como ventana sobre
    el mismo CTE —y no como una segunda consulta— porque así la definición de
    "dormido" se escribe UNA vez: dos consultas separadas pueden quedar con
    umbrales distintos sin que nada avise, y el total es exactamente el número
    con el que el dueño decide si remata mercancía. En Postgres la ventana se
    evalúa DESPUÉS del `having` y ANTES del `limit`, así que cuenta todos los
    productos sobre el umbral aunque la lista devuelva solo los primeros.
    """
    result = await db.execute(
        text(
            """
            with dormidos as (
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
            )
            select
              d.product_id,
              d.product_code,
              d.product_name,
              d.units,
              d.cost_value,
              d.days_in_stock,
              count(*)             over () as total_product_count,
              sum(d.cost_value)    over () as total_cost_value
            from dormidos d
            order by d.days_in_stock desc
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


async def operating_expenses(
    db: AsyncSession, *, company_id: UUID, tz_name: str, from_date: date, to_date: date
) -> Row[Any]:
    """Gastos operativos del período, desde el DOCUMENTO (`expense`).

    No desde los movimientos de caja, que es de donde los saca `/reportes`
    hoy: el desglose de caja solo cubre sesiones CERRADAS, así que los gastos
    de hoy no aparecerían. Mismo criterio que ya usan `profit_summary` y
    `pawn_performance`.

    Las fechas se comparan en la zona horaria de la EMPRESA, no en UTC: el
    "hoy" del negocio termina a medianoche de Bogotá.
    """
    result = await db.execute(
        text(
            """
            select
              coalesce(sum(amount), 0) as total,
              count(*)                 as expense_count
            from public.expense
            where company_id = :company_id
              and (created_at at time zone :tz)::date between :from_date and :to_date
            """
        ),
        {
            "company_id": str(company_id),
            "tz": tz_name,
            "from_date": from_date,
            "to_date": to_date,
        },
    )
    row = result.first()
    assert row is not None  # los agregados siempre devuelven una fila
    return row


async def inventory_purchased(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> Decimal:
    """Mercancía comprada en el período, por `entry_date`.

    Por la fecha en que ENTRÓ la mercancía y no por la de digitación ni la de
    pago: es lo que corresponde al período desde el punto de vista del
    inventario. Una factura de la semana pasada cargada hoy pertenece a la
    semana pasada.

    Solo `purchase`: los demás orígenes no le entregan plata a nadie
    (inventario inicial, sobrante de conteo, transformación) y contarlos daría
    a entender que el negocio invirtió en mercancía que ya tenía.
    """
    result = await db.execute(
        text(
            """
            select coalesce(sum(total_cost), 0)
            from public.inventory_entry
            where company_id = :company_id
              and origin_type = 'purchase'
              and entry_date between :from_date and :to_date
            """
        ),
        {"company_id": str(company_id), "from_date": from_date, "to_date": to_date},
    )
    return Decimal(str(result.scalar_one() or 0))


async def monthly_series(
    db: AsyncSession, *, company_id: UUID, tz_name: str, months: int
) -> list[Row[Any]]:
    """Serie mensual de ingresos operativos y gastos, últimos `months` meses.

    Misma semántica de ingreso que el resto de los reportes, no una tercera
    definición: el interés sale de `contract_payment` (el documento) y la
    venta de `sale_line.subtotal` menos el descuento de la venta, solo
    `completed`. El capital abonado NO entra — recuperar capital reduce la
    cartera, no es ingreso — ni las compras de mercancía, que son un activo.

    `sales_returns` viene como columna APARTE y no restado de `sales_revenue`:
    así `sales_revenue` significa lo mismo acá que en
    `/reports/income-statement`, y quien pinte la serie decide si muestra la
    devolución o solo la venta neta. Restarlo en silencio acá y no allá habría
    creado dos «Ventas» distintas con el mismo nombre.

    `generate_series` arma los meses ANTES de agregar: un mes sin ventas ni
    abonos tiene que aparecer en cero, no faltar. Si faltara, la gráfica
    uniría dos meses no consecutivos con una línea recta y mostraría una
    tendencia que nunca existió.

    Todo se agrupa por el mes en la zona de la EMPRESA (`at time zone :tz`),
    igual que los demás reportes — un abono de las 7pm en Bogotá pertenece a
    ese mes, aunque en UTC ya sea el siguiente.
    """
    result = await db.execute(
        text(
            """
            with meses as (
                select generate_series(
                    date_trunc('month', (now() at time zone :tz)::date)
                        - make_interval(months => :months - 1),
                    date_trunc('month', (now() at time zone :tz)::date),
                    interval '1 month'
                )::date as month
            ),
            -- Interés NETO del descuento, igual que la venta se cuenta neta de
            -- su descuento unas líneas más abajo: un descuento es plata que se
            -- decidió no cobrar, no un dato informativo. Sin el `- discount`
            -- esta serie sobreestimaba el ingreso del mes por todos los
            -- descuentos de interés otorgados, y no cuadraba con
            -- `/reports/income-statement` (09/09/2026).
            intereses as (
                select
                  date_trunc('month', (paid_at at time zone :tz)::date)::date        as month,
                  coalesce(sum(interest_amount), 0) - coalesce(sum(discount_amount), 0) as total
                from public.contract_payment
                where company_id = :company_id
                group by 1
            ),
            ventas as (
                select
                  s.id,
                  date_trunc('month', (s.sold_at at time zone :tz)::date)::date as month,
                  s.discount_amount
                from public.sale s
                where s.company_id = :company_id and s.status = 'completed'
            ),
            -- Bruto y descuento se agregan POR SEPARADO y se restan al final:
            -- el descuento vive en `sale`, no en la línea, así que un join
            -- plano con las líneas lo repetiría una vez por línea de la venta
            -- (mismo motivo por el que `profit_summary` los separa).
            ventas_bruto as (
                select v.month, coalesce(sum(sl.subtotal), 0) as bruto
                from ventas v
                join public.sale_line sl
                  on sl.sale_id = v.id and sl.company_id = :company_id
                group by v.month
            ),
            ventas_descuento as (
                select month, coalesce(sum(discount_amount), 0) as descuento
                from ventas
                group by month
            ),
            -- DEVOLUCIONES (F21-12): contra-ingreso del mes de la DEVOLUCIÓN,
            -- exactamente la misma definición que usa `profit_summary` — no
            -- una tercera. Se agrupa por `return_date`, que es un `date` puro
            -- (sin `at time zone`: ya es la fecha del negocio), así que una
            -- devolución de enero baja enero y nunca reescribe el mes de la
            -- venta original.
            bruto_por_venta as (
                select sl.sale_id, coalesce(sum(sl.subtotal), 0) as bruto_venta
                from public.sale_line sl
                where sl.company_id = :company_id
                  and sl.sale_id in (
                      select sale_id from public.sale_return
                      where company_id = :company_id
                  )
                group by sl.sale_id
            ),
            devoluciones as (
                select
                  date_trunc('month', r.return_date)::date as month,
                  coalesce(sum(round(srl.quantity * sl.unit_price, 2)), 0)
                  - coalesce(
                      sum(
                        round(
                          s.discount_amount * (srl.quantity * sl.unit_price)
                          / nullif(bv.bruto_venta, 0),
                          2
                        )
                      ),
                      0
                    )                                      as total
                from public.sale_return r
                join public.sale_return_line srl
                  on srl.return_id = r.id and srl.company_id = r.company_id
                join public.sale_line sl
                  on sl.id = srl.sale_line_id and sl.company_id = srl.company_id
                join public.sale s
                  on s.id = r.sale_id and s.company_id = r.company_id
                join bruto_por_venta bv on bv.sale_id = r.sale_id
                where r.company_id = :company_id and s.status = 'completed'
                group by 1
            ),
            gastos as (
                select
                  date_trunc('month', (created_at at time zone :tz)::date)::date as month,
                  coalesce(sum(amount), 0)                                       as total
                from public.expense
                where company_id = :company_id
                group by 1
            )
            select
              m.month,
              coalesce(i.total, 0)                                as interest_revenue,
              coalesce(vb.bruto, 0) - coalesce(vd.descuento, 0)   as sales_revenue,
              coalesce(dv.total, 0)                               as sales_returns,
              coalesce(g.total, 0)                                as expenses
            from meses m
            left join intereses i          on i.month  = m.month
            left join ventas_bruto vb      on vb.month = m.month
            left join ventas_descuento vd  on vd.month = m.month
            left join devoluciones dv      on dv.month = m.month
            left join gastos g             on g.month  = m.month
            order by m.month
            """
        ),
        {"company_id": str(company_id), "tz": tz_name, "months": months},
    )
    return list(result.all())
