-- =====================================================================
-- 00008_audit.sql — Auditoría inmutable.
-- Los servicios insertan en la MISMA transacción de cada acción sensible:
-- descuentos, remates, anulaciones, egresos, cierres/reaperturas de caja,
-- cambios de roles/permisos, extensiones de suscripción.
-- RLS: solo INSERT y SELECT. Sin políticas de UPDATE/DELETE + trigger de
-- bloqueo = inmutable por diseño.
-- =====================================================================

create table public.audit_log (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null,
  user_id     uuid,
  module      text not null,
  action      text not null,
  entity_type text not null,
  entity_id   uuid,
  before      jsonb,
  after       jsonb,
  ip          inet,
  created_at  timestamptz not null default now()
);
create index ix_audit_company_date on public.audit_log (company_id, created_at desc);
create index ix_audit_entity on public.audit_log (entity_type, entity_id);

create trigger trg_audit_immutable
  before update or delete on public.audit_log
  for each row execute function public.forbid_change();

alter table public.audit_log enable row level security;
alter table public.audit_log force row level security;

create policy audit_insert on public.audit_log
  for insert with check (company_id = public.current_company_id());

create policy audit_select on public.audit_log
  for select using (company_id = public.current_company_id());
-- La restricción de "solo admin ve auditoría" se aplica por permiso
-- (audit.view) en el backend; RLS garantiza el aislamiento de tenant.
