-- =====================================================================
-- 00045_return_time_limit_permission.sql — saltar el plazo de devolución.
--
-- `company.settings.return_window_days` es un plazo que ADVIERTE, no
-- bloquea duro (decisión de negocio: no hay un plazo legal fijo en
-- Colombia para devoluciones en tienda física que justifique un bloqueo
-- absoluto). Pasado el plazo, la devolución se rechaza salvo que quien la
-- registra tenga este permiso — misma idea que una excepción a una
-- política de negocio, no una operación rutinaria.
--
-- Se otorga a quien ya puede aplicar un descuento (`sales.apply_discount`):
-- ambas son la misma clase de decisión, saltarse una regla comercial por
-- un caso puntual.
-- =====================================================================

insert into public.permission (code, module, action, is_special, description) values
  ('sales.return_override_time_limit', 'sales', 'return_override_time_limit', true,
   'Registrar una devolución fuera del plazo configurado por la empresa')
on conflict (code) do nothing;

insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'sales.return_override_time_limit')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'sales.apply_discount'
on conflict do nothing;
