-- =====================================================================
-- 00010_plan_read_policy.sql — Falta un SELECT policy en `public.plan`.
--
-- Bug real encontrado implementando GET /me: 00002_platform.sql habilita
-- y FUERZA RLS en `plan` (`force row level security`) pero nunca crea una
-- policy, a diferencia de `permission` en 00003 (que sí tiene
-- `permission_read_all`) — mismo catálogo global, mismo patrón, un caso
-- se armó bien y el otro se quedó a medias. Con FORCE ROW LEVEL SECURITY
-- y cero policies, Postgres deniega TODO select por defecto — nunca se
-- notó porque cada lectura de `plan` hasta ahora pasaba por la sesión de
-- bypass (`get_db`, service-role, siempre superusuario → ignora RLS).
-- La primera lectura de `plan` desde una sesión tenant-scoped
-- (`get_tenant_db`, rol `authenticated`) — el JOIN de `GET /me` con la
-- suscripción activa — devolvía 0 filas en silencio.
-- =====================================================================

create policy plan_read_all on public.plan
  for select using (public.current_company_id() is not null);  -- catálogo visible a autenticados
