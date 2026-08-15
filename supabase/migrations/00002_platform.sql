-- =====================================================================
-- 00002_platform.sql — Empresas (tenants), planes y suscripciones
-- Tablas de PLATAFORMA: sin company_id. Las gestiona solo el super-admin
-- (backend con service_role). RLS: los usuarios normales solo pueden
-- LEER su propia empresa; planes/suscripciones quedan denegadas (RLS sin
-- política = deny) y se acceden únicamente desde el backend de plataforma.
-- =====================================================================

create type company_status as enum ('active', 'suspended', 'inactive');
create type subscription_status as enum ('active', 'expired', 'suspended', 'canceled');

create table public.company (
  id             uuid primary key default gen_random_uuid(),
  name           text not null,
  legal_name     text,
  tax_id         text,
  contact_email  text,
  contact_phone  text,
  address        text,
  logo_url       text,
  signature_url  text,           -- firma empresarial insertada en los PDF de contratos
  settings       jsonb not null default '{"grace_days":30,"currency":"COP","timezone":"America/Bogota"}',
  status         company_status not null default 'active',
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create trigger trg_company_updated before update on public.company
  for each row execute function public.set_updated_at();

create table public.plan (
  id            uuid primary key default gen_random_uuid(),
  name          text not null unique,
  code          text not null unique,
  price         numeric(14,2),   -- referencial interna; el cobro es por fuera del sistema
  billing_cycle text not null default 'monthly',
  modules       jsonb not null default '{"pawn":true,"store":true}',
  max_users     int,
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

-- DECIDIDO: suscripción de gestión manual. El super-admin crea/amplía
-- expires_at cuando el cliente paga por fuera del sistema.
create table public.subscription (
  id           uuid primary key default gen_random_uuid(),
  company_id   uuid not null references public.company(id),
  plan_id      uuid not null references public.plan(id),
  status       subscription_status not null default 'active',
  starts_at    date not null default current_date,
  expires_at   date not null,
  extended_by  uuid,             -- super-admin que hizo la última extensión
  notes        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create trigger trg_subscription_updated before update on public.subscription
  for each row execute function public.set_updated_at();

-- Solo una suscripción vigente por empresa
create unique index uq_subscription_active
  on public.subscription (company_id)
  where status = 'active';

create index ix_subscription_expires on public.subscription (expires_at) where status = 'active';

-- ---------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------
alter table public.company enable row level security;
alter table public.company force row level security;
-- Un usuario autenticado solo puede LEER su propia empresa (logo, nombre, settings)
create policy company_read_own on public.company
  for select using (id = public.current_company_id());

alter table public.plan enable row level security;
alter table public.plan force row level security;
-- sin políticas: acceso solo vía service_role (panel super-admin)

alter table public.subscription enable row level security;
alter table public.subscription force row level security;
-- lectura de la propia suscripción (para mostrar vencimiento en la app)
create policy subscription_read_own on public.subscription
  for select using (company_id = public.current_company_id());
