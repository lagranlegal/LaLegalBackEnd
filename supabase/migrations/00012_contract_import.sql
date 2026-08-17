-- =====================================================================
-- 00012_contract_import.sql — Import de contratos pre-existentes
-- (docs/MIGRACION_CONTRATOS.md): especificación aprobada, quedó pendiente
-- desde el paso 5. Backend expuesto en POST /api/v1/contracts/import.
--
-- Se migra la foto financiera al corte, no la historia: el body trae
-- hechos del sistema viejo (legacy_code, capital_balance,
-- interest_paid_until, snapshot de tasa/plazo/ventana/prórroga); todo lo
-- derivable (número, due_date, estado) lo calcula el backend con la lógica
-- que ya existe. No requiere sesión de caja ni genera cash_movement: el
-- desembolso ya ocurrió en el sistema anterior.
-- =====================================================================

-- El índice parcial no bastaba: dos contratos con el mismo legacy_code en
-- la misma empresa deben ser imposibles a nivel de esquema, no solo
-- detectados por el servicio.
drop index if exists ix_contract_legacy;
create unique index ux_contract_legacy on public.contract (company_id, legacy_code)
  where legacy_code is not null;

insert into public.permission (code, module, action, is_special, description) values
  ('contracts.import', 'contracts', 'import', true,
   'Importar contratos del sistema anterior (sin caja, sin cash_movement)')
on conflict (code) do nothing;

-- Empresas ya existentes no pasan de nuevo por
-- platform.service.build_seed_role_permissions (eso solo corre al crear una
-- empresa) — hay que otorgar el permiso nuevo a mano a sus roles Admin
-- semilla para que quede igual que en una empresa creada de ahora en más.
insert into public.role_permission (role_id, permission_id)
select r.id, p.id
from public.role r
cross join public.permission p
where r.name = 'Admin' and r.is_seed = true and p.code = 'contracts.import'
on conflict do nothing;
