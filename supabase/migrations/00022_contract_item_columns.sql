-- =====================================================================
-- 00022_contract_item_columns.sql — FASE 3, paso 1 de 2: RELAJAR.
--
-- Prepara la contracción sin romper nada. Deja de exigir `NOT NULL` en las
-- columnas de `inventory_item` que desde 00021 viven en `product`, y repara
-- cualquier artículo que haya quedado sin producto.
--
-- POR QUÉ EN DOS PASOS. Al intentar contraer de una sola vez, los DOS
-- órdenes de despliegue rompían algo:
--
--   migración primero  -> el código desplegado hace SELECT de `name` sobre
--                         `inventory_item` y la columna ya no existe
--   código primero     -> el INSERT nuevo no escribe `name`, que es NOT NULL,
--                         y viola la restricción
--
-- Con este paso intermedio los dos mundos conviven: el código viejo sigue
-- leyendo y escribiendo esas columnas, y el nuevo puede omitirlas. Recién
-- entonces 00023 las borra.
--
-- Es la misma lección de 00014/00015/00016 —donde el CHECK llegó antes que
-- el deploy y rompió dev— aplicada de entrada en vez de como recuperación.
--
-- SECUENCIA COMPLETA:
--   1. aplicar 00022  (esta)         nada se rompe, ambos códigos funcionan
--   2. desplegar el código nuevo     deja de leer y escribir esas columnas
--   3. aplicar 00023                 las borra
--
-- Todos los pasos son idempotentes y verifican antes de actuar: se pueden
-- reejecutar sin daño.
-- =====================================================================

-- Repara artículos sin producto. Puede haberlos si se crearon en la ventana
-- entre desplegar 00021 y el código que enlaza el producto — una ventana que
-- no debería existir si van juntos, pero que una migración robusta no asume
-- cerrada.
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_name = 'inventory_item' and column_name = 'name'
  ) then
    insert into public.product
      (company_id, name, cat1_id, cat2_id, cat3_id, description, sale_price, is_unique)
    select i.company_id, i.name, i.cat1_id, i.cat2_id, i.cat3_id, min(i.description),
           max(i.sale_price), false
    from public.inventory_item i
    where i.product_id is null and i.origin <> 'auction'
    group by i.company_id, i.name, i.cat1_id, i.cat2_id, i.cat3_id;

    update public.inventory_item i
    set product_id = p.id
    from public.product p
    where i.product_id is null and i.origin <> 'auction'
      and p.company_id = i.company_id and not p.is_unique
      and p.name = i.name and p.cat1_id = i.cat1_id
      and p.cat2_id = i.cat2_id and p.cat3_id = i.cat3_id;

    -- Piezas de remate: producto propio, nunca agrupan.
    declare r record; new_id uuid;
    begin
      for r in select * from public.inventory_item where product_id is null loop
        insert into public.product
          (company_id, name, cat1_id, cat2_id, cat3_id, description, sale_price, is_unique)
        values (r.company_id, r.name, r.cat1_id, r.cat2_id, r.cat3_id, r.description,
                r.sale_price, true)
        returning id into new_id;
        update public.inventory_item set product_id = new_id where id = r.id;
      end loop;
    end;
  end if;
end $$;

with numerados as (
  select id, row_number() over (partition by product_id order by entry_date, created_at, id) as n
  from public.inventory_item
  where lot_number is null and product_id is not null
)
update public.inventory_item i
set lot_number = numerados.n
from numerados where numerados.id = i.id;

-- Relajar el NOT NULL de lo que 00023 va a borrar. Guardado con `if exists`
-- para poder reejecutarse aunque las columnas ya no estén.
do $$
declare col text;
begin
  foreach col in array array['name', 'cat1_id', 'cat2_id', 'cat3_id'] loop
    if exists (
      select 1 from information_schema.columns
      where table_name = 'inventory_item' and column_name = col
    ) then
      execute format('alter table public.inventory_item alter column %I drop not null', col);
    end if;
  end loop;
end $$;
