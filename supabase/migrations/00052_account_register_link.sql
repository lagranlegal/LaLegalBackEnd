-- ---------------------------------------------------------------------
-- 00052 — Ligar cada cajón a su caja registradora.
--
-- NO habilita multi-caja ni multi-sucursal. No hay tabla `branch`, no hay
-- `branch_id` y ningún endpoint cambia. Esto es PREPARACIÓN: poblar una
-- columna que `00049` agregó vacía, mientras hacerlo todavía es determinista.
--
-- POR QUÉ AHORA Y NO EL DÍA QUE SE IMPLEMENTE
--
-- Hoy cada empresa tiene EXACTAMENTE una caja registradora y EXACTAMENTE una
-- cuenta `cash` activa (verificado sobre las 7 empresas de dev el 10/09/2026,
-- ver `docs/SUCURSALES.md` §4). Con esos números, "¿a qué registradora
-- pertenece este cajón?" tiene una sola respuesta posible y la consulta de
-- abajo la encuentra sola.
--
-- El día que exista una segunda registradora o un segundo cajón, ese `limit 1`
-- deja de tener respuesta correcta y la atribución pasa a ser una decisión
-- humana, empresa por empresa, sobre datos ya mezclados. Es la diferencia
-- entre un UPDATE de cuatro líneas y una tarea de arqueología.
--
-- Es el mismo razonamiento con el que `propuesta-productos-lotes.html`
-- justificó hacer el cambio de producto+lote ANTES de cargar el inventario
-- real: el costo no está en programarlo, está en convertir los datos.
--
-- QUÉ NO TOCA, Y POR QUÉ
--
--   · Cuentas INACTIVAS. Una cuenta desactivada no pertenece a ningún
--     mostrador operativo, y adivinarle una registradora sería inventar un
--     dato. En dev eso deja fuera exactamente una fila: `Cajon mostrador 2`
--     del laboratorio de QA, que existe como evidencia de por qué dos
--     cajones hacen incuadrable el arqueo.
--   · Cuentas que no son `cash`. Un banco, un convenio o una caja fuerte no
--     son un punto de cobro de un mostrador — `vault` es `vault` justamente
--     porque no lo es (00049).
--
-- Idempotente por el `register_id is null`: reejecutarla no pisa nada.
-- ---------------------------------------------------------------------

update public.account a
   set register_id = (
         select r.id
           from public.cash_register r
          where r.company_id = a.company_id
            and r.active
          order by r.created_at
          limit 1
       )
 where a.type = 'cash'
   and a.active
   and a.register_id is null
   and exists (
         select 1 from public.cash_register r
          where r.company_id = a.company_id and r.active
       );
