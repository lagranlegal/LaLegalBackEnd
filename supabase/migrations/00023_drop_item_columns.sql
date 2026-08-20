-- =====================================================================
-- 00023_drop_item_columns.sql — FASE 3, paso 2 de 2: BORRAR.
--
-- Elimina de `inventory_item` las columnas que desde 00021 viven en
-- `product`. Se aplica DESPUÉS de desplegar el código que dejó de leerlas
-- (ver la secuencia en 00022).
--
-- Mientras estuvieron duplicadas, alguien tenía que mantenerlas
-- sincronizadas — y eso ya falló una vez, en producción de dev:
-- `update_product` escribía el precio en el producto pero no en los lotes,
-- así que la pantalla mostraba $250.000 y la caja seguía cobrando $200.000.
-- Se parcheó con `sync_lot_prices`, pero el arreglo real es este: que el dato
-- exista UNA sola vez y nadie tenga que acordarse de nada.
--
-- QUÉ SE VA:
--   name, cat1_id, cat2_id, cat3_id, description
--     -> definen QUÉ es el artículo, y eso es el producto. Dos lotes de la
--        misma cadena no pueden llamarse distinto: si lo hicieran, no serían
--        el mismo producto.
--   sale_price
--     -> decisión comercial sobre el producto, no atributo de una compra.
--
-- QUÉ SE QUEDA EN EL LOTE: costo, proveedor, fecha de entrada, cantidad,
-- estado, fotos, código y contrato de origen. Todo lo propio de ESA compra o
-- ESA pieza. `photos` se queda a propósito: un lote puede fotografiarse
-- aparte, y una pieza de remate ciertamente tiene las suyas.
-- =====================================================================

-- Última verificación antes de borrar algo irreversible: si quedara un
-- artículo sin producto, perderíamos su nombre para siempre.
do $$
declare huerfanos int;
begin
  select count(*) into huerfanos
  from public.inventory_item where product_id is null or lot_number is null;
  if huerfanos > 0 then
    raise exception
      'Quedan % artículos sin producto o sin lote. Ejecutar 00022 antes de contraer.',
      huerfanos;
  end if;
end $$;

alter table public.inventory_item alter column product_id set not null;
alter table public.inventory_item alter column lot_number set not null;

alter table public.inventory_item
  drop column if exists name,
  drop column if exists cat1_id,
  drop column if exists cat2_id,
  drop column if exists cat3_id,
  drop column if exists description,
  drop column if exists sale_price;

create index if not exists ix_item_product on public.inventory_item (company_id, product_id);
