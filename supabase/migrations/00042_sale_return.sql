-- =====================================================================
-- 00042_sale_return.sql — el documento de la devolución.
--
-- Es a `sale` lo que `inventory_transformation` es a un ingreso/egreso: un
-- documento propio que referencia la venta original y, línea por línea,
-- cuánto se devuelve de cada una. Soporta devolución PARCIAL (una o varias
-- líneas, cantidad parcial de una línea) — a propósito distinto de
-- `sales.void_sale`, que es todo-o-nada porque asume "esto no debió pasar".
-- Una devolución asume lo contrario: la venta fue real, y ahora una parte
-- vuelve.
--
-- `settlement_method`: efectivo (mueve caja) o nota crédito (no mueve caja
-- al emitirse — la tabla vive en 00043). `customer_id` es obligatorio SOLO
-- si es nota crédito (el CHECK lo hace cumplir): una nota no redimible sin
-- saber a quién pertenece no sirve de nada. Con efectivo puede ser anónima,
-- igual que la venta original puede serlo.
--
-- Inmutable como todo documento que mueve stock o plata (mismo criterio que
-- `inventory_transformation`, `sale`, `contract_payment`): corregir una
-- devolución mal hecha es registrar otra, no editar la que ya pasó.
-- =====================================================================

create table public.sale_return (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references public.company(id),
  number            bigint not null,
  sale_id           uuid not null references public.sale(id),
  -- Obligatorio solo si settlement_method='credit_note' (ver CHECK abajo).
  -- Si la venta original tenía cliente, se hereda; si no, hay que
  -- identificarlo en este mismo momento para poder redimir la nota después.
  customer_id       uuid references public.customer(id),
  reason            return_reason not null,
  settlement_method return_settlement_method not null,
  notes             text,
  return_date       date not null default current_date,
  created_by        uuid,
  created_at        timestamptz not null default now(),
  idempotency_key   text,
  unique (company_id, number),
  unique (company_id, idempotency_key),
  check (settlement_method <> 'credit_note' or customer_id is not null)
);

create index ix_sale_return_company on public.sale_return (company_id, return_date);
create index ix_sale_return_sale on public.sale_return (company_id, sale_id);

alter table public.sale_return enable row level security;
alter table public.sale_return force row level security;
create policy tenant_isolation on public.sale_return
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

create trigger trg_sale_return_immutable
  before update or delete on public.sale_return
  for each row execute function public.forbid_change();

-- ---------------------------------------------------------------------
-- Línea de devolución: cuánto de cuál línea de venta.
--
-- `item_id` es el lote que RECIBE la cantidad devuelta: el mismo lote
-- reabierto si seguía intacto, o un lote nuevo si ya no lo estaba (el
-- servicio decide cuál de los dos caso por caso — ver 00044). NULL si
-- `restock=false`: una devolución puede ser puramente financiera, sin que
-- la mercancía vuelva a inventario (la pieza se perdió, se dañó más allá de
-- uso, o el negocio simplemente decide no reingresarla).
--
-- `unit_cost` se hereda de `sale_line.unit_cost` — el costo ya congelado al
-- vender, un hecho histórico que nunca se recalcula (mismo principio que
-- usa `sale_line` desde el día uno).
-- ---------------------------------------------------------------------

create table public.sale_return_line (
  id           uuid primary key default gen_random_uuid(),
  company_id   uuid not null references public.company(id),
  return_id    uuid not null references public.sale_return(id) on delete cascade,
  sale_line_id uuid not null references public.sale_line(id),
  item_id      uuid references public.inventory_item(id),
  quantity     numeric(14,3) not null check (quantity > 0),
  unit_cost    numeric(14,2) not null check (unit_cost >= 0),
  restock      boolean not null default true,
  created_at   timestamptz not null default now()
);

create index ix_sale_return_line_return on public.sale_return_line (return_id);
create index ix_sale_return_line_sale_line
  on public.sale_return_line (company_id, sale_line_id);

alter table public.sale_return_line enable row level security;
alter table public.sale_return_line force row level security;
create policy tenant_isolation on public.sale_return_line
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

-- ---------------------------------------------------------------------
-- Permiso propio. MUEVE DINERO y REVERSA STOCK a la vez — mismo criterio
-- que separó `inventory.transform` de `inventory.exit` en 00037.
--
-- Se otorga a quien ya tiene `sales.void`: es el mismo nivel de confianza,
-- revertir (parcialmente) una venta ya hecha.
-- ---------------------------------------------------------------------

insert into public.permission (code, module, action, is_special, description) values
  ('sales.return', 'sales', 'return', true,
   'Registrar devolución de cliente (efectivo o nota crédito, con o sin reingreso de stock)')
on conflict (code) do nothing;

insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'sales.return')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'sales.void'
on conflict do nothing;
