-- =====================================================================
-- 00019_sale_line_unit_cost.sql — Costo de ventas (COGS).
--
-- `inventory_item.cost` guarda el costo real de cada pieza (identificación
-- específica, estándar joyero/NIIF) y `sale_line.unit_price` el precio al que
-- se vendió. NADA los cruzaba: un grep de `cost` en todo el módulo `sales`
-- daba cero resultados. O sea que la pregunta central del negocio —"¿cuánto
-- gané realmente con lo que vendí este mes?"— no tenía respuesta en la app.
--
-- El costo se COPIA a la línea de venta, no se lee del artículo al reportar.
-- Es el mismo criterio de snapshot legal que ya usan los contratos (que
-- congelan tasa, plazo y ventana de mora al crearse): el costo de una venta
-- es un hecho histórico del momento en que ocurrió. Leerlo del artículo al
-- generar el reporte haría que un reporte del mes pasado cambiara si alguien
-- corrige el costo de un artículo hoy — y los reportes de un período cerrado
-- no deben moverse.
--
-- BACKFILL: las ventas anteriores sí pueden recuperar su costo, porque
-- `inventory_item.cost` es inmutable en la práctica (se fija al ingresar o al
-- rematar y ningún endpoint lo edita — `ItemUpdateIn` acepta nombre,
-- descripción, precio, fotos y categoría, nunca el costo). Así que copiarlo
-- ahora reconstruye el histórico con el valor correcto, a diferencia del
-- `payment_method` de 00014, que sí era irrecuperable.
--
-- NOT NULL con default 0 después del backfill: una línea de venta sin costo
-- rompería la utilidad en silencio (aparecería como margen del 100%), que es
-- peor que un cero visible.
-- =====================================================================

alter table public.sale_line add column unit_cost numeric(14,2);

update public.sale_line sl
set unit_cost = i.cost
from public.inventory_item i
where i.id = sl.item_id
  and i.company_id = sl.company_id;

-- Cualquier línea que no haya matcheado (no debería existir: item_id es FK
-- NOT NULL) queda en 0 explícito en vez de NULL.
update public.sale_line set unit_cost = 0 where unit_cost is null;

alter table public.sale_line
  alter column unit_cost set not null,
  alter column unit_cost set default 0;

alter table public.sale_line
  add constraint sale_line_unit_cost_non_negative check (unit_cost >= 0);

-- El reporte de utilidad filtra por rango de fechas sobre ventas completadas.
create index ix_sale_sold_at on public.sale (company_id, sold_at) where status = 'completed';
