-- =====================================================================
-- 00016_purchase_check_restored.sql — Restituye el CHECK que 00015 quitó,
-- ahora que el código que manda `payment_method` ya está desplegado.
--
-- Cierra la secuencia de despliegue sin downtime que 00015 dejó a medias:
--
--   00014  columnas nullable        (compatible con el código viejo)
--   00015  quitar el CHECK          (el deploy falló, había que desbloquear)
--          fly deploy               ✅ el backend ya manda payment_method
--   00016  restituir el CHECK       <- este archivo
--
-- La regla que hace cumplir es la misma de 00014, y no es cosmética: sin ella
-- vuelve a ser posible una compra sin medio de pago (que descuadra el cierre
-- de caja — el bug original que motivó todo esto) o un remate CON medio de
-- pago (que nadie sabría interpretar en el acta). Hasta ahora esa regla la
-- sostenía solo `inventory.service.create_entry`; a partir de acá la base
-- también, que es donde debe vivir un invariante de este tipo.
--
-- NOT VALID por la misma razón que en 00014: las compras anteriores a este
-- trabajo tienen payment_method NULL y no se pueden backfillear (nadie sabe
-- hoy con qué se pagó cada una). La regla aplica a todo INSERT/UPDATE de aquí
-- en adelante sin inventar datos del pasado.
-- =====================================================================

alter table public.inventory_entry
  add constraint inventory_entry_payment_method_matches_origin check (
    (origin_type = 'purchase' and payment_method is not null)
    or (origin_type <> 'purchase' and payment_method is null)
  ) not valid;
