-- =====================================================================
-- 00029_accounts_permissions.sql — el módulo de cuentas tiene sus propios
-- permisos.
--
-- Las cuentas (00024–00027) se construyeron reusando permisos de otros
-- módulos: `cashbox.view` para leer y `company.configure` para administrar.
-- Funciona, pero está mal por tres razones:
--
--   1. NO ES PARAMETRIZABLE. Un admin no puede darle acceso a las cuentas a
--      alguien sin darle además toda la caja, ni dejarlo administrarlas sin
--      darle también el logo, la firma y los textos de los documentos. La
--      matriz de permisos deja de describir lo que la app hace realmente.
--
--   2. LIQUIDAR UN CONVENIO ESTABA DETRÁS DE UN PERMISO DE LECTURA.
--      `POST /accounts/{id}/settle` mueve plata entre cuentas y generaba dos
--      movimientos, pero exigía `cashbox.view` — o sea que cualquiera que
--      pudiera MIRAR la caja podía liquidar Sistecrédito. Es el agujero real
--      que destapó esta revisión.
--
--   3. Un módulo que no aparece en la matriz es invisible para quien
--      configura los roles: no puede otorgarlo ni quitarlo a conciencia.
--
-- Los tres permisos nuevos siguen la separación que ya usa el resto del
-- catálogo: ver / administrar / la acción sensible aparte (`is_special`,
-- igual que `cashbox.reopen` o `contracts.auction`).
-- =====================================================================

insert into public.permission (code, module, action, is_special, description) values
  ('accounts.view',   'accounts', 'view',   false, 'Ver cuentas y sus saldos'),
  ('accounts.manage', 'accounts', 'manage', false, 'Crear y editar cuentas'),
  ('accounts.settle', 'accounts', 'settle', true,  'Liquidar cuentas por cobrar (Sistecrédito)')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------
-- Nadie pierde lo que ya tenía.
--
-- Los roles existentes se configuraron cuando las cuentas usaban permisos
-- prestados. Si solo se agregaran los permisos nuevos, todos esos roles
-- perderían el acceso de un día para otro sin que nadie tocara nada — el
-- clásico deploy que "rompe" sin haber cambiado ninguna regla de negocio.
-- ---------------------------------------------------------------------

-- Quien podía VER la caja, podía ver las cuentas.
insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'accounts.view')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'cashbox.view'
on conflict do nothing;

-- Quien podía configurar la empresa, podía administrar las cuentas.
insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'accounts.manage')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'company.configure'
on conflict do nothing;

-- `accounts.settle` es la ÚNICA excepción deliberada a "nadie pierde nada":
-- se otorga a quien tiene `cashbox.open_close` (el permiso de responsable de
-- caja), NO a quien tiene `cashbox.view`. Conservar el mapeo anterior sería
-- conservar el agujero: liquidar mueve plata y no puede quedar al alcance de
-- todo el que solo mira. Un Admin lo tiene igual, porque tiene todo.
insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'accounts.settle')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'cashbox.open_close'
on conflict do nothing;
