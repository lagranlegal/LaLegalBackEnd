-- =====================================================================
-- 00063_reportes_fase7.sql — Los datos que le faltaban al estado de
-- resultados para cerrar el círculo (auditoría fase 7, 28/09/2026).
--
--   F7-04  El remate capitaliza el interés pendiente en el costo del
--          artículo (`cost = saldo capital + intereses pendientes`), y ese
--          interés no quedaba guardado en ninguna parte por separado: al
--          vender, el costo de ventas cargaba 1.000.000 por una prenda que
--          costó 800.000 de capital, y los 200.000 de interés nunca llegaban
--          al resultado. Medido: `inventory_item` guarda solo `cost`; el
--          contrato conserva `capital_balance` y el ingreso del remate
--          `total_cost`, así que la parte de interés se puede DERIVAR para
--          los remates existentes, pero no por pieza en un reporte.
--   F7-08  Vender por debajo del precio publicado ya exige permiso y motivo
--          (ed9ab91), pero el precio publicado se guardaba solo en
--          `audit_log`: ningún reporte podía sumar ese descuento.
--
-- Todo es ADITIVO y compatible con el código desplegado: columnas con
-- default (o nullable) que el código viejo no lee ni escribe.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Interés capitalizado en el costo de un lote rematado (F7-04).
--
-- UNITARIO, como `cost`: de `cost`, cuánto es interés que el contrato
-- adeudaba al rematar. El resto (`cost − capitalized_interest`) es el
-- capital que el negocio prestó y es la BASE DE COSTO del lote en el
-- resultado — lo que sale del costo de ventas, de una merma o de una
-- devolución. El valor del inventario sigue siendo `cost` completo.
-- ---------------------------------------------------------------------
alter table public.inventory_item
  add column capitalized_interest numeric(14,2) not null default 0;

alter table public.inventory_item
  add constraint inventory_item_capitalized_interest_range
  check (capitalized_interest >= 0 and capitalized_interest <= cost);

-- Backfill de los remates existentes, derivado del contrato: el interés del
-- remate es `total_cost` de su ingreso menos el `capital_balance` que el
-- contrato conserva (un contrato `auctioned` es terminal: su saldo ya no se
-- mueve). Se reparte entre las piezas en proporción a su costo —que ya se
-- repartió por avalúo—, y la última absorbe el residuo del redondeo para que
-- la suma cuadre al centavo, igual que `split_cost_by_appraisal`.
with remates as (
  select e.contract_id, e.company_id, e.total_cost,
         greatest(e.total_cost - c.capital_balance, 0) as interes
  from public.inventory_entry e
  join public.contract c
    on c.id = e.contract_id and c.company_id = e.company_id
  where e.origin_type = 'auction' and c.status = 'auctioned' and e.total_cost > 0
),
piezas as (
  select i.id, i.cost, r.interes,
         round(r.interes * i.cost / r.total_cost, 2) as parte,
         row_number() over (partition by i.source_contract_id order by i.id desc) as desde_el_final,
         sum(round(r.interes * i.cost / r.total_cost, 2))
           over (partition by i.source_contract_id) as suma_partes
  from public.inventory_item i
  join remates r on r.contract_id = i.source_contract_id and r.company_id = i.company_id
  where i.origin = 'auction'
)
update public.inventory_item i
set capitalized_interest = least(
      greatest(
        case when p.desde_el_final = 1 then p.parte + (p.interes - p.suma_partes) else p.parte end,
        0
      ),
      i.cost
    )
from piezas p
where p.id = i.id and p.interes > 0;

-- ---------------------------------------------------------------------
-- 2. La línea de venta congela la parte de interés de su costo (F7-04).
--
-- Mismo criterio que `unit_cost` (00019): el costo de una venta es un hecho
-- histórico y se congela al vender. Una devolución la lee de su línea.
-- ---------------------------------------------------------------------
alter table public.sale_line
  add column unit_cost_interest numeric(14,2) not null default 0;

alter table public.sale_line
  add constraint sale_line_unit_cost_interest_range
  check (unit_cost_interest >= 0 and unit_cost_interest <= unit_cost);

update public.sale_line sl
set unit_cost_interest = least(i.capitalized_interest, sl.unit_cost)
from public.inventory_item i
where i.id = sl.item_id and i.company_id = sl.company_id
  and i.capitalized_interest > 0;

-- ---------------------------------------------------------------------
-- 3. El precio publicado, congelado en la línea (F7-08).
--
-- NULL = la venta es anterior a esta migración y no vendió por debajo del
-- precio, o el producto no tenía precio publicado. El descuento por precio
-- de una línea es `max(list_price − unit_price, 0) × quantity`.
-- ---------------------------------------------------------------------
alter table public.sale_line
  add column list_price numeric(14,2) check (list_price >= 0);

-- Backfill de las ventas bajo el precio publicado desde ed9ab91: su precio
-- quedó en `audit_log.after.below_price_lines`, por artículo. Es el único
-- registro histórico del precio publicado; las demás líneas quedan NULL
-- (no hay de dónde sacarlo, y inventarlo con el precio de HOY del producto
-- afirmaría un descuento que nadie otorgó).
update public.sale_line sl
set list_price = (bl.value ->> 'sale_price')::numeric(14,2)
from public.audit_log a
cross join lateral jsonb_array_elements(a.after -> 'below_price_lines') bl(value)
where a.action = 'apply_sale_discount'
  and a.entity_type = 'sale'
  and a.after ? 'below_price_lines'
  and sl.sale_id = a.entity_id
  and sl.company_id = a.company_id
  and sl.item_id = (bl.value ->> 'item_id')::uuid;
