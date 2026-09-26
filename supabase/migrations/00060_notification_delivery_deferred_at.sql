-- =====================================================================
-- 00060_notification_delivery_deferred_at.sql — un recordatorio frenado
-- por el tope se REPROGRAMA en vez de perderse (docs/NOTIFICACIONES.md
-- §20.6, decisión de Mateo del 26/09/2026).
--
-- Hasta acá, un recordatorio al cliente que chocaba con el tope de la
-- Ley 2300 (un contacto por semana) quedaba `throttled`, terminal. Con R1
-- tres días antes del vencimiento y R2 el día del vencimiento, R2 chocaba
-- SIEMPRE, y el cliente nunca recibía el aviso de mora (§20.4).
--
-- Ahora la MISMA entrega vuelve a `pending` con `scheduled_at` en el
-- primer momento en que el tope y la hora hábil lo permiten. Esta columna
-- dice que eso pasó, y cuándo por primera vez:
--
--   deferred_at   el instante en que el tope la corrió por primera vez.
--                 Nula = nunca la frenó el tope.
--
-- POR QUÉ HACE FALTA UNA COLUMNA, y no alcanza con `scheduled_at`: el
-- despachador trata distinto a una entrega que el tope corrió.
--   1. No le aplica el rezago genérico (`stale_after_days`): una mora
--      avisada el martes sigue siendo verdad aunque su fecha objetivo sea
--      del jueves anterior. La acota su propia regla por tipo (§20.6).
--   2. Antes de mandarla re-verifica que el hecho siga siendo cierto: si
--      el cliente pagó mientras esperaba cupo, no sale.
-- La hora hábil también mueve `scheduled_at` y no debe activar ninguna de
-- las dos cosas; sin un dato propio, las dos esperas serían indistinguibles.
--
-- Reprogramar no cuenta como intento: `attempts` no se toca.
--
-- Aditiva: nullable, sin default, sin backfill (lo ya `throttled` se queda
-- como está — no se resucitan avisos viejos). El código nuevo la escribe;
-- el viejo la ignora. Se puede aplicar ANTES del deploy.
-- =====================================================================

alter table public.notification_delivery
  add column deferred_at timestamptz;

comment on column public.notification_delivery.deferred_at is
  'Cuándo el tope de contactos (Ley 2300) corrió por primera vez esta entrega '
  'en vez de dejarla throttled (NOTIFICACIONES §20.6). Nula = nunca la frenó.';
