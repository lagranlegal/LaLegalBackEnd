-- =====================================================================
-- 00039_item_source_transformation.sql — que un lote de oro pueda decir
-- DE DÓNDE SALIÓ.
--
-- EL HUECO: 00037 construyó la transformación como un documento que enlaza un
-- egreso y un ingreso, y dejó escrito que con eso "la trazabilidad de una
-- pieza rematada sobrevive: contrato -> remate -> artículo -> transformación
-- -> lote de oro". Es cierto — pero solo en esa dirección. Al revés no:
-- parado en el lote de oro, la única forma de llegar a la transformación era
--
--   item -> inventory_entry_line -> inventory_entry (origin_type=...)
--        -> inventory_transformation
--
-- cuatro saltos, ninguno expuesto por un endpoint. En la práctica, imposible.
--
-- POR QUÉ IMPORTA EN UNA COMPRAVENTA. Ese oro puede venir de la prenda que un
-- cliente dejó empeñada. Si mañana aparece un reclamo —o una autoridad
-- preguntando por una pieza— la cadena tiene que poder recorrerse hacia atrás
-- desde lo que hay en la vitrina hoy. Es el mismo motivo por el que
-- `source_contract_id` existe desde 00006 para el remate: sin el puntero de
-- vuelta, el vínculo existe en los datos pero no en la aplicación.
--
-- Y contablemente: el costo de ese lote salió de repartir el costo de lo
-- consumido entre lo producido. Un costo sin forma de auditar su origen es un
-- número sin respaldo, y ese número es el que decide la utilidad de la venta.
--
-- ES EL TERCER PUNTERO DE ORIGEN, y los tres son excluyentes entre sí:
--   `supplier_id`             se lo compramos a alguien
--   `source_contract_id`      salió de un remate
--   `source_transformation_id` lo produjimos nosotros fundiendo/despiezando
-- Ninguno de los tres -> mercancía propia sin documento externo (inventario
-- inicial o sobrante de conteo, 00033).
--
-- Esa distinción es justo la que la LETRA DEL CÓDIGO no podía hacer: todo lo
-- que no era proveedor ni remate caía en `P` de propio, así que una etiqueta
-- no distinguía oro fundido de mercancía que ya estaba el día uno. Con este
-- puntero, `publish_item` puede emitir `T` y la etiqueta vuelve a decir la
-- verdad.
--
-- ADITIVA. Se hace backfill de lo ya transformado.
-- =====================================================================

alter table public.inventory_item
  add column if not exists source_transformation_id uuid
    references public.inventory_transformation(id);

comment on column public.inventory_item.source_transformation_id is
  'Solo en artículos PRODUCIDOS por una transformación (fundir, despiezar, '
  'armar). Excluyente con supplier_id y source_contract_id. Es lo que hace '
  'que la letra del código sea T y no P.';

-- Para "¿qué salió de esta transformación?" sin recorrer la tabla entera.
-- Parcial porque la enorme mayoría de artículos no vienen de una.
create index if not exists ix_item_source_transformation
  on public.inventory_item (company_id, source_transformation_id)
  where source_transformation_id is not null;

-- ---------------------------------------------------------------------
-- Backfill: lo ya transformado antes de que la columna existiera.
--
-- El vínculo se reconstruye por el camino largo que este cambio viene a
-- reemplazar — que sigue siendo correcto, solo incómodo. Se puede hacer una
-- sola vez y sin ambigüedad: cada `inventory_entry` de una transformación
-- pertenece a exactamente una (`entry_id` es único en la práctica, un ingreso
-- no se comparte entre dos transformaciones).
--
-- NO se recalculan códigos ya emitidos: un código es inmutable (CLAUDE.md).
-- Un lote que salió publicado como `P` antes de hoy se queda `P` — la
-- etiqueta impresa que está pegada a la bolsa no se puede cambiar desde una
-- migración. Lo que sí gana es el puntero, así que la app puede mostrar su
-- origen aunque la letra no lo diga.
-- ---------------------------------------------------------------------
update public.inventory_item i
set source_transformation_id = t.id
from public.inventory_entry_line el
join public.inventory_transformation t on t.entry_id = el.entry_id
where el.item_id = i.id
  and el.company_id = i.company_id
  and i.source_transformation_id is null;
