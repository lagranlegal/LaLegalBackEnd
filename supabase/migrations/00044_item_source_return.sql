-- =====================================================================
-- 00044_item_source_return.sql — el cuarto puntero de origen: `D` de
-- devuelto por cliente.
--
-- Copia literal del patrón de 00039 (`source_transformation_id`), sin
-- backfill porque no hay devoluciones históricas que reconstruir — la
-- tabla que este puntero referencia (`sale_return`) nace en esta misma
-- serie de migraciones.
--
-- Solo se usa en el camino B de una devolución: cuando el lote original ya
-- no es reabrible (fue consumido en una transformación, dado de baja, etc.
-- después de la venta) y hay que crear un lote nuevo para lo que reingresa.
-- El camino A (lote intacto) NO usa este puntero — reabre el mismo
-- `inventory_item` de siempre, sin crear uno nuevo.
--
-- Cuarto puntero de origen, excluyente con los otros tres (`supplier_id`,
-- `source_contract_id`, `source_transformation_id`) por la misma convención
-- de código que ya rige a esos tres — sin CHECK de exclusividad en BD
-- porque tampoco existe entre ellos hoy.
--
-- ADITIVA.
-- =====================================================================

alter table public.inventory_item
  add column if not exists source_return_id uuid
    references public.sale_return(id);

comment on column public.inventory_item.source_return_id is
  'Solo en artículos creados por el REINGRESO de una devolución (camino B: '
  'el lote original ya no era reabrible). Excluyente con supplier_id, '
  'source_contract_id y source_transformation_id. Es lo que hace que la '
  'letra del código sea D y no P.';

create index if not exists ix_item_source_return
  on public.inventory_item (company_id, source_return_id)
  where source_return_id is not null;
