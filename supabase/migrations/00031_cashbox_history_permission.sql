-- =====================================================================
-- 00031_cashbox_history_permission.sql — separar "ver la caja de hoy" de
-- "ver todo el histórico de cierres".
--
-- EL CASO: quien maneja la caja necesita ver SU turno —el de hoy— para
-- operar y para cerrarlo. No necesita, y muchas veces no debe, ver cuánto
-- se movió el mes pasado, cuánto vendió el negocio ni qué descuadres hubo
-- en turnos ajenos. Hoy `cashbox.view` abre las dos cosas: la sesión
-- actual y el listado completo de sesiones con el reporte de cualquiera.
-- No hay forma de dar "solo el día de hoy".
--
-- LA PARTICIÓN:
--
--   cashbox.view          la sesión ABIERTA / la de hoy, sus movimientos,
--                         su reporte. Lo que hace falta para trabajar y
--                         para cuadrar el cajón esta noche.
--   cashbox.view_history  el listado de sesiones y el reporte de
--                         cualquier sesión que no sea la de hoy.
--
-- LA TRAMPA QUE ESTO TIENE QUE CERRAR: `GET /reports/closings` expone
-- exactamente el mismo dato (el histórico de cierres) desde el módulo de
-- reportes, y solo pedía `reports.view`. Quitarle el histórico al cajero
-- por un lado y dejárselo por el otro sería teatro, así que ese endpoint
-- exige ahora los DOS permisos. Es el mismo criterio de 00030: un módulo
-- donde el control se puede rodear por otra puerta no es parametrizable.
--
-- NADIE PIERDE LO QUE YA TENÍA, igual que con `catalogs.view` en 00030: el
-- permiso se otorga a todos los roles que hoy tienen `cashbox.view`. Lo que
-- se gana no es restringir hoy, sino que el permiso EXISTA y se pueda
-- quitar a conciencia desde la matriz de roles.
-- =====================================================================

insert into public.permission (code, module, action, is_special, description) values
  ('cashbox.view_history', 'cashbox', 'view_history', false,
   'Ver el histórico de cierres de caja (turnos de días anteriores)')
on conflict (code) do nothing;

insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'cashbox.view_history')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'cashbox.view'
on conflict do nothing;
