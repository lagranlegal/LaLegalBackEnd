-- =====================================================================
-- 00005_contracts.sql — Contratos de empeño, artículos en garantía,
-- abonos y contadores de consecutivos.
--
-- Reglas clave (ver CLAUDE.md):
--  * SNAPSHOT legal: tasa, plazo, ventana de mora y meses de prórroga se
--    copian al contrato AL CREARLO; cambios de config = solo contratos nuevos.
--  * Abonos: solo meses COMPLETOS de interés; capital solo con intereses
--    al día. Validado en el servicio; aquí quedan los datos y unicidades.
--  * Estados: active → in_arrears → in_extension → auctioned; paid cierra.
--    Nunca editables a mano (solo el servicio y la acción Rematar).
-- =====================================================================

create type contract_status as enum ('active', 'in_arrears', 'in_extension', 'auctioned', 'paid');
create type contract_item_status as enum ('in_custody', 'returned', 'auctioned');
create type payment_method as enum ('cash', 'transfer', 'other');

-- Contador genérico de consecutivos por empresa+prefijo.
-- Prefijos: 'CONTRACT', 'RECEIPT', 'SALE', 'INV_ENTRY', 'INV_EXIT'
-- y los prefijos de código de artículo ('JOC', 'JPA', ...).
create table public.code_counter (
  company_id  uuid not null references public.company(id),
  prefix      text not null,
  last_number int  not null default 0,
  primary key (company_id, prefix)
);

create or replace function public.next_counter(p_company uuid, p_prefix text)
returns int
language sql
as $$
  insert into public.code_counter (company_id, prefix, last_number)
  values (p_company, p_prefix, 1)
  on conflict (company_id, prefix)
  do update set last_number = public.code_counter.last_number + 1
  returning last_number;
$$;

create table public.contract (
  id                    uuid primary key default gen_random_uuid(),
  company_id            uuid not null references public.company(id),
  number                bigint not null,
  legacy_code           text,                       -- código del sistema antiguo (migrados), buscable
  customer_id           uuid not null references public.customer(id),
  principal             numeric(14,2) not null check (principal > 0),
  capital_balance       numeric(14,2) not null,
  appraisal_value       numeric(14,2),              -- tasación total, OPCIONAL
  interest_rate_pct     numeric(5,2) not null,      -- SNAPSHOT
  interest_type         text not null default 'simple_on_balance',
  term_months           int not null,               -- SNAPSHOT
  arrears_window_months int not null,               -- SNAPSHOT (metales 4, tecnología 1)
  extension_months      int not null default 1,     -- SNAPSHOT (mes final de prórroga)
  start_date            date not null default current_date,  -- manual en migrados
  due_date              date not null,
  interest_paid_until   date not null,              -- base del cálculo de months_owed
  status                contract_status not null default 'active',
  extension_ends_at     date,
  ltv_warning           boolean not null default false,
  notes                 text,
  signed_photo_url      text,                       -- foto del contrato impreso y firmado
  created_by            uuid,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (company_id, number)
);
create trigger trg_contract_updated before update on public.contract
  for each row execute function public.set_updated_at();
create index ix_contract_company_status on public.contract (company_id, status);
create index ix_contract_customer on public.contract (customer_id);
create index ix_contract_legacy on public.contract (company_id, legacy_code)
  where legacy_code is not null;

-- Prenda en garantía (≠ artículo de inventario).
-- inventory_item_id: SOLO se llena al rematar (trazabilidad bidireccional).
create table public.contract_item (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references public.company(id),
  contract_id       uuid not null references public.contract(id),
  category_id       uuid not null references public.category(id),  -- nivel 3
  description       text not null,
  weight_grams      numeric(10,2),   -- metales/joyería (base de tasación del oro)
  serial_imei       text,            -- tecnología
  item_appraisal    numeric(14,2),   -- tasación individual, OPCIONAL
  status            contract_item_status not null default 'in_custody',
  photos            jsonb not null default '[]',
  inventory_item_id uuid,            -- FK a inventory_item (se agrega en 00006)
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create trigger trg_contract_item_updated before update on public.contract_item
  for each row execute function public.set_updated_at();
create index ix_contract_item_contract on public.contract_item (contract_id);

-- Abono/pago. Validación de negocio en el servicio:
--   total = N meses COMPLETOS de interés (+ capital solo si N cubre todos
--   los adeudados). Parcial de interés → 422. Genera cash_movement en la
--   MISMA transacción (module = pawn).
create table public.contract_payment (
  id                      uuid primary key default gen_random_uuid(),
  company_id              uuid not null references public.company(id),
  contract_id             uuid not null references public.contract(id),
  receipt_number          bigint not null,
  paid_at                 timestamptz not null default now(),
  months_covered          int not null default 0,
  interest_amount         numeric(14,2) not null default 0,
  capital_amount          numeric(14,2) not null default 0,
  discount_amount         numeric(14,2) not null default 0,  -- SOLO permiso especial + motivo
  discount_reason         text,
  discount_by             uuid,
  payment_method          payment_method not null,
  total                   numeric(14,2) not null check (total > 0),
  new_capital_balance     numeric(14,2) not null,
  new_interest_paid_until date not null,
  idempotency_key         text not null,
  registered_by           uuid,
  created_at              timestamptz not null default now(),
  unique (company_id, receipt_number),
  unique (company_id, idempotency_key),
  check (discount_amount = 0 or discount_reason is not null)
);
create index ix_payment_contract on public.contract_payment (contract_id);

-- Los pagos son inmutables (correcciones = contra-asiento, nunca editar)
create trigger trg_payment_immutable
  before update or delete on public.contract_payment
  for each row execute function public.forbid_change();

-- RLS
alter table public.code_counter enable row level security;
alter table public.code_counter force row level security;
create policy tenant_isolation on public.code_counter
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

alter table public.contract enable row level security;
alter table public.contract force row level security;
create policy tenant_isolation on public.contract
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

alter table public.contract_item enable row level security;
alter table public.contract_item force row level security;
create policy tenant_isolation on public.contract_item
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

alter table public.contract_payment enable row level security;
alter table public.contract_payment force row level security;
create policy tenant_isolation on public.contract_payment
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());
