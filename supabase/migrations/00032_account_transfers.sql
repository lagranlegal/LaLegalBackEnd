-- =====================================================================
-- 00032_account_transfers.sql — mover plata entre cuentas propias.
--
-- EL CASO QUE FALTA: al final del día se saca el efectivo del cajón y se
-- consigna en el banco. Hoy esa operación NO EXISTE. El módulo de cuentas
-- sabe LIQUIDAR una cuenta por cobrar (Sistecrédito consigna lo que debía)
-- pero no sabe mover plata entre dos cuentas propias, así que consignar
-- deja dos salidas y las dos están mal:
--
--   · registrarlo como GASTO      -> falsea la utilidad. Es exactamente el
--                                    error que este proyecto ya se ganó a
--                                    los golpes con el capital de los
--                                    contratos: "prestar no es un gasto,
--                                    cobrar no es una ganancia".
--   · no registrarlo              -> el saldo del banco queda mentiroso y
--                                    el efectivo esperado del día siguiente
--                                    queda inflado, así que el arqueo
--                                    descuadra sin culpa del cajero.
--
-- EL PRINCIPIO: un traslado no es ingreso ni egreso. Es la misma plata en
-- otro bolsillo. No toca el estado de resultados, solo mueve saldos.
--
-- POR QUÉ CONCEPTOS NUEVOS Y NO `adjustment`: un ajuste significa "el
-- sistema no cuadra con la realidad y lo estoy corrigiendo". Un traslado sí
-- cuadra — es una operación normal y planeada. Mezclarlos haría imposible
-- separarlos después, y los reportes necesitan EXCLUIR los traslados del
-- cálculo de ingresos y gastos: contarlos inventaría movimiento de negocio
-- donde solo hubo un cambio de bolsillo.
--
-- POR QUÉ UNA TABLA Y NO SOLO DOS MOVIMIENTOS: CLAUDE.md regla 4 — los
-- movimientos de caja los generan los servicios DESDE DOCUMENTOS. El
-- documento es lo que guarda la fecha, el motivo, quién lo hizo y la clave
-- de idempotencia; los dos movimientos son su reflejo contable. Sin
-- documento, un traslado sería el único movimiento de dinero del sistema
-- sin nada que lo respalde.
--
-- ADITIVA: no toca ninguna tabla existente, así que puede aplicarse ANTES
-- del deploy sin romper el código que está corriendo.
-- =====================================================================

alter type cash_concept add value if not exists 'transfer_out';
alter type cash_concept add value if not exists 'transfer_in';

create table public.account_transfer (
  id              uuid primary key default gen_random_uuid(),
  company_id      uuid not null references public.company(id),
  number          integer not null,
  from_account_id uuid not null references public.account(id),
  to_account_id   uuid not null references public.account(id),
  amount          numeric(14,2) not null check (amount > 0),
  -- Cuándo se movió la plata. Por defecto hoy; nunca futura (lo valida el
  -- servicio contra el hoy de la EMPRESA, no el del servidor).
  transfer_date   date not null default current_date,
  notes           text,
  created_by      uuid,
  created_at      timestamptz not null default now(),
  -- Mover plata es una operación de dinero: exige `Idempotency-Key` y el
  -- reintento devuelve el mismo traslado en vez de consignar dos veces.
  idempotency_key text,
  -- Trasladar a la misma cuenta no mueve nada y dejaría dos movimientos que
  -- se anulan entre sí, ensuciando el acta sin cambiar ningún saldo.
  constraint account_transfer_distinct check (from_account_id <> to_account_id),
  unique (company_id, idempotency_key)
);

create index ix_account_transfer_company on public.account_transfer (company_id, transfer_date);

alter table public.account_transfer enable row level security;
alter table public.account_transfer force row level security;
create policy tenant_isolation on public.account_transfer
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

-- Un traslado es inmutable, igual que un movimiento de caja o un recibo de
-- abono: corregirlo es hacer el traslado contrario, no editar el original.
create trigger trg_account_transfer_immutable
  before update or delete on public.account_transfer
  for each row execute function public.forbid_change();

-- ---------------------------------------------------------------------
-- Permiso propio. Va aparte de `accounts.manage` (crear/editar cuentas)
-- porque MUEVE PLATA — mismo criterio que separó `accounts.settle` en
-- 00029. Quien administra el catálogo de cuentas no necesariamente puede
-- sacar el efectivo del cajón.
-- ---------------------------------------------------------------------

insert into public.permission (code, module, action, is_special, description) values
  ('accounts.transfer', 'accounts', 'transfer', true,
   'Trasladar plata entre cuentas propias (consignar el efectivo)')
on conflict (code) do nothing;

-- Se otorga a quien ya podía liquidar: es la misma clase de operación
-- (mover plata entre dos cuentas de la empresa) y quien tiene esa confianza
-- ya la tiene. Nadie gana un poder que no tuviera de alguna forma.
insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'accounts.transfer')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'accounts.settle'
on conflict do nothing;
