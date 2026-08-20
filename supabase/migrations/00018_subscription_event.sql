-- =====================================================================
-- 00018_subscription_event.sql — Historial comercial de la suscripción.
--
-- Hoy la fila de `subscription` se MUTA en cada extensión: hay un índice
-- único que permite una sola suscripción 'active' por empresa, y extender
-- hace UPDATE sobre ella. `expires_at`, `extended_by` y `notes` se pisan, así
-- que la única foto que queda es la última — no hay forma de responder
-- "¿cuántas veces renovó esta empresa?" ni "¿qué decían las notas de la
-- renovación de marzo?".
--
-- El `audit_log` SÍ registra las extensiones (before/after de `expires_at`),
-- pero no sirve como historial comercial por dos razones distintas:
--   1. Es tenant-scoped por RLS. Un super-admin de plataforma jamás puede
--      leer el audit_log de una empresa que no es la suya, sin importar el
--      filtro — así que el rastro existe y es inalcanzable desde el panel.
--   2. Solo guarda `expires_at`. Las `notes` de cada extensión (el campo que
--      el super-admin llena para decir "pagó por transferencia el 3 de
--      marzo") no van en el after y se pierden para siempre.
--
-- Son dos registros con propósitos distintos y conviene no forzar a uno a
-- hacer de otro: `audit_log` es el registro de SEGURIDAD (quién tocó qué,
-- inmutable, por empresa); `subscription_event` es el registro COMERCIAL de
-- la relación con el cliente. El primero responde a una auditoría; el
-- segundo, a "¿esta empresa está al día y cuánto ha pagado?".
--
-- `amount` es opcional a propósito: el cobro es 100% manual y fuera del
-- sistema (CONTEXTO.md §3), así que registrar el monto es una conveniencia
-- para tener trazabilidad básica de pagos sin construir un módulo de
-- facturación. Una extensión sin monto sigue siendo válida.
-- =====================================================================

create type subscription_event_type as enum (
  'created',    -- alta de la empresa
  'extended',   -- renovación (la más frecuente)
  'suspended',  -- corte de acceso por el super-admin
  'activated',  -- reactivación
  'expired'     -- vencimiento automático (job nocturno)
);

create table public.subscription_event (
  id                  uuid primary key default gen_random_uuid(),
  company_id          uuid not null references public.company(id),
  subscription_id     uuid references public.subscription(id),
  event_type          subscription_event_type not null,
  -- Ambos NULL en eventos que no mueven la fecha (suspender/activar): así el
  -- historial distingue "renovó hasta X" de "le cortaron el acceso".
  previous_expires_at date,
  new_expires_at      date,
  amount              numeric(14,2) check (amount is null or amount >= 0),
  notes               text,
  created_by          uuid,
  created_at          timestamptz not null default now()
);

create index ix_subscription_event_company
  on public.subscription_event (company_id, created_at desc);

-- Se escribe y se lee SOLO desde el módulo `platform`, que corre con sesión
-- de bypass (service_role) igual que el resto de ese módulo. RLS habilitado y
-- forzado SIN políticas: ningún tenant puede leer ni escribir esta tabla ni
-- siquiera la suya, porque es información de la relación comercial entre la
-- plataforma y sus clientes (incluye montos pagados), no datos de la
-- operación de la compraventa. Si más adelante se decide mostrarle a una
-- empresa su propio historial de pagos, se agrega una política de SELECT
-- acotada — pero es una decisión de producto, no un olvido.
alter table public.subscription_event enable row level security;
alter table public.subscription_event force row level security;
