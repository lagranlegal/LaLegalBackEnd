-- =====================================================================
-- 00028_hook_allows_invited.sql — el hook también emite claims para
-- usuarios `invited`.
--
-- Arregla un bloqueo mutuo que impedía que CUALQUIER invitado entrara:
--
--   1. El hook solo emitía `company_id`/`role_id` si `status = 'active'`.
--   2. Un invitado que acaba de poner su contraseña tiene `status =
--      'invited'`, así que su JWT salía sin esos claims.
--   3. `get_verified_claims` rechaza con 401 todo token sin claims de
--      tenant, ANTES de llegar a `get_current_user`.
--   4. Y `get_current_user` era justamente el único lugar que pasaba al
--      usuario de `invited` a `active`.
--
-- Resultado: la auto-activación era código inalcanzable exactamente para el
-- caso que fue escrito, y el invitado veía "Tu usuario o tu empresa están
-- inactivos" — un mensaje que además apunta al lugar equivocado. No se
-- detectó antes porque los usuarios de prueba se habían activado a mano
-- durante el desarrollo, así que nunca se recorrió el flujo completo.
--
-- Por qué es seguro emitir claims para `invited`:
--
--   · `invited` no significa "no autorizado": significa "el admin ya lo dio
--     de alta y todavía no ha entrado por primera vez". El derecho de
--     acceso ya se lo concedió su empresa.
--   · Para tener un JWT válido en la mano ya completó el flujo de
--     invitación de Supabase (puso contraseña o usó Google), lo cual prueba
--     que controla ese correo. Sin eso no hay token que presentar.
--   · El estado que SÍ importa para seguridad es `inactive` — un usuario
--     desactivado por el admin —, y ese sigue quedando fuera: la condición
--     enumera los estados permitidos en vez de negar uno solo, así que
--     cualquier estado nuevo nace excluido.
--
-- La empresa sigue teniendo que estar `active`: suspenderla corta el acceso
-- de todos sus usuarios, invitados incluidos.
-- =====================================================================

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

  -- `in ('active', 'invited')` y no `<> 'inactive'`: enumerar lo permitido
  -- hace que un estado futuro quede excluido por defecto.
  if found and v_user.status in ('active', 'invited')
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
