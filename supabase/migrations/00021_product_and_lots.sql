-- =====================================================================
-- 00021_product_and_lots.sql — Introduce el concepto de PRODUCTO.
--
-- FASE 1 de 3 (expandir / migrar / contraer). Esta migración es puramente
-- ADITIVA: agrega la estructura nueva y la llena, sin quitarle nada a
-- `inventory_item`. El código viejo sigue funcionando igual mientras el
-- nuevo empieza a usar `product`. Es la misma disciplina que faltó en
-- 00014 (donde el CHECK llegó antes que el deploy y rompió dev) — acá el
-- orden está pensado desde el principio.
--
--   Fase 1 (esta)  expandir  -> product + product_id + lot_number, backfill
--   Fase 2         migrar    -> el precio pasa a vivir en product; las
--                               pantallas leen de ahí
--   Fase 3         contraer  -> se quitan de inventory_item las columnas
--                               que ya viven en product
--
-- EL PROBLEMA QUE RESUELVE: el sistema no tenía el concepto de producto,
-- solo artículos sueltos. Dos compras de la misma cadena quedaban como
-- `JAO0007I` y `JAO0012M` sin nada que las vinculara. De ahí salían cuatro
-- síntomas que parecían independientes: la lista no agrupa, el precio se
-- edita lote por lote, reponer depende de escribir el nombre idéntico, y no
-- se pueden comparar proveedores del mismo producto.
--
-- QUÉ VIVE DÓNDE:
--   producto -> nombre, categoría, descripción, PRECIO de venta
--   lote     -> costo, proveedor, fecha de entrada, cantidad, estado, fotos
--
-- El costo NUNCA sube al producto: identificación específica (NIIF), cada
-- lote conserva su costo real y jamás se promedia. Ese principio es el que
-- sostiene el costo de ventas de 00019.
--
-- PIEZAS ÚNICAS (remates): un anillo de un contrato no tiene "lote 2". En
-- vez de un modelo aparte, cada pieza rematada obtiene SU PROPIO producto
-- con un solo lote, marcado `is_unique`. Así la estructura es uniforme (todo
-- lote pertenece a un producto) y las piezas únicas nunca se agrupan entre
-- sí, que es justamente lo correcto.
-- =====================================================================

create table public.product (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references public.company(id),
  -- SKU: `[letra cat1][cat2][cat3][consecutivo 4 dígitos]`, sin la letra de
  -- proveedor — el proveedor es del LOTE, no del producto: el mismo producto
  -- puede comprarse a varios proveedores y sigue siendo el mismo.
  code        text,
  name        text not null,
  cat1_id     uuid not null references public.category(id),
  cat2_id     uuid not null references public.category(id),
  cat3_id     uuid not null references public.category(id),
  description text,
  -- El precio vive ACÁ y no en el lote: es una decisión comercial sobre el
  -- producto, no un atributo de una compra puntual. Cambiarlo una vez aplica
  -- a todos los lotes, que es el comportamiento correcto (el cliente no sabe
  -- qué lote le tocó). Las ventas ya hechas no se ven afectadas: `sale_line`
  -- congela su propio `unit_price`.
  sale_price  numeric(14,2) check (sale_price is null or sale_price >= 0),
  -- Piezas de remate: producto de un solo lote que no agrupa con nada.
  is_unique   boolean not null default false,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (company_id, code)
);
create trigger trg_product_updated before update on public.product
  for each row execute function public.set_updated_at();
create index ix_product_company_name on public.product (company_id, name);

alter table public.inventory_item add column product_id uuid references public.product(id);
-- Consecutivo del lote DENTRO del producto: 1, 2, 3… El código del lote se
-- arma como `{product.code}-{lot_number:02d}` → `JAO0007-01`.
alter table public.inventory_item add column lot_number int;

-- ---------------------------------------------------------------------
-- Backfill. Un producto por cada combinación (empresa, nombre, categoría)
-- ya existente: los artículos que hoy comparten nombre y categoría eran, de
-- hecho, el mismo producto comprado varias veces — solo que el sistema no
-- podía saberlo.
--
-- Los de remate quedan fuera de esa agrupación a propósito (`is_unique`):
-- dos anillos rematados con el mismo nombre siguen siendo piezas distintas.
-- ---------------------------------------------------------------------

insert into public.product (company_id, name, cat1_id, cat2_id, cat3_id, description, sale_price, is_unique)
select
  i.company_id,
  i.name,
  i.cat1_id,
  i.cat2_id,
  i.cat3_id,
  min(i.description),
  -- Precio del producto: el más alto entre sus lotes. Si dos lotes quedaron
  -- con precios distintos (posible hoy, porque el precio estaba por pieza),
  -- tomar el mayor evita bajar precios sin querer durante la migración. El
  -- usuario lo ajusta después desde una sola pantalla, que es justamente lo
  -- que este cambio habilita.
  max(i.sale_price),
  false
from public.inventory_item i
where i.origin <> 'auction'
group by i.company_id, i.name, i.cat1_id, i.cat2_id, i.cat3_id;

update public.inventory_item i
set product_id = p.id
from public.product p
where i.origin <> 'auction'
  and p.company_id = i.company_id
  and p.name = i.name
  and p.cat1_id = i.cat1_id
  and p.cat2_id = i.cat2_id
  and p.cat3_id = i.cat3_id;

-- Cada pieza rematada, su propio producto único.
do $$
declare r record; new_product_id uuid;
begin
  for r in select * from public.inventory_item where origin = 'auction' loop
    insert into public.product
      (company_id, name, cat1_id, cat2_id, cat3_id, description, sale_price, is_unique)
    values
      (r.company_id, r.name, r.cat1_id, r.cat2_id, r.cat3_id, r.description, r.sale_price, true)
    returning id into new_product_id;
    update public.inventory_item set product_id = new_product_id where id = r.id;
  end loop;
end $$;

-- Numeración de lotes por producto, en orden de entrada.
with numerados as (
  select id, row_number() over (partition by product_id order by entry_date, created_at, id) as n
  from public.inventory_item
  where product_id is not null
)
update public.inventory_item i
set lot_number = numerados.n
from numerados
where numerados.id = i.id;

-- El SKU del producto se hereda del código del primer lote que ya lo tenía
-- (quitándole la letra de proveedor del final). Los que nunca se publicaron
-- quedan sin código hasta que se publique su primer lote.
update public.product p
set code = sub.base_code
from (
  select distinct on (i.product_id) i.product_id, left(i.code, length(i.code) - 1) as base_code
  from public.inventory_item i
  where i.code is not null and i.product_id is not null
  order by i.product_id, i.lot_number
) sub
where sub.product_id = p.id
  and sub.base_code is not null;

alter table public.product enable row level security;
alter table public.product force row level security;
create policy tenant_isolation on public.product
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());
