-- =====================================================================
-- 00011_grants.sql — Faltan los GRANT base a anon/authenticated/service_role.
--
-- Bug real encontrado probando GET /me contra el proyecto Supabase
-- hospedado de dev (driyubkodnsqxbtxcmaz): `apply_tenant_claims`
-- (core/db.py) hace `SET LOCAL ROLE authenticated` en cada transacción de
-- tenant para que RLS se evalúe de verdad (00001-00010 ya la habilitan y
-- fuerzan tabla por tabla). Pero RLS solo restringe FILAS — Postgres exige
-- el privilegio de TABLA primero, y ninguna migración lo otorgó nunca.
-- `information_schema.role_table_grants` confirmó CERO privilegios
-- SELECT/INSERT/UPDATE/DELETE en TODAS las tablas de `public` para los
-- tres roles. Un proyecto Supabase local (`supabase start`) trae estos
-- GRANT precargados en la imagen de Postgres; un proyecto hospedado nuevo
-- no — hay que declararlos acá para que dev/staging/prod queden iguales.
-- Sin esto, TODO endpoint que pase por `get_tenant_db` (prácticamente toda
-- la app fuera de `platform`) falla con "permission denied for table X"
-- antes de llegar a evaluar ninguna policy.
-- =====================================================================

grant usage on schema public to anon, authenticated, service_role;

grant select, insert, update, delete on all tables in schema public
  to anon, authenticated, service_role;

grant usage, select on all sequences in schema public
  to anon, authenticated, service_role;

-- Para que las tablas de futuras migraciones hereden lo mismo sin volver a
-- acordarnos de este paso.
alter default privileges in schema public
  grant select, insert, update, delete on tables to anon, authenticated, service_role;

alter default privileges in schema public
  grant usage, select on sequences to anon, authenticated, service_role;
