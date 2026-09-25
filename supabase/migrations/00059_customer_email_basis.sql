-- =====================================================================
-- 00059_customer_email_basis.sql — la base legal del correo del cliente
-- (fase 3 de docs/NOTIFICACIONES.md; diseño en §9.2).
--
-- "¿Tengo permiso para escribirle?" estaba mal planteada como un booleano.
-- Bien planteada son dos datos: PARA QUÉ es el correo (`purpose`, ya en el
-- catálogo desde 00058) y BAJO QUÉ BASE tengo la dirección de esta persona
-- (esta migración). El cruce de los dos vive en un solo lugar del código
-- (`notifications/catalog.py::PURPOSE_ACCEPTED_BASES`), y es configuración
-- de la PLATAFORMA: si un abogado dice "estricto", cambia una línea de
-- código y ninguna fila de acá.
--
-- COLUMNAS EN `customer`, Y POR QUÉ CADA UNA:
--
--   email_basis           'contract' | 'consent' | null (= ninguna).
--   email_basis_at        cuándo se escribió la base vigente. Para 'contract'
--                         no hay otra fecha que la diga; para 'consent'
--                         coincide con email_consent_at.
--   email_consent_at      cuándo autorizó EXPRESAMENTE. Solo con 'consent'.
--                         Nunca se escribe una fecha de autorización que no
--                         ocurrió (§9.2-g): sería fabricar la prueba.
--   email_consent_source  dónde se capturó: 'counter' (la ficha del cliente
--                         en el mostrador), 'contract_form' (al crear el
--                         contrato, §1c — todavía sin pantalla), 'import'.
--   email_opt_out_at      pidió la baja. Gana sobre CUALQUIER base (§9.2-c):
--                         tener derecho a escribir no es tener razón.
--   email_invalid_at      rebotó duro (§6.3, §9.3). La escribirá el webhook
--                         de Resend; nace acá para que ese día no haga
--                         falta otra migración.
--
-- **La base se ESCRIBE, no se deduce** (§9.2-a): la que importa es la que
-- había el día que salió el correo, y eso hay que poder mostrarlo meses
-- después. Por la misma razón `notification_delivery.legal_basis` guarda,
-- en cada entrega, la base con la que se decidió mandarla.
--
-- BACKFILL: 'contract' en los clientes que HOY tienen correo y al menos un
-- contrato no terminal. Nadie queda en 'consent': nadie autorizó nada
-- todavía. `email_basis_at` = el momento de la migración, que es cuándo se
-- escribió de verdad; no se inventa una fecha anterior.
--
-- Aditiva: el código viejo no lee estas columnas y trata la base de todo
-- cliente como nula (todo aviso al cliente queda `suppressed`), así que se
-- puede aplicar antes del deploy. Ningún aviso al cliente se enciende por
-- esto: nacen apagados por catálogo (§12.3) y el interruptor por empresa
-- también está apagado.
-- =====================================================================

alter table public.customer
  add column email_basis          text
    check (email_basis in ('contract', 'consent')),
  add column email_basis_at       timestamptz,
  add column email_consent_at     timestamptz,
  add column email_consent_source text
    check (email_consent_source in ('counter', 'contract_form', 'import')),
  add column email_opt_out_at     timestamptz,
  add column email_invalid_at     timestamptz;

-- Las tres invariantes que el esquema puede garantizar solo:
-- una base sin fecha (o una fecha sin base) no dice nada;
alter table public.customer add constraint customer_email_basis_dated
  check ((email_basis is null) = (email_basis_at is null));
-- 'consent' sin cuándo ni dónde no es prueba de nada;
alter table public.customer add constraint customer_email_consent_proven
  check (email_basis is distinct from 'consent'
         or (email_consent_at is not null and email_consent_source is not null));
-- y una fecha de autorización colgando de otra base es una prueba que no
-- corresponde a lo que rige.
alter table public.customer add constraint customer_email_consent_only_with_consent
  check ((email_consent_at is null and email_consent_source is null)
         or email_basis = 'consent');

comment on column public.customer.email_basis is
  'Base legal del correo (docs/NOTIFICACIONES.md §9.2): contract | consent | null = ninguna.';
comment on column public.customer.email_opt_out_at is
  'Pidió la baja de los avisos por correo. Gana sobre cualquier base (§9.2-c).';

-- La evidencia de cada envío: con qué base se decidió. Nula en las entregas
-- que no son al cliente y en las que no salieron por falta de base.
alter table public.notification_delivery
  add column legal_basis text check (legal_basis in ('contract', 'consent'));

-- Backfill (§9.2-a, §9.2-g).
update public.customer c
   set email_basis = 'contract',
       email_basis_at = now()
 where nullif(btrim(c.email), '') is not null
   and c.email_basis is null
   and exists (
     select 1 from public.contract k
      where k.company_id = c.company_id
        and k.customer_id = c.id
        and k.status not in ('paid', 'auctioned', 'superseded')
   );
