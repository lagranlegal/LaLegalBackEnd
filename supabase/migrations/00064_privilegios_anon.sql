-- =====================================================================
-- 00064_privilegios_anon.sql — El rol `anon` no tiene privilegios en `public`.
--
-- Toda la app entra con sesión: el backend hace `SET LOCAL ROLE
-- authenticated` en cada transacción de tenant (core/db.py) y el front solo
-- usa Supabase Auth y Storage con sesión iniciada. Ningún camino legítimo
-- lee ni escribe `public` como `anon`, así que ese rol no conserva
-- privilegios de tabla, secuencia ni función en este esquema. 00011 se los
-- había dado junto con `authenticated`; `authenticated` y `service_role`
-- quedan exactamente como estaban.
--
-- `custom_access_token_hook` lo ejecuta SOLO Supabase Auth
-- (`supabase_auth_admin`); ningún rol de cliente lo necesita.
--
-- Aditiva: solo REVOKE/GRANT. No toca datos ni el esquema.
-- =====================================================================

-- Tablas, vistas y secuencias existentes.
revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;

-- Funciones: `anon` las recibía directo (00011/imagen de Supabase) y por
-- `PUBLIC` (el default de Postgres para funciones). Se quitan las dos vías y
-- se deja el grant explícito a los roles que sí las usan.
revoke execute on all functions in schema public from anon, public;
grant execute on all functions in schema public to authenticated, service_role;

-- Explícitas por nombre (00062 ya las había sacado de PUBLIC, no de anon).
revoke execute on function public.current_user_has_permission(text) from anon;
revoke execute on function public.current_user_is_active_member() from anon;
revoke execute on function public.storage_object_allowed(text, text, boolean) from anon;

-- El hook de claims: solo Supabase Auth.
revoke execute on function public.custom_access_token_hook(jsonb)
  from anon, authenticated, public;
grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;

-- Objetos futuros creados por las migraciones (dueño `postgres`): que no
-- vuelvan a nacer con privilegios para `anon` ni con EXECUTE para PUBLIC.
alter default privileges for role postgres in schema public
  revoke all on tables from anon;
alter default privileges for role postgres in schema public
  revoke all on sequences from anon;
alter default privileges for role postgres in schema public
  revoke all on functions from anon, public;
alter default privileges for role postgres in schema public
  grant execute on functions to authenticated, service_role;
