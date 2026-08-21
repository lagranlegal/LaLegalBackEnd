-- =====================================================================
-- 00030_view_permissions.sql — leer deja de exigir permiso de escritura.
--
-- Auditoría del catálogo completo tras el reporte de que el módulo de
-- contratos no era parametrizable. Contratos resultó estar BIEN por el lado
-- del backend (view/create/edit/auction/import, cada endpoint con el suyo);
-- el hueco estaba en el front. Pero la revisión destapó dos módulos donde
-- LEER exige un permiso de escritura, y uno donde no exige nada:
--
--   · `sales` no tiene `sales.view`: listar ventas exige `sales.create`. O
--     sea que no se puede tener a alguien que REVISE las ventas sin dejarlo
--     además registrarlas. Es el error inverso al de `accounts.settle`
--     (00029): allá una escritura colgaba de un permiso de lectura, acá una
--     lectura cuelga de uno de escritura.
--
--   · `catalogs` no tiene `catalogs.view`, y peor: sus cuatro endpoints de
--     lectura no exigían NINGÚN permiso (`Depends(get_current_user)` pelado).
--     Viola la regla 3 de CLAUDE.md — "endpoint sin permiso explícito = error
--     de revisión" — y hacía que las categorías y los proveedores fueran
--     legibles por cualquier usuario autenticado de la empresa.
--
-- Un módulo donde leer obliga a poder escribir no es parametrizable: el admin
-- no puede construir un rol de consulta.
-- =====================================================================

insert into public.permission (code, module, action, is_special, description) values
  ('sales.view',    'sales',    'view', false, 'Ver ventas y su detalle'),
  ('catalogs.view', 'catalogs', 'view', false, 'Ver categorías y proveedores')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------
-- Nadie pierde lo que ya tenía.
-- ---------------------------------------------------------------------

-- Quien podía registrar ventas ya las veía.
insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'sales.view')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'sales.create'
on conflict do nothing;

-- `catalogs.view` va a TODOS los roles existentes, sin condición, y es a
-- propósito: hasta ahora esos endpoints no pedían permiso, así que cualquier
-- usuario autenticado los leía. Otorgarlo solo a algunos sería quitarle el
-- acceso al resto — y romper de paso a cualquier asesor, que necesita leer
-- las categorías para poder crear un contrato.
--
-- Lo que se gana no es restringir hoy, sino que a partir de ahora el permiso
-- EXISTA y se pueda quitar a conciencia desde la matriz.
insert into public.role_permission (role_id, permission_id)
select r.id, (select id from public.permission where code = 'catalogs.view')
from public.role r
on conflict do nothing;
