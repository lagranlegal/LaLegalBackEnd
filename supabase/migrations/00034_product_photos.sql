-- =====================================================================
-- 00034_product_photos.sql — la foto es del PRODUCTO, no del lote.
--
-- LA PREGUNTA QUE LO ORIGINA: "¿por qué la foto es obligatoria para
-- publicar un artículo?". No había razón técnica. La regla venía del spec
-- original (CLAUDE.md §Remate asistido: "publish valida precio/fotos") y se
-- aplicaba a TODO artículo, cuando la frase estaba escrita pensando en el
-- REMATE — donde sí tiene sentido fuerte: la foto es evidencia de qué
-- prenda dejó el cliente en garantía, y en joyería cada pieza es única.
--
-- Para mercancía fungible —cincuenta fundas de celular iguales, compradas
-- por docenas— exigir una foto POR LOTE es fricción sin beneficio: la foto
-- es la misma que ya se tomó la vez pasada.
--
-- LA RAÍZ ERA ESTRUCTURAL. 00022 subió el nombre, la categoría, la
-- descripción y el precio del lote al producto, y dejó las fotos abajo. Para
-- una pieza única eso es correcto (cada pieza es distinta). Para mercancía
-- repetida está en el lugar equivocado: obliga a re-fotografiar lo mismo en
-- cada reposición.
--
-- QUÉ HACE ESTA MIGRACIÓN
--
--   1. `product.photos` — cómo se ve ESTE producto. Se toma una vez y todos
--      sus lotes la heredan.
--   2. `inventory_item.photos` SE CONSERVA y pasa a ser un override del
--      lote, para lo que sí es propio de una compra puntual: documentar el
--      estado de una pieza, una tara, una variante de color. Las fotos
--      efectivas de un lote son las suyas si tiene, y si no las del
--      producto.
--
-- Se conserva en vez de contraerse porque las piezas de REMATE ya tienen sus
-- fotos ahí y son evidencia legal: moverlas y borrar la columna sería jugar
-- con lo único de este módulo que puede terminar en una discusión con un
-- cliente.
--
-- ADITIVA: no borra ni vuelve obligatorio nada, así que puede aplicarse
-- antes del deploy.
-- =====================================================================

alter table public.product
  add column photos jsonb not null default '[]';

-- ---------------------------------------------------------------------
-- Backfill: el producto hereda las fotos del lote MÁS ANTIGUO que tenga.
--
-- El más antiguo y no el más nuevo a propósito: es el que se fotografió
-- cuando el producto se dio de alta, así que es la foto "de catálogo". Un
-- lote posterior fotografiado aparte suele documentar algo puntual de esa
-- compra, que es justamente lo que NO queremos subir al producto.
-- ---------------------------------------------------------------------

update public.product p
set photos = sub.photos
from (
  select distinct on (i.product_id)
         i.product_id, i.photos
  from public.inventory_item i
  where i.photos is not null
    and jsonb_array_length(i.photos) > 0
  order by i.product_id, i.entry_date, i.created_at
) sub
where sub.product_id = p.id;

-- Verificación: ningún producto que tuviera fotos en algún lote debería
-- quedarse sin ellas. Si el backfill falló, mejor saberlo ahora que cuando
-- media vitrina aparezca sin imagen.
do $$
declare huerfanos int;
begin
  select count(distinct i.product_id) into huerfanos
  from public.inventory_item i
  join public.product p on p.id = i.product_id
  where jsonb_array_length(i.photos) > 0
    and jsonb_array_length(p.photos) = 0;
  if huerfanos > 0 then
    raise exception 'Quedaron % productos con lotes fotografiados y sin foto propia.', huerfanos;
  end if;
end $$;
