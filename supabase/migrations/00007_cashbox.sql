-- =====================================================================
-- 00007_cashbox.sql — Caja: sesiones, movimientos y gastos.
--
-- DECIDIDO: acto ÚNICO diario de apertura/cierre, base ÚNICA de efectivo,
-- desglose CONTABLE por módulo (pawn/store/general) en el acta.
-- Sin tolerancia de diferencias: todo descuadre exige justificación.
-- El modelo conserva cash_register para multi-caja/sucursal (fase 2):
-- se agregará branch + branch_id NULLABLE sin migración de datos.
-- =====================================================================

create type cash_module as enum ('pawn', 'store', 'general');
create type cash_direction as enum ('in', 'out');
create type cash_concept as enum (
  'loan_disbursed',     -- préstamo entregado (out, pawn)
  'interest_payment',   -- abono a interés (in, pawn)
  'capital_payment',    -- abono a capital (in, pawn)
  'sale',               -- venta (in, store)
  'purchase',           -- compra a proveedor (out, store)
  'expense',            -- gasto (out, module del gasto)
  'adjustment',
  'other'
);
create type session_status as enum ('open', 'closed');

create table public.cash_register (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.company(id),
  name       text not null default 'Caja principal',
  active     boolean not null default true,
  created_at timestamptz not null default now(),
  unique (company_id, name)
);

create table public.cash_session (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references public.company(id),
  register_id       uuid not null references public.cash_register(id),
  session_date      date not null default current_date,
  opened_by         uuid not null,
  opened_at         timestamptz not null default now(),
  opening_balance   numeric(14,2) not null check (opening_balance >= 0),  -- base ÚNICA
  expected_cash     numeric(14,2),
  counted_cash      numeric(14,2),
  difference        numeric(14,2),
  difference_reason text,
  closed_by         uuid,
  closed_at         timestamptz,
  status            session_status not null default 'open',
  report_url        text,           -- acta PDF (Storage)
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (register_id, session_date),
  -- toda diferencia requiere justificación (sin tolerancia)
  check (status = 'open' or difference is null or difference = 0 or difference_reason is not null)
);
create trigger trg_cash_session_updated before update on public.cash_session
  for each row execute function public.set_updated_at();

-- Solo UNA sesión abierta por caja (y no se abre nuevo día con la anterior abierta)
create unique index uq_session_open on public.cash_session (register_id)
  where status = 'open';

-- Movimientos: generados SOLO por los servicios desde documentos
-- (abono, venta, compra, gasto). Manual: únicamente expense/adjustment.
create table public.cash_movement (
  id             uuid primary key default gen_random_uuid(),
  company_id     uuid not null references public.company(id),
  session_id     uuid not null references public.cash_session(id),
  module         cash_module not null,
  direction      cash_direction not null,
  concept        cash_concept not null,
  reference_type text,           -- 'contract_payment' | 'sale' | 'inventory_entry' | 'expense' ...
  reference_id   uuid,
  amount         numeric(14,2) not null check (amount > 0),
  payment_method payment_method not null,
  notes          text,
  created_by     uuid,
  created_at     timestamptz not null default now()
);
create index ix_movement_session on public.cash_movement (session_id);
create index ix_movement_company_date on public.cash_movement (company_id, created_at);

-- Movimientos inmutables (correcciones = contra-movimiento)
create trigger trg_movement_immutable
  before update or delete on public.cash_movement
  for each row execute function public.forbid_change();

create table public.expense_category (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.company(id),
  name       text not null,
  active     boolean not null default true,
  unique (company_id, name)
);

-- DECIDIDO: sin aprobación adicional — basta el permiso del rol
-- (cashbox.expense); registro completo + auditoría.
create table public.expense (
  id             uuid primary key default gen_random_uuid(),
  company_id     uuid not null references public.company(id),
  session_id     uuid not null references public.cash_session(id),
  module         cash_module not null default 'general',
  category_id    uuid not null references public.expense_category(id),
  description    text not null,
  amount         numeric(14,2) not null check (amount > 0),
  payment_method payment_method not null,
  receipt_url    text,
  registered_by  uuid,
  created_at     timestamptz not null default now()
);

-- RLS
do $$
declare t text;
begin
  foreach t in array array['cash_register','cash_session','cash_movement',
                           'expense_category','expense']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format(
      'create policy tenant_isolation on public.%I
         using (company_id = public.current_company_id())
         with check (company_id = public.current_company_id())', t);
  end loop;
end $$;
