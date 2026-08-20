-- =====================================================================
-- 00014_inventory_purchase_cash.sql — La compra a proveedor pasa por caja.
--
-- Hueco real encontrado auditando el código: el enum `cash_concept` define
-- 'purchase' ("compra a proveedor (out, store)") desde 00007, pero
-- `inventory.service.create_entry` nunca llamaba a `cashbox.record_movement`.
-- Consecuencia: `expected_cash` (base + movimientos en efectivo) ignoraba la
-- plata entregada al proveedor, así que TODO día en que se compró mercancía
-- en efectivo cerraba con descuadre — y la política es "sin tolerancia,
-- justificación obligatoria" (CLAUDE.md), o sea que el operador quedaba
-- obligado a justificar un descuadre que el propio sistema fabricaba.
--
-- Dos columnas, ninguna migración de datos:
--
-- `payment_method` — NULLABLE a propósito. Solo los ingresos con
-- origin_type='purchase' mueven dinero; los de 'auction' (remate) NO — ahí el
-- capital ya salió como préstamo en su momento y el artículo entra al
-- inventario como conversión de un activo, no como una compra nueva. Un
-- ingreso 'other' tampoco mueve caja. El CHECK de abajo hace cumplir esa
-- correspondencia en la base, no solo en el servicio.
--
-- `idempotency_key` — CLAUDE.md regla 4 ("obligatorio en operaciones de
-- dinero"): `contract`, `contract_payment` y `sale` ya lo tenían; el ingreso
-- de inventario movía costo y stock sin esa garantía, así que un doble click
-- con red inestable duplicaba ingreso, stock y costo, sin `DELETE` con el
-- cual deshacerlo. NULLABLE por la misma razón que en 00009: hay filas
-- creadas antes de que el backend mandara el header y no hay key real que
-- backfillear. UNIQUE con NULLs es seguro en Postgres (cada NULL cuenta como
-- distinto), así que las filas viejas no chocan entre sí ni bloquean nuevas.
-- =====================================================================

alter table public.inventory_entry add column payment_method payment_method;
alter table public.inventory_entry add column idempotency_key text;

alter table public.inventory_entry
  add constraint inventory_entry_idempotency_key_unique unique (company_id, idempotency_key);

-- Un ingreso de compra SIEMPRE dice con qué medio se pagó (es lo que decide
-- si afecta el efectivo esperado del cierre o se concilia por otro medio);
-- los demás orígenes nunca lo llevan, para que no exista la ambigüedad de un
-- remate con medio de pago que nadie sabría interpretar en el acta.
--
-- NOT VALID: las compras registradas ANTES de esta migración tienen
-- payment_method NULL y violarían el CHECK. No se pueden backfillear (nadie
-- sabe hoy con qué se pagó cada una) y borrarlas no es opción. NOT VALID
-- aplica la regla a todo INSERT/UPDATE de aquí en adelante y deja las filas
-- históricas como están — que es exactamente lo que se quiere: el hueco se
-- cierra hacia el futuro sin inventar datos del pasado.
alter table public.inventory_entry
  add constraint inventory_entry_payment_method_matches_origin check (
    (origin_type = 'purchase' and payment_method is not null)
    or (origin_type <> 'purchase' and payment_method is null)
  ) not valid;
