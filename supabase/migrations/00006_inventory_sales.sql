-- =====================================================================
-- 00006_inventory_sales.sql — Inventario (tienda) y ventas.
--
-- Reglas clave:
--  * Código: [cat1][cat2][cat3][0001][letra proveedor | 'R' remate].
--    Se emite AL PUBLICAR (draft → available) con next_counter() y es
--    INMUTABLE. Código ≠ id técnico.
--  * Costos por identificación específica: cada pieza/lote con su costo
--    real; accesorios por lote (FIFO). Nunca promediar.
--  * Stock: solo cambia por ingreso/egreso/venta (servicio en transacción).
--  * Remate asistido: la acción Rematar crea el item en 'draft' con
--    origin='auction' y cost = capital + intereses pendientes.
-- =====================================================================

create type item_origin as enum ('supplier', 'auction', 'other');
create type item_status as enum ('draft', 'available', 'reserved', 'sold', 'written_off');
create type entry_origin as enum ('purchase', 'auction', 'other');
create type exit_type as enum ('adjustment', 'damage', 'supplier_return', 'internal_use');
create type sale_status as enum ('completed', 'voided');

create table public.inventory_item (
  id                 uuid primary key default gen_random_uuid(),
  company_id         uuid not null references public.company(id),
  code               text,                        -- JOC0001I / JOC0001R; null hasta publicar
  name               text not null,
  cat1_id            uuid not null references public.category(id),
  cat2_id            uuid not null references public.category(id),
  cat3_id            uuid not null references public.category(id),
  description        text,
  origin             item_origin not null,
  supplier_id        uuid references public.supplier(id),
  source_contract_id uuid references public.contract(id),   -- solo origin='auction'
  cost               numeric(14,2) not null check (cost >= 0),
  sale_price         numeric(14,2),
  quantity           int not null default 1 check (quantity >= 0),
  status             item_status not null default 'draft',
  photos             jsonb not null default '[]',
  entry_date         date not null default current_date,
  created_by         uuid,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  check (origin <> 'supplier' or supplier_id is not null),
  check (origin <> 'auction'  or source_contract_id is not null)
);
create trigger trg_inventory_item_updated before update on public.inventory_item
  for each row execute function public.set_updated_at();
create unique index uq_inventory_code on public.inventory_item (company_id, code)
  where code is not null;
create index ix_item_company_status on public.inventory_item (company_id, status);
create index ix_item_cats on public.inventory_item (cat1_id, cat2_id, cat3_id);

-- FK diferida desde contract_item (creada aquí porque inventory_item no existía en 00005)
alter table public.contract_item
  add constraint fk_contract_item_inventory
  foreign key (inventory_item_id) references public.inventory_item(id);

create table public.inventory_entry (
  id               uuid primary key default gen_random_uuid(),
  company_id       uuid not null references public.company(id),
  number           bigint not null,
  origin_type      entry_origin not null,
  supplier_id      uuid references public.supplier(id),
  supplier_invoice text,
  contract_id      uuid references public.contract(id),  -- solo origin='auction'
  total_cost       numeric(14,2) not null default 0,
  notes            text,
  registered_by    uuid,
  created_at       timestamptz not null default now(),
  unique (company_id, number)
);

create table public.inventory_entry_line (
  id        uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.company(id),
  entry_id  uuid not null references public.inventory_entry(id) on delete cascade,
  item_id   uuid not null references public.inventory_item(id),
  quantity  int not null check (quantity > 0),
  unit_cost numeric(14,2) not null check (unit_cost >= 0)
);
create index ix_entry_line_entry on public.inventory_entry_line (entry_id);

-- DECIDIDO: sin aprobación adicional — basta el permiso del rol
-- (inventory.exit); queda registro completo de quién y qué (auditoría).
create table public.inventory_exit (
  id            uuid primary key default gen_random_uuid(),
  company_id    uuid not null references public.company(id),
  number        bigint not null,
  exit_type     exit_type not null,
  reason        text not null,
  registered_by uuid,
  created_at    timestamptz not null default now(),
  unique (company_id, number)
);

create table public.inventory_exit_line (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.company(id),
  exit_id    uuid not null references public.inventory_exit(id) on delete cascade,
  item_id    uuid not null references public.inventory_item(id),
  quantity   int not null check (quantity > 0)
);

create table public.sale (
  id              uuid primary key default gen_random_uuid(),
  company_id      uuid not null references public.company(id),
  number          bigint not null,
  sold_at         timestamptz not null default now(),
  customer_id     uuid references public.customer(id),   -- opcional (mostrador)
  sold_by         uuid,
  discount_amount numeric(14,2) not null default 0,      -- permiso especial
  discount_by     uuid,
  total           numeric(14,2) not null check (total >= 0),
  payment_method  payment_method not null,
  status          sale_status not null default 'completed',
  void_reason     text,
  voided_by       uuid,
  idempotency_key text not null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (company_id, number),
  unique (company_id, idempotency_key),
  check (status <> 'voided' or void_reason is not null)
);
create trigger trg_sale_updated before update on public.sale
  for each row execute function public.set_updated_at();

create table public.sale_line (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.company(id),
  sale_id    uuid not null references public.sale(id) on delete cascade,
  item_id    uuid not null references public.inventory_item(id),
  quantity   int not null check (quantity > 0),
  unit_price numeric(14,2) not null check (unit_price >= 0),
  subtotal   numeric(14,2) not null
);
create index ix_sale_line_sale on public.sale_line (sale_id);

-- RLS (patrón de tenant en todas)
do $$
declare t text;
begin
  foreach t in array array['inventory_item','inventory_entry','inventory_entry_line',
                           'inventory_exit','inventory_exit_line','sale','sale_line']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format(
      'create policy tenant_isolation on public.%I
         using (company_id = public.current_company_id())
         with check (company_id = public.current_company_id())', t);
  end loop;
end $$;
