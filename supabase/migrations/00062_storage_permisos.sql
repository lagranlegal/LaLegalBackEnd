-- =====================================================================
-- 00062_storage_permisos.sql — Los archivos del bucket `company-files` se
-- leen y escriben con el MISMO permiso que la pantalla que los usa.
--
-- Auditoría del 27/09/2026, F3-03. La política de 00013 (`tenant_isolation`)
-- solo compara la carpeta de la empresa: cualquier usuario de la empresa, con
-- el permiso que fuera, podía leer, subir o borrar cualquier archivo de su
-- empresa (fotos de cédula de los clientes, contratos firmados, comprobantes
-- de gasto). El aislamiento ENTRE empresas sí funcionaba y se conserva.
--
-- Desde acá la subcarpeta decide el permiso. Las rutas las arma el front
-- como `{company_id}/{sección}/…` (`frontend-starter/src/lib/storage/
-- photos.ts`, `PhotoUploader` con su `folder`):
--
--   sección          leer                               escribir
--   ---------------  ---------------------------------  -------------------------------
--   customers        customers.view                     customers.create
--   contracts        contracts.view                     contracts.create | contracts.edit
--   contract-items   contracts.view | inventory.view    contracts.create | contracts.edit
--                    (las fotos de la prenda viajan al  | contracts.import
--                    inventario con el remate)
--   inventory        inventory.view                     inventory.create
--   expenses         cashbox.view                       cashbox.expense
--   company          cualquier usuario activo (el logo  company.configure
--                    y la firma salen en todo impreso)
--   perfil           cualquier usuario activo           cualquier usuario activo (su foto)
--   otra             nadie (deny-by-default, CLAUDE.md regla 3)
--
-- "Escribir" cubre INSERT, UPDATE y DELETE: borrar evidencia es tan sensible
-- como subirla. El backend usa la service_role, que no pasa por RLS.
--
-- Todo ADITIVO respecto al código desplegado: el backend no lee Storage, y el
-- front sigue armando las mismas rutas. Lo que cambia es quién recibe 403.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. ¿El usuario actual tiene este permiso?
--
-- Se resuelve por el `sub` del JWT contra `app_user`, dentro del
-- `company_id` del JWT — no por el `role_id` del token. El token vive hasta
-- una hora: con el claim, un usuario desactivado o al que le quitaron el rol
-- seguiría abriendo archivos hasta que venza. La fila es la verdad vigente,
-- igual que en `get_current_user` del backend.
--
-- SECURITY DEFINER porque quien pregunta (el rol `authenticated` desde el
-- gateway de Storage) no necesita poder leer `role_permission` para saber si
-- tiene un permiso; `search_path` fijo para que nadie le cambie las tablas
-- por debajo.
-- ---------------------------------------------------------------------
create or replace function public.current_user_has_permission(p_code text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.app_user u
    join public.role_permission rp on rp.role_id = u.role_id
    join public.permission p on p.id = rp.permission_id
    where u.id = public.current_user_id()
      and u.company_id = public.current_company_id()
      and u.status <> 'inactive'
      and p.code = p_code
  )
$$;

-- ¿Es un usuario vigente de la empresa del token? (para lo que no pide un
-- permiso concreto: el logo, la firma y la foto de perfil).
create or replace function public.current_user_is_active_member()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.app_user u
    where u.id = public.current_user_id()
      and u.company_id = public.current_company_id()
      and u.status <> 'inactive'
  )
$$;

-- ---------------------------------------------------------------------
-- 2. ¿Puede el usuario actual leer (p_write = false) o escribir (true) este
--    objeto? Un solo lugar con la tabla de arriba, para que las cuatro
--    políticas no la repitan.
-- ---------------------------------------------------------------------
create or replace function public.storage_object_allowed(
  p_bucket text, p_name text, p_write boolean
)
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  partes text[] := string_to_array(p_name, '/');
  seccion text;
begin
  if p_bucket is distinct from 'company-files' then
    return false;
  end if;
  -- `{company_id}/{sección}/{archivo}`: menos de tres partes no es una ruta
  -- que el front arme, y sin sección no hay permiso que aplicar.
  if coalesce(array_length(partes, 1), 0) < 3
     or partes[1] is distinct from public.current_company_id()::text then
    return false;
  end if;
  seccion := partes[2];

  if seccion = 'customers' then
    return public.current_user_has_permission(
      case when p_write then 'customers.create' else 'customers.view' end);
  elsif seccion = 'contracts' then
    if p_write then
      return public.current_user_has_permission('contracts.create')
          or public.current_user_has_permission('contracts.edit');
    end if;
    return public.current_user_has_permission('contracts.view');
  elsif seccion = 'contract-items' then
    if p_write then
      return public.current_user_has_permission('contracts.create')
          or public.current_user_has_permission('contracts.edit')
          or public.current_user_has_permission('contracts.import');
    end if;
    return public.current_user_has_permission('contracts.view')
        or public.current_user_has_permission('inventory.view');
  elsif seccion = 'inventory' then
    return public.current_user_has_permission(
      case when p_write then 'inventory.create' else 'inventory.view' end);
  elsif seccion = 'expenses' then
    return public.current_user_has_permission(
      case when p_write then 'cashbox.expense' else 'cashbox.view' end);
  elsif seccion = 'company' then
    if p_write then
      return public.current_user_has_permission('company.configure');
    end if;
    return public.current_user_is_active_member();
  elsif seccion = 'perfil' then
    return public.current_user_is_active_member();
  end if;
  return false;
end;
$$;

revoke all on function public.current_user_has_permission(text) from public;
revoke all on function public.current_user_is_active_member() from public;
revoke all on function public.storage_object_allowed(text, text, boolean) from public;
grant execute on function public.current_user_has_permission(text) to authenticated, service_role;
grant execute on function public.current_user_is_active_member() to authenticated, service_role;
grant execute on function public.storage_object_allowed(text, text, boolean)
  to authenticated, service_role;

-- ---------------------------------------------------------------------
-- 3. Las políticas. Misma guarda de entorno que 00013: `storage.objects` la
--    crea el servicio de Storage, no Postgres (CI y el local sin Storage no
--    la tienen). Las funciones de arriba se crean igual en todos lados, que
--    es lo que prueba `tests/rls/test_storage_permissions.py`.
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (
    select 1 from information_schema.tables
    where table_schema = 'storage' and table_name = 'objects'
  ) then
    raise notice 'storage.objects ausente (CI o local sin el servicio): se omiten las políticas.';
    return;
  end if;

  execute 'drop policy if exists tenant_isolation on storage.objects';
  execute 'drop policy if exists company_files_select on storage.objects';
  execute 'drop policy if exists company_files_insert on storage.objects';
  execute 'drop policy if exists company_files_update on storage.objects';
  execute 'drop policy if exists company_files_delete on storage.objects';

  execute $pol$
    create policy company_files_select on storage.objects for select
      using (public.storage_object_allowed(bucket_id, name, false))
  $pol$;
  execute $pol$
    create policy company_files_insert on storage.objects for insert
      with check (public.storage_object_allowed(bucket_id, name, true))
  $pol$;
  execute $pol$
    create policy company_files_update on storage.objects for update
      using (public.storage_object_allowed(bucket_id, name, true))
      with check (public.storage_object_allowed(bucket_id, name, true))
  $pol$;
  execute $pol$
    create policy company_files_delete on storage.objects for delete
      using (public.storage_object_allowed(bucket_id, name, true))
  $pol$;
end $$;
