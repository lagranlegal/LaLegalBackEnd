-- =====================================================================
-- 00035_pay_purchase_permission.sql — pagarle a un proveedor no es
-- administrar el inventario.
--
-- EL PROBLEMA: saldar una compra pendiente
-- (`POST /inventory/entries/{id}/pay`) exigía `inventory.create` — el mismo
-- permiso que registra mercancía. O sea que quien maneja la bodega podía
-- además sacar plata de la caja para pagarle al proveedor.
--
-- Son dos hechos contables distintos y separados en el tiempo, y el sistema
-- ya los distingue por dentro (`entry_date` vs `paid_at`):
--
--   · la mercancía ENTRA  -> cambia el inventario. Lo hace bodega.
--   · la factura SE PAGA  -> cambia el efectivo y baja la deuda con el
--                            proveedor. El inventario no se mueve.
--                            Lo hace quien maneja la plata.
--
-- Es el mismo criterio que ya separó `accounts.settle` (00029) y
-- `accounts.transfer` (00032): una acción que MUEVE PLATA lleva su propio
-- permiso, aunque viva en la pantalla de otro módulo.
--
-- NADIE PIERDE LO QUE YA TENÍA, igual que en 00030 y 00031: el permiso se
-- otorga a todos los roles que hoy tienen `inventory.create`. Lo que se gana
-- no es restringir hoy, sino que el permiso EXISTA y se pueda quitar a
-- conciencia desde la matriz de roles.
-- =====================================================================

insert into public.permission (code, module, action, is_special, description) values
  ('inventory.pay_purchase', 'inventory', 'pay_purchase', true,
   'Pagar compras pendientes a proveedores (saca plata de la caja)')
on conflict (code) do nothing;

insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'inventory.pay_purchase')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'inventory.create'
on conflict do nothing;
