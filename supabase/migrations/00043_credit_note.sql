-- =====================================================================
-- 00043_credit_note.sql — la nota crédito, un pasivo que se DERIVA.
--
-- Cuando una devolución se liquida en nota crédito, la compraventa le debe
-- al cliente ese monto, redimible en una compra futura. El error fácil sería
-- guardar un `balance` en `credit_note` y descontarlo al redimir — pero eso
-- es exactamente el error que `reports.payables_by_supplier` ya evitó para
-- cuentas por pagar a proveedor: un saldo guardado se desincroniza, uno
-- derivado no puede.
--
-- Mismo patrón acá, mirror del de proveedor: `credit_note` es la emisión
-- (inmutable, como todo documento), `credit_note_redemption` es cada
-- consumo parcial en una venta futura, y el saldo es SIEMPRE
--
--   amount - sum(credit_note_redemption.amount)
--
-- calculado en cada lectura, nunca una columna. `unique(company_id,
-- sale_id, credit_note_id)` evita que la misma venta redima la misma nota
-- dos veces por un reintento sin idempotencia propia — no la necesita:
-- vive dentro de la transacción de `create_sale`, que ya deduplica por la
-- `idempotency_key` de la venta que la consume.
-- =====================================================================

create table public.credit_note (
  id             uuid primary key default gen_random_uuid(),
  company_id     uuid not null references public.company(id),
  number         bigint not null,
  customer_id    uuid not null references public.customer(id),
  sale_return_id uuid not null references public.sale_return(id),
  amount         numeric(14,2) not null check (amount > 0),
  notes          text,
  created_by     uuid,
  created_at     timestamptz not null default now(),
  unique (company_id, number),
  -- Una devolución emite a lo sumo una nota crédito.
  unique (company_id, sale_return_id)
);

create index ix_credit_note_customer on public.credit_note (company_id, customer_id);

alter table public.credit_note enable row level security;
alter table public.credit_note force row level security;
create policy tenant_isolation on public.credit_note
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

create trigger trg_credit_note_immutable
  before update or delete on public.credit_note
  for each row execute function public.forbid_change();

create table public.credit_note_redemption (
  id             uuid primary key default gen_random_uuid(),
  company_id     uuid not null references public.company(id),
  credit_note_id uuid not null references public.credit_note(id),
  sale_id        uuid not null references public.sale(id),
  amount         numeric(14,2) not null check (amount > 0),
  created_by     uuid,
  created_at     timestamptz not null default now(),
  unique (company_id, sale_id, credit_note_id)
);

create index ix_credit_note_redemption_note
  on public.credit_note_redemption (company_id, credit_note_id);

alter table public.credit_note_redemption enable row level security;
alter table public.credit_note_redemption force row level security;
create policy tenant_isolation on public.credit_note_redemption
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

create trigger trg_credit_note_redemption_immutable
  before update or delete on public.credit_note_redemption
  for each row execute function public.forbid_change();
