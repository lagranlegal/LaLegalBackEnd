-- =====================================================================
-- 00048_cash_balance_from_movements.sql
--
-- El saldo de una cuenta de efectivo deja de ser propiedad de la SESIÓN de
-- caja y pasa a ser propiedad de la CUENTA, derivado de sus movimientos —
-- igual que ya ocurre con una cuenta `bank`.
--
-- POR QUÉ (docs/CAJA_TRAZABILIDAD.md):
--   `cash_session.opening_balance` era un número DIGITADO A MANO cada
--   mañana, sin comparación contra el cierre de la noche anterior. Era el
--   único número de toda la aplicación que aparecía sin documento — contra
--   la regla 5 de CLAUDE.md ("nunca editables a mano"). Efectos colaterales
--   del mismo error: sin sesión abierta una cuenta de efectivo reportaba
--   0.00 (la plata dejaba de existir entre las 8pm y las 8am), y todas las
--   cuentas de efectivo de una empresa reportaban el MISMO saldo, porque
--   todas leían la única sesión abierta.
--
-- ESTA MIGRACIÓN NO CAMBIA EL ESQUEMA: convierte la historia en
-- movimientos, que es lo que el saldo derivado va a leer. Sin esto, al
-- cambiar el cálculo todas las cuentas de efectivo arrancarían en cero y
-- perderían la plata con la que cada empresa venía operando.
--
-- Los movimientos que crea llevan `session_id = NULL` A PROPÓSITO: no son
-- operaciones del turno, son correcciones de la CUENTA. Dejarlos fuera de
-- la sesión mantiene intacto el cálculo de `expected_cash` y las actas de
-- cierre ya impresas, que siguen dando exactamente el mismo número. La
-- trazabilidad no se pierde: `reference_type`/`reference_id` apuntan a la
-- sesión que causó cada ajuste.
-- =====================================================================

-- La cuenta de efectivo que recibe la historia: la predeterminada de la
-- empresa y, si ninguna lo es, la más antigua. Es la que venían usando los
-- movimientos, porque `_default_account_for` resuelve igual.
create temporary table _cash_account on commit drop as
select distinct on (company_id)
       company_id,
       id as account_id
from public.account
where type = 'cash'
order by company_id, is_default desc, created_at;

-- Cada sesión con la de su día anterior al lado, por caja registradora.
create temporary table _chain on commit drop as
select s.id,
       s.company_id,
       s.register_id,
       s.session_date,
       s.opening_balance,
       s.counted_cash,
       s.difference,
       s.status,
       s.opened_at,
       s.opened_by,
       s.closed_at,
       s.closed_by,
       lag(s.counted_cash) over w  as prev_counted,
       lag(s.status) over w        as prev_status
from public.cash_session s
window w as (partition by s.register_id order by s.session_date, s.opened_at);

-- ---------------------------------------------------------------------
-- 1. El saldo con el que cada empresa arrancó, y cada descuadre de
--    apertura que nadie miró.
--
--    Primera sesión de la caja  -> su `opening_balance` completo: es el
--                                  efectivo con el que la empresa entró al
--                                  sistema.
--    Sesiones siguientes        -> solo la DIFERENCIA contra lo contado la
--                                  noche anterior. Si coinciden no se
--                                  emite nada, que es el caso sano.
--
--    Esa diferencia es información que hasta hoy no existía en ninguna
--    parte: la plata que apareció o desapareció entre un cierre y la
--    apertura siguiente sin que nadie la registrara.
-- ---------------------------------------------------------------------
insert into public.cash_movement
  (company_id, session_id, account_id, module, direction, concept, reference_type,
   reference_id, amount, payment_method, notes, created_by, created_at)
select c.company_id,
       null,
       a.account_id,
       'general'::cash_module,
       (case when delta.v > 0 then 'in' else 'out' end)::cash_direction,
       'adjustment'::cash_concept,
       'cash_session',
       c.id,
       abs(delta.v),
       'cash'::payment_method,
       case
         when c.prev_counted is null
           then 'Saldo inicial de efectivo al empezar a usar la aplicación (migración 00048).'
         else 'Descuadre entre el cierre anterior y esta apertura, reconstruido por la migración 00048. '
              || 'La apertura declaró ' || c.opening_balance || ' y la noche anterior se contaron '
              || c.prev_counted || '.'
       end,
       c.opened_by,
       c.opened_at
from _chain c
join _cash_account a on a.company_id = c.company_id
cross join lateral (
  select case
           when c.prev_counted is null or c.prev_status is distinct from 'closed'
             then c.opening_balance
           else c.opening_balance - c.prev_counted
         end as v
) as delta
where delta.v <> 0;

-- ---------------------------------------------------------------------
-- 2. El descuadre de cada cierre, que hasta hoy vivía como un CAMPO del
--    acta y no movía el saldo. Ahora es una línea del libro: el saldo
--    derivado queda en lo que de verdad se contó.
-- ---------------------------------------------------------------------
insert into public.cash_movement
  (company_id, session_id, account_id, module, direction, concept, reference_type,
   reference_id, amount, payment_method, notes, created_by, created_at)
select c.company_id,
       null,
       a.account_id,
       'general'::cash_module,
       (case when c.difference > 0 then 'in' else 'out' end)::cash_direction,
       'adjustment'::cash_concept,
       'cash_session',
       c.id,
       abs(c.difference),
       'cash'::payment_method,
       'Descuadre del arqueo de cierre del ' || c.session_date
         || ', reconstruido por la migración 00048.',
       coalesce(c.closed_by, c.opened_by),
       coalesce(c.closed_at, c.opened_at)
from _chain c
join _cash_account a on a.company_id = c.company_id
where c.status = 'closed' and c.difference is not null and c.difference <> 0;

-- ---------------------------------------------------------------------
-- 3. `account.opening_balance` de las cuentas de efectivo se pone en cero.
--
--    Esa columna NUNCA se leyó para una cuenta `cash` —el saldo salía de la
--    sesión—, así que lo que tenga adentro es texto que alguien escribió y
--    que nada validó nunca. En dev hay una empresa con 2.000.000 y
--    4.000.000 en dos cuentas creadas por error durante una prueba: plata
--    que no existe y que, al empezar a leer la columna, aparecería de la
--    nada.
--
--    El saldo real de arranque ya quedó representado arriba, como
--    movimiento. De acá en adelante la columna SÍ se lee, así que una
--    cuenta de efectivo creada después de esta migración puede declarar el
--    efectivo que ya había en ese cajón y va a funcionar.
-- ---------------------------------------------------------------------
update public.account set opening_balance = 0
where type = 'cash' and opening_balance <> 0;
