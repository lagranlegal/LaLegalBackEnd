-- =====================================================================
-- seed.sql — Datos semilla GLOBALES (se aplican con `supabase db reset`).
-- 1) Catálogo de permisos (módulo.acción + especiales).
-- 2) Planes.
-- Los datos POR EMPRESA (roles semilla, caja principal, categorías demo)
-- los crea el servicio de plataforma al dar de alta cada empresa
-- (platform/service.py: create_company_defaults).
-- =====================================================================

insert into public.permission (code, module, action, is_special, description) values
  -- Contratos
  ('contracts.view',    'contracts', 'view',    false, 'Ver contratos y su detalle'),
  ('contracts.create',  'contracts', 'create',  false, 'Crear contratos de empeño'),
  ('contracts.edit',    'contracts', 'edit',    false, 'Editar datos no sensibles del contrato'),
  ('contracts.auction', 'contracts', 'auction', true,  'Rematar contrato (crea artículo en inventario)'),
  ('contracts.import',  'contracts', 'import',  true,  'Importar contratos del sistema anterior (sin caja, sin cash_movement)'),
  -- Abonos
  ('payments.create',         'payments', 'create',   false, 'Registrar abonos y pagos'),
  ('payments.apply_discount', 'payments', 'discount', true,  'Aplicar descuento sobre intereses'),
  -- Clientes
  ('customers.view',   'customers', 'view',   false, 'Ver clientes e historial cruzado'),
  ('customers.create', 'customers', 'create', false, 'Crear y editar clientes'),
  -- Catálogos
  ('catalogs.manage', 'catalogs', 'manage', false, 'Gestionar categorías y proveedores'),
  -- Inventario
  ('inventory.view',   'inventory', 'view',   false, 'Ver artículos y stock'),
  ('inventory.create', 'inventory', 'create', false, 'Crear artículos e ingresos de mercancía'),
  ('inventory.exit',   'inventory', 'exit',   true,  'Egresos de inventario (ajuste, daño, devolución)'),
  -- Ventas
  ('sales.create',         'sales', 'create',   false, 'Registrar ventas'),
  ('sales.void',           'sales', 'void',     true,  'Anular venta (repone stock)'),
  ('sales.apply_discount', 'sales', 'discount', true,  'Aplicar descuento en venta'),
  -- Caja
  ('cashbox.view',       'cashbox', 'view',    false, 'Ver movimientos del día'),
  ('cashbox.open_close', 'cashbox', 'session', true,  'Abrir y cerrar la caja diaria'),
  ('cashbox.reopen',     'cashbox', 'reopen',  true,  'Reabrir un cierre (excepcional, auditado)'),
  ('cashbox.expense',    'cashbox', 'expense', false, 'Registrar gastos'),
  -- Usuarios y roles
  ('identity.manage_users', 'identity', 'users', false, 'Invitar, editar e inactivar usuarios'),
  ('identity.manage_roles', 'identity', 'roles', true,  'Crear roles y editar permisos'),
  -- Reportes / auditoría / configuración
  ('reports.view',   'reports', 'view',   false, 'Dashboard y reportes'),
  ('audit.view',     'audit',   'view',   false, 'Consultar auditoría'),
  ('company.configure', 'company', 'configure', false, 'Configurar empresa (logo, firma, parámetros)')
on conflict (code) do nothing;

insert into public.plan (name, code, price, modules, active) values
  ('Solo Empeño', 'pawn_only',  null, '{"pawn":true,"store":false}', true),
  ('Solo Tienda', 'store_only', null, '{"pawn":false,"store":true}', true),
  ('Completo',    'full',       null, '{"pawn":true,"store":true}',  true)
on conflict (code) do nothing;

-- =====================================================================
-- Matriz inicial de roles semilla (referencia para create_company_defaults;
-- el admin de cada empresa puede modificarla en cualquier momento):
--   Admin:      TODOS los permisos.
--   Moderador:  todos MENOS inventory.create, inventory.exit,
--               identity.manage_users, identity.manage_roles,
--               cashbox.open_close, cashbox.reopen, payments.apply_discount,
--               sales.apply_discount, audit.view, company.configure,
--               contracts.import.
--   Asesor:     contracts.view/create, payments.create, customers.*,
--               inventory.view, sales.create, cashbox.view.
--   Bodega:     inventory.view/create, catalogs.manage (proveedores),
--               customers.view.
-- =====================================================================
