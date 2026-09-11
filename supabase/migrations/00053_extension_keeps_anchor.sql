-- =====================================================================
-- 00053_extension_keeps_anchor.sql — el recargo deja de mover la fecha de
-- cobro, y queda registrado cuándo ocurrió de verdad.
--
-- EL CASO (Mateo, 11/09/2026, probando con el cliente): presta 1.000.000 el
-- día 1 y el cliente recarga 500.000 el día 25. Hasta hoy el sucesor nacía
-- con `start_date = hoy` e `interest_paid_until = hoy`, así que la próxima
-- cuota se cobraba el 25 de octubre y no el 1. El cliente tenía una fecha
-- de pago que se le movía sola cada vez que volvía por plata.
--
-- LO QUE SE PIDIÓ: que el sucesor conserve la fecha del contrato original,
-- para que el día 1 del mes siguiente se cobre interés sobre 1.500.000 sin
-- importar en qué día del mes se hizo el recargo.
--
-- POR QUÉ ES LA OPCIÓN CORRECTA Y NO UNA CUARTA POLÍTICA: RECARGOS.md §5
-- planteaba tres respuestas al "pedazo de mes corrido sobre el capital
-- viejo" — perdonarlo, cobrar un mes completo, o prorratear (descartada
-- porque rompe la regla de meses completos). Heredar el ancla DISUELVE la
-- pregunta: no hay pedazo que resolver, porque el mes en curso se cobra
-- entero al capital nuevo cuando venza. Y le gana a `forgive` por los dos
-- lados: hoy un recargo el día 27 perdona ~45.000 Y ADEMÁS corre la próxima
-- fecha de pago 27 días.
--
-- EL FILO, dicho en voz alta: un recargo dos días antes del aniversario
-- hace que el cliente pague un mes completo sobre el capital nuevo casi de
-- inmediato. No es anatocismo —no se capitaliza interés, es plata que se
-- entregó— y es lo que hace la mayoría de compraventas, pero la pantalla
-- tiene que decirlo ANTES de confirmar. Eso vive en el front.
-- =====================================================================

-- ---------------------------------------------------------------------
-- La política. El campo ya existía desde 00051 con dos valores y NADA lo
-- exponía — se dejó puesto justamente para el día que apareciera una regla
-- nueva (RECARGOS.md §8.2, "una columna, un default, cero UI el día uno").
-- Este es ese día.
--
--   keep_anchor   (NUEVO, y el default desde hoy) el sucesor hereda la
--                 fecha del contrato ORIGINAL y el ancla del interés. La
--                 fecha de cobro no se mueve nunca.
--   forgive       el reloj se reinicia; los días corridos se perdonan.
--   charge_month  exige el mes de interés pagado antes de ampliar.
--
-- Los contratos YA FIRMADOS conservan su `forgive`: la columna es SNAPSHOT
-- y cambiar el default no puede alterar lo pactado. Es la misma regla que
-- protege la tasa y el plazo.
-- ---------------------------------------------------------------------
alter table public.contract
  drop constraint if exists contract_extension_interest_policy_check;

alter table public.contract
  add constraint contract_extension_interest_policy_check
  check (extension_interest_policy in ('keep_anchor', 'forgive', 'charge_month'));

alter table public.contract
  alter column extension_interest_policy set default 'keep_anchor';

-- ---------------------------------------------------------------------
-- La trazabilidad, que con este cambio deja de ser un extra.
--
-- Antedatar `start_date` rompe dos cosas que dependían de él para responder
-- "¿cuándo se hizo el recargo?":
--
--   · El detalle del contrato decía «Sucede a un contrato anterior,
--     ampliado el {start_date}» — pasaría a mentir con la fecha del
--     original.
--   · El impreso dice «Fecha: {start_date}». El papel que el cliente firma
--     el 25 saldría fechado el 1, sin nada más. Eso es un documento
--     antedatado, y es un problema más grande que el que se resuelve.
--
-- POR QUÉ COLUMNAS Y NO DERIVARLO DE `created_at`:
--
--   · `created_at` es un timestamptz y el "día" del negocio es el de la
--     ZONA DE LA EMPRESA. Convertirlo en cada lectura es exactamente el
--     cálculo que a este proyecto ya le costó el bug de las 5 horas dos
--     veces (una en el backend, otra dentro de un test).
--   · `created_at` no distingue un sucesor de un contrato importado ni de
--     uno normal. `extended_on` nombra el hecho.
--   · Y el MONTO no está en ninguna columna: vive en el `cash_movement` y
--     en el `audit_log`. Para escribir "recargo de $500.000 el 25/09" en la
--     pantalla y en el papel hay que ir a buscarlo a otra tabla.
--
-- Ambas son NULL en todo contrato que no nació de un recargo, y esa es su
-- otra función: `extended_on is not null` es la respuesta a "¿este contrato
-- es un sucesor?" sin mirar la cadena.
-- ---------------------------------------------------------------------
alter table public.contract
  add column if not exists extended_on      date,
  add column if not exists extension_amount numeric(14,2)
    check (extension_amount is null or extension_amount > 0);

comment on column public.contract.extended_on is
  'Día REAL en que se hizo el recargo que dio origen a este contrato, en la '
  'zona horaria de la empresa. NULL si el contrato no nació de un recargo. '
  'Va aparte de start_date a propósito: desde 00053 start_date es la fecha '
  'del contrato ORIGINAL de la cadena (el ancla legal del interés), así que '
  'ya no puede responder cuándo se entregó la plata nueva.';

comment on column public.contract.extension_amount is
  'Lo que se le entregó al cliente EN ESE recargo — el delta, no el capital '
  'total. NULL si el contrato no nació de un recargo. Es el mismo monto del '
  'cash_movement loan_disbursed que referencia a este contrato; se copia acá '
  'para poder mostrarlo con el documento sin cruzar tablas.';

-- Aditiva de punta a punta: dos columnas nullable, un default y un CHECK
-- que solo AMPLÍA los valores aceptados. Se puede aplicar antes del deploy.
