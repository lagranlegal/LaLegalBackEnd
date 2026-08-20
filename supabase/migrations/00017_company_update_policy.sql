-- =====================================================================
-- 00017_company_update_policy.sql — La empresa puede editar su propia
-- configuración (`PATCH /api/v1/company/settings`, permiso
-- `company.configure`).
--
-- `public.company` tenía RLS habilitado y FORZADO con UNA sola política:
-- `company_read_own` (solo SELECT). Tenía sentido mientras la única forma de
-- modificar una empresa era el módulo `platform` (super-admin), que corre con
-- sesión de bypass sin RLS. Al abrir la configuración al propio tenant, el
-- UPDATE afectaba CERO filas — sin error, sin excepción, sin nada: RLS no
-- falla, simplemente no encuentra la fila. Encontrado con un test que
-- guardaba y volvía a leer, no por inspección del código: el endpoint
-- respondía 200 con los datos viejos.
--
-- La política restringe la FILA (solo la empresa propia). Postgres no permite
-- restringir COLUMNAS desde una policy, así que qué campos son editables lo
-- decide `company.repository.EDITABLE_COLUMNS` — una lista blanca explícita
-- que deja fuera `status` (suspender/activar una empresa es del super-admin,
-- nunca de la empresa sobre sí misma) y las marcas de tiempo. Hay un test de
-- integración que manda `{"status": "suspended"}` y verifica que la empresa
-- sigue `active`.
--
-- Mismo criterio que el resto del proyecto: los invariantes de negocio los
-- sostiene el servicio (el estado de un contrato, el stock, los consecutivos)
-- y RLS sostiene el aislamiento entre tenants. Acá pasa igual.
-- =====================================================================

create policy company_update_own on public.company
  for update
  using (id = public.current_company_id())
  with check (id = public.current_company_id());
