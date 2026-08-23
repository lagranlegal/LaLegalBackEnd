-- =====================================================================
-- 00040_kardex_indexes.sql — poder preguntar "¿qué pasó con este producto?"
-- sin recorrer todas las líneas de la empresa.
--
-- EL KARDEX es el libro auxiliar de inventario: la historia completa de un
-- producto en una sola línea de tiempo, con saldo de unidades y de costo
-- corriendo. Hoy esa historia existe pero está partida en TRES tablas de
-- líneas que nadie une:
--
--   inventory_entry_line   compras, inventario inicial, sobrantes, remates,
--                          y lo que sale de una transformación
--   inventory_exit_line    ajustes, daños, pérdidas, devoluciones a proveedor,
--                          consumo interno, y lo que entra a una transformación
--   sale_line              ventas (y sus anulaciones, que reponen stock)
--
-- Las tres se consultan HACIA ADELANTE —dado un ingreso, qué artículos trajo—
-- y por eso están indexadas por su documento. La pregunta del kardex es la
-- contraria: dado un artículo, qué documentos lo tocaron. Sin índice por
-- `item_id` eso es un recorrido secuencial de todas las líneas de la empresa,
-- que crece para siempre aunque el producto tenga tres movimientos.
--
-- `inventory_exit_line` además no tenía NINGÚN índice fuera de su clave
-- primaria — ni siquiera por `exit_id`, que es como la consulta el detalle de
-- un egreso desde 00006. Pasó desapercibido porque los egresos son pocos.
--
-- Solo índices: ninguna tabla, columna ni dato cambia.
-- ADITIVA.
-- =====================================================================

create index if not exists ix_entry_line_item
  on public.inventory_entry_line (company_id, item_id);

create index if not exists ix_exit_line_item
  on public.inventory_exit_line (company_id, item_id);

create index if not exists ix_sale_line_item
  on public.sale_line (company_id, item_id);

-- El que faltaba desde 00006: el detalle de un egreso lista sus líneas por
-- `exit_id`, igual que ingresos y ventas, pero solo esas dos lo tenían.
create index if not exists ix_exit_line_exit
  on public.inventory_exit_line (exit_id);
