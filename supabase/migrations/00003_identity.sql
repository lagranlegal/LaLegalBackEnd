-- =====================================================================
-- 00003_identity.sql — Usuarios, roles y permisos (RBAC dinámico)
-- permission es catálogo GLOBAL (seed). role es por empresa.
-- app_user.id == auth.users.id (perfil 1:1 con Supabase Auth).
-- =====================================================================

create type user_status as enum ('invited', 'active', 'inactive');

create table public.permission (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique,       -- 'contracts.create', 'cashbox.open_close'...
  module      text not null,
  action      text not null,
  is_special  boolean not null default false,
  description text
);

create table public.role (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references public.company(id),
  name        text not null,
  description text,
  is_seed     boolean not null default false,  -- Admin/Moderador/Asesor/Bodega: clonables, NO eliminables
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (company_id, name)
);
create trigger trg_role_updated before update on public.role
  for each row execute function public.set_updated_at();

create table public.role_permission (
  role_id       uuid not null references public.role(id) on delete cascade,
  permission_id uuid not null references public.permission(id),
  primary key (role_id, permission_id)
);

create table public.app_user (
  id            uuid primary key,               -- = auth.users.id
  company_id    uuid not null references public.company(id),
  role_id       uuid not null references public.role(id),
  full_name     text not null,
  email         text not null,
  photo_url     text,
  status        user_status not null default 'invited',
  last_login_at timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (company_id, email)
);
create trigger trg_app_user_updated before update on public.app_user
  for each row execute function public.set_updated_at();
create index ix_app_user_company on public.app_user (company_id);

-- ---------------------------------------------------------------------
-- Custom Access Token Hook: inyecta company_id y role_id en el JWT.
-- Registrar en Dashboard/config: Auth > Hooks > Custom Access Token.
-- Si la empresa está suspendida o el usuario inactivo, NO emite claims
-- de tenant (el backend rechazará el token).
-- ---------------------------------------------------------------------
create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql stable
security definer
set search_path = public
as $$
declare
  v_user   public.app_user%rowtype;
  v_claims jsonb;
begin
  select * into v_user from public.app_user where id = (event->>'user_id')::uuid;
  v_claims := coalesce(event->'claims', '{}'::jsonb);

  if found and v_user.status = 'active'
     and exists (select 1 from public.company c
                 where c.id = v_user.company_id and c.status = 'active') then
    v_claims := v_claims
      || jsonb_build_object('company_id', v_user.company_id::text,
                            'role_id',   v_user.role_id::text);
  end if;

  return jsonb_set(event, '{claims}', v_claims);
end;
$$;
grant execute on function public.custom_access_token_hook to supabase_auth_admin;

-- ---------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------
alter table public.permission enable row level security;
alter table public.permission force row level security;
create policy permission_read_all on public.permission
  for select using (public.current_company_id() is not null);  -- catálogo visible a autenticados

alter table public.role enable row level security;
alter table public.role force row level security;
create policy tenant_isolation on public.role
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

alter table public.role_permission enable row level security;
alter table public.role_permission force row level security;
create policy tenant_isolation on public.role_permission
  using (exists (select 1 from public.role r
                 where r.id = role_id
                   and r.company_id = public.current_company_id()))
  with check (exists (select 1 from public.role r
                      where r.id = role_id
                        and r.company_id = public.current_company_id()));

alter table public.app_user enable row level security;
alter table public.app_user force row level security;
create policy tenant_isolation on public.app_user
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

-- NOTA (salvaguardas en el servicio, no en SQL):
--  * siempre >= 1 admin activo por empresa
--  * un admin no puede quitarse identity.manage_roles ni auto-inactivarse
--    siendo el último admin
