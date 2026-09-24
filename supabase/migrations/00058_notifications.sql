-- =====================================================================
-- 00058_notifications.sql — la maquinaria de avisos por correo (fase 1).
--
-- Diseño completo y decisiones: docs/NOTIFICACIONES.md. Acá solo lo que
-- el esquema tiene que garantizar por sí mismo.
--
-- TRES TABLAS, Y POR QUÉ NO UNA:
--
--   notification_event_type  EL CATÁLOGO. Global (sin company_id), como
--                            `permission`: qué avisos existen, a quién van
--                            (`audience`), para qué (`purpose`) y si nacen
--                            encendidos (`default_enabled`).
--   notification_event       EL HECHO. Se escribe SIEMPRE, aunque no haya
--                            por dónde avisar o el aviso esté apagado.
--   notification_delivery    EL INTENTO, por canal y destinatario.
--
-- Es el patrón de siempre: el documento guarda el hecho, las filas hijas
-- sus efectos (§4.1). WhatsApp, el día que llegue, es un valor más de
-- `channel` sobre eventos que ya existen — un insert, no una migración.
--
-- **`purpose` no tiene default a propósito** (§9.2-b): el día que alguien
-- agregue "promoción de fin de año" tiene que decidir si es `marketing`,
-- y un default cómodo le ahorraría pensarlo.
--
-- **Todos los avisos al CLIENTE nacen con `default_enabled = false`**
-- (§12.3, decisión del 24/09/2026: las tres preguntas legales quedaron en
-- pausa). Encender uno es poner
-- `company.settings.notifications.events.<code> = true` — un interruptor
-- por empresa, sin código ni migración.
--
-- IDEMPOTENCIA (§6): `unique (company_id, dedupe_key)`. La llave la arma
-- el productor con lo que hace único al hecho (el documento, o la fecha de
-- la que habla un recordatorio), nunca con la hora a la que corrió el job.
-- En el job el choque NO es un error: `on conflict do nothing`.
--
-- Aditiva de punta a punta. Nada de lo que ya corre la mira: se puede
-- aplicar antes del deploy.
-- =====================================================================

-- ---------------------------------------------------------------------
-- El catálogo
-- ---------------------------------------------------------------------
create table public.notification_event_type (
  code            text primary key,
  audience        text not null check (audience in ('customer', 'company', 'platform')),
  purpose         text not null check (purpose in ('service', 'marketing')),
  family          text not null
                    check (family in ('transactional', 'reminder', 'state', 'digest',
                                      'alert', 'platform')),
  default_enabled boolean not null,
  description     text not null
);

alter table public.notification_event_type enable row level security;
alter table public.notification_event_type force row level security;
-- Catálogo visible a cualquier usuario autenticado de una empresa, igual
-- que `permission`: la pantalla de preferencias lo lista.
create policy notification_event_type_read_all on public.notification_event_type
  for select using (public.current_company_id() is not null);

-- Espejo EXACTO de `app/modules/notifications/catalog.py`; un test compara
-- las dos listas en las dos direcciones.
insert into public.notification_event_type
  (code, audience, purpose, family, default_enabled, description) values
  -- §2.1 transaccionales al cliente (C1–C7). Apagados: §12.3.
  ('contract_created',       'customer', 'service', 'transactional', false,
   'C1 · Contrato creado: número, monto y fecha de la próxima cuota'),
  ('payment_registered',     'customer', 'service', 'transactional', false,
   'C2 · Abono registrado: qué pagó, hasta cuándo quedó cubierto y saldo'),
  ('contract_paid_off',      'customer', 'service', 'transactional', false,
   'C3 · Paz y salvo: el contrato quedó saldado'),
  ('loan_extended',          'customer', 'service', 'transactional', false,
   'C4 · Préstamo ampliado: nace un contrato sucesor'),
  ('credit_note_issued',     'customer', 'service', 'transactional', false,
   'C5 · Nota crédito emitida: saldo a favor'),
  ('sale_receipt',           'customer', 'service', 'transactional', false,
   'C6 · Comprobante de venta (solo ventas con cliente)'),
  ('sale_reversed',          'customer', 'service', 'transactional', false,
   'C7 · Venta anulada o devolución'),
  -- §2.2 recordatorios y cambios de estado al cliente (R1–R5). Apagados: §12.3.
  ('installment_due_soon',   'customer', 'service', 'reminder', false,
   'R1 · Cuota por vencer (3 días antes y el día del vencimiento)'),
  ('installment_overdue',    'customer', 'service', 'state', false,
   'R2 · Cuota vencida: el contrato entró en mora'),
  ('extension_started',      'customer', 'service', 'state', false,
   'R3 · El contrato entró en prórroga'),
  ('extension_ending_soon',  'customer', 'service', 'reminder', false,
   'R4 · La prórroga vence pronto'),
  ('auction_ready_customer', 'customer', 'service', 'state', false,
   'R5 · Aviso al cliente de que su prenda está lista para remate'),
  -- §2.4 resumen a la empresa. Encendidos: el dato no sale de la empresa.
  ('company_daily_digest',   'company',  'service', 'digest', true,
   'Resumen diario a la empresa: sale solo si hubo actividad o alertas'),
  ('company_weekly_digest',  'company',  'service', 'digest', true,
   'Resumen semanal a la empresa (lunes): sale siempre'),
  -- §2.5 alertas inmediatas a la empresa (fase 7; el tipo ya existe).
  ('alert_sale_voided',      'company',  'service', 'alert', true,
   'A1 · Venta anulada'),
  ('alert_discount',         'company',  'service', 'alert', true,
   'A2 · Descuento por encima del umbral de la empresa'),
  ('alert_capital_withdrawal','company', 'service', 'alert', true,
   'A3 · Retiro de capital del dueño'),
  ('alert_cash_reopened',    'company',  'service', 'alert', true,
   'A4 · Caja reabierta'),
  -- §2.6 de la plataforma (fase 2; el tipo ya existe).
  ('user_invitation',        'platform', 'service', 'platform', true,
   'P1 · Invitación de usuario');

-- ---------------------------------------------------------------------
-- El hecho
-- ---------------------------------------------------------------------
create table public.notification_event (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references public.company(id),
  event_type  text not null references public.notification_event_type(code),
  audience    text not null check (audience in ('customer', 'company', 'platform')),
  customer_id uuid references public.customer(id),
  entity_type text,
  entity_id   uuid,
  -- Lo MÍNIMO para redactar (§9.1): nunca cédula ni descripción de prenda.
  payload     jsonb not null default '{}'::jsonb,
  dedupe_key  text not null,
  -- El día de la EMPRESA, no UTC (§4.1, ARCHITECTURE §10).
  occurred_on date not null,
  -- La fecha de la que HABLA el aviso (vencimiento, fin de prórroga, día del
  -- resumen). Con ella el despachador aplica la ventana de rezago (§5.3):
  -- un aviso cuya fecha quedó más de `stale_after_days` atrás no se manda.
  -- Nula = el aviso no caduca (un paz y salvo sirve igual una semana tarde).
  target_date date,
  created_at  timestamptz not null default now(),
  unique (company_id, dedupe_key)
);
create index ix_notification_event_company_date
  on public.notification_event (company_id, occurred_on desc);

-- ---------------------------------------------------------------------
-- El intento
-- ---------------------------------------------------------------------
create table public.notification_delivery (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references public.company(id),
  event_id          uuid not null references public.notification_event(id),
  channel           text not null default 'email' check (channel in ('email')),
  -- Nulo cuando es `unroutable`: "había algo que avisar y no había por dónde".
  to_address        text,
  recipient_user_id uuid references public.app_user(id),
  status            text not null
                      check (status in ('pending', 'sending', 'sent', 'delivered', 'bounced',
                                        'failed', 'dead', 'unroutable', 'suppressed',
                                        'throttled', 'skipped_stale', 'skipped_no_provider')),
  attempts          int not null default 0,
  last_error        text,
  provider_id       text,          -- el id de Resend, para cruzar con su panel
  scheduled_at      timestamptz not null default now(),
  sent_at           timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  check (status <> 'unroutable' or to_address is null),
  check (status in ('unroutable') or to_address is not null),
  -- Un destinatario, un canal, un intento vivo por evento. `nulls not
  -- distinct`: dos `unroutable` del mismo evento serían el mismo hecho.
  unique nulls not distinct (event_id, channel, to_address)
);
create trigger trg_notification_delivery_updated before update on public.notification_delivery
  for each row execute function public.set_updated_at();
-- El barrido del despachador (§6.3): pendientes y reintentables cuya hora llegó.
create index ix_notification_delivery_due
  on public.notification_delivery (scheduled_at)
  where status in ('pending', 'failed');
-- El listado de entregas recientes de la empresa.
create index ix_notification_delivery_company_date
  on public.notification_delivery (company_id, created_at desc);
-- El tope por destinatario (Ley 2300, §12.3): cuántos le salieron esta semana.
create index ix_notification_delivery_recipient_sent
  on public.notification_delivery (company_id, channel, to_address, sent_at)
  where sent_at is not null;

do $$
declare t text;
begin
  foreach t in array array['notification_event', 'notification_delivery']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format(
      'create policy tenant_isolation on public.%I
         using (company_id = public.current_company_id())
         with check (company_id = public.current_company_id())', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- Permisos (§4.3): quién RECIBE, no quién configura. Configurar es
-- `company.configure`, que ya existe.
--
--   notifications.receive_digest  recibir el resumen diario/semanal (§2.4)
--   notifications.receive_alerts  recibir las alertas inmediatas (§2.5, fase 7)
--
-- Solo al Admin por defecto (§4.3: "Usuario → Solo Admin"). El resumen
-- lleva descuadres de caja, descuentos y el vencimiento de la suscripción:
-- es la misma pregunta que quién ve el reporte de caja entero, y el
-- Moderador ya está excluido de `audit.view` y `company.configure`. Los
-- roles semilla se arman en `platform/service.py` (se excluyen ahí del
-- Moderador); para las empresas que YA existen se le dan a su rol de
-- administrador con el mismo testigo que usó 00054: `identity.manage_roles`.
-- ---------------------------------------------------------------------
insert into public.permission (code, module, action, is_special, description) values
  ('notifications.receive_digest', 'notifications', 'receive_digest', false,
   'Recibir por correo el resumen diario y semanal de la empresa'),
  ('notifications.receive_alerts', 'notifications', 'receive_alerts', false,
   'Recibir por correo las alertas inmediatas (anulaciones, descuentos, retiros, reaperturas)')
on conflict (code) do nothing;

insert into public.role_permission (role_id, permission_id)
select rp.role_id, p2.id
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'identity.manage_roles'
cross join public.permission p2
where p2.code in ('notifications.receive_digest', 'notifications.receive_alerts')
on conflict do nothing;
