-- =====================================================================
-- 00061_idempotencia_dinero.sql — La `Idempotency-Key` se PERSISTE en las
-- operaciones de dinero que la exigían (o debían exigirla) y la tiraban.
--
-- Auditoría del 27/09/2026:
--   F5-02  `POST /accounts/{id}/settle` exigía la clave y nunca la pasaba al
--          servicio: dos envíos con la MISMA clave liquidaban dos veces
--          (Sistecrédito −100.000 y el banco +96.000 por una liquidación de
--          50.000). Y la liquidación no tenía documento propio donde
--          guardarla — sus movimientos apuntan a la cuenta, no a un acto.
--   F5-03  `POST /cashbox/expenses` (B-13): dos gastos con la misma clave.
--   F6-11  `POST /inventory/exits` (B-13): el doble clic duplicaba la baja.
--   F6-01  `POST /inventory/entries/{id}/pay` (B-07): exigía la clave y no la
--          guardaba; dos pagos de la misma factura sacaban la plata dos veces
--          aun con la misma clave.
--
-- Todo es ADITIVO y compatible con el código desplegado: columnas nullable
-- sin default ni backfill, y una tabla nueva que nadie más lee. UNIQUE con
-- NULLs es seguro en Postgres (cada NULL cuenta como distinto), así que las
-- filas viejas —y las que sigan llegando sin clave desde el front de hoy—
-- no chocan entre sí. Mismo criterio que 00009 y 00014.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. La liquidación como DOCUMENTO (F5-02).
--
-- Guarda lo que la respuesta devuelve (liquidado, recibido, saldo pendiente
-- antes), para que un reintento con la misma clave responda EXACTAMENTE lo
-- mismo sin volver a mover plata. La comisión no se guarda: se deriva
-- (liquidado − recibido), como en el servicio.
-- ---------------------------------------------------------------------
create table public.account_settlement (
  id               uuid primary key default gen_random_uuid(),
  company_id       uuid not null references public.company(id),
  from_account_id  uuid not null references public.account(id),
  to_account_id    uuid not null references public.account(id),
  amount_settled   numeric(14,2) not null check (amount_settled > 0),
  amount_received  numeric(14,2) not null check (amount_received >= 0),
  pending_before   numeric(14,2) not null,
  notes            text,
  created_by       uuid,
  created_at       timestamptz not null default now(),
  idempotency_key  text,
  unique (company_id, idempotency_key)
);

create index ix_account_settlement_company
  on public.account_settlement (company_id, from_account_id, created_at);

alter table public.account_settlement enable row level security;
alter table public.account_settlement force row level security;
create policy tenant_isolation on public.account_settlement
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

-- Inmutable, como un traslado o un movimiento de caja.
create trigger trg_account_settlement_immutable
  before update or delete on public.account_settlement
  for each row execute function public.forbid_change();

-- ---------------------------------------------------------------------
-- 2. Gasto (F5-03) y egreso de inventario (F6-11).
-- ---------------------------------------------------------------------
alter table public.expense add column idempotency_key text;
alter table public.expense
  add constraint expense_idempotency_key_unique unique (company_id, idempotency_key);

alter table public.inventory_exit add column idempotency_key text;
alter table public.inventory_exit
  add constraint inventory_exit_idempotency_key_unique unique (company_id, idempotency_key);

-- ---------------------------------------------------------------------
-- 3. Pago de una factura a crédito (F6-01).
--
-- Columna PROPIA y no `idempotency_key`: esa ya es la clave del INGRESO (la
-- compra), y el pago es otra operación, días después, con otra clave. Con
-- una sola columna el pago no tendría dónde guardar la suya sin pisar la
-- de la compra.
-- ---------------------------------------------------------------------
alter table public.inventory_entry add column pay_idempotency_key text;
alter table public.inventory_entry
  add constraint inventory_entry_pay_idempotency_key_unique
  unique (company_id, pay_idempotency_key);
