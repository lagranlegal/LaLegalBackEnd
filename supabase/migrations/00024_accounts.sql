-- =====================================================================
-- 00024_accounts.sql — Catálogo de CUENTAS. Fase 1 de 3: expandir.
--
-- Hoy el dinero se clasifica con un enum de tres valores
-- (`payment_method`: cash | transfer | other) que vive en CINCO tablas:
-- sale, contract_payment, expense, inventory_entry y cash_movement. Eso
-- alcanza para decir "entró en efectivo" pero no para decir A DÓNDE entró,
-- ni cuánto hay en cada lado.
--
-- EL CASO QUE OBLIGA AL CAMBIO: el cliente vende con Sistecrédito. Ahí el
-- dinero NO entra al vender — Sistecrédito asume el crédito, le cobra al
-- cliente, y le consigna al comercio días después MENOS una comisión. El
-- datáfono se comporta igual. Con el enum actual esas ventas quedan como
-- "otro" y la plata que te deben es invisible: ni está en caja, ni en el
-- banco, ni figura como algo por cobrar.
--
-- TRES TIPOS, PORQUE SE COMPORTAN DISTINTO:
--
--   cash        el dinero está al instante y se verifica CONTANDO, cada
--               noche, en el cierre de caja. Es lo que ya existe.
--   bank        el dinero está al instante y se verifica contra el EXTRACTO,
--               en el ritmo del banco (mensual), no en el cierre diario.
--   settlement  el dinero NO está: alguien te lo debe. Llega después y llega
--               MENOS. Se verifica contra la liquidación de quien paga.
--
-- Meter `bank` o `settlement` en el cierre diario sería un error: obligaría
-- al cajero a "cuadrar el banco" cada noche sin extracto y sin acceso,
-- contra un número que el propio sistema calculó. Solo las cuentas `cash`
-- entran al arqueo — el resto lleva saldo corriente y se concilia aparte.
--
-- LA COMISIÓN NO SE CONFIGURA. Al liquidar se registra lo que
-- EFECTIVAMENTE entró; la diferencia contra lo que estaba por cobrar es la
-- comisión, y se deriva. Así el sistema nunca queda desactualizado respecto
-- al contrato con Sistecrédito, y de paso queda visible cuánto cuesta el
-- convenio cada mes — que es información de negociación.
--
-- FASE 1 (esta): puramente ADITIVA. Se crea el catálogo, se le da a cada
-- empresa sus cuentas iniciales y se enlazan los movimientos existentes.
-- `payment_method` NO se toca: el código actual sigue funcionando igual.
--   fase 2  migrar    cada operación elige cuenta; liquidaciones
--   fase 3  contraer  `payment_method` deja de ser la fuente de verdad
-- =====================================================================

create type account_type as enum ('cash', 'bank', 'settlement');

create table public.account (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references public.company(id),
  name        text not null,
  type        account_type not null,
  -- Número de cuenta, del convenio, o del datáfono. Libre a propósito: cada
  -- banco y cada convenio lo formatean distinto y no aporta validarlo.
  reference   text,
  -- Solo una cuenta `cash` por empresa entra al arqueo diario (fase 1: una
  -- caja por empresa, igual que hoy). El índice parcial de abajo lo asegura.
  is_default  boolean not null default false,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (company_id, name)
);
create trigger trg_account_updated before update on public.account
  for each row execute function public.set_updated_at();

create index ix_account_company on public.account (company_id, type) where active;

-- Una sola cuenta por defecto por tipo y empresa: es la que se preselecciona
-- al cobrar y la que hereda un movimiento sin cuenta explícita.
create unique index uq_account_default on public.account (company_id, type)
  where is_default;

alter table public.account enable row level security;
alter table public.account force row level security;
create policy tenant_isolation on public.account
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

-- ---------------------------------------------------------------------
-- Cuentas iniciales por empresa, mapeando el enum actual.
--
-- `other` se mapea a una cuenta de tipo `bank` y no a `cash`: si hubiera
-- sido efectivo se habría registrado como tal, así que asumir lo contrario
-- inflaría el efectivo esperado y fabricaría descuadres — el mismo error que
-- ya costó una corrección con las compras a proveedor.
-- ---------------------------------------------------------------------

insert into public.account (company_id, name, type, is_default)
select c.id, 'Caja principal', 'cash', true from public.company c;

insert into public.account (company_id, name, type, is_default)
select c.id, 'Transferencias', 'bank', true from public.company c;

insert into public.account (company_id, name, type, is_default)
select c.id, 'Otros medios', 'bank', false from public.company c;

-- ---------------------------------------------------------------------
-- Enlazar lo existente. Aditivo: `payment_method` se queda intacto y sigue
-- siendo lo que el código lee hasta la fase 3.
-- ---------------------------------------------------------------------

alter table public.cash_movement    add column account_id uuid references public.account(id);
alter table public.sale             add column account_id uuid references public.account(id);
alter table public.contract_payment add column account_id uuid references public.account(id);
alter table public.expense          add column account_id uuid references public.account(id);
alter table public.inventory_entry  add column account_id uuid references public.account(id);

-- OJO: `cash_movement` y `contract_payment` tienen trigger de inmutabilidad
-- (`forbid_change`) que bloquea todo UPDATE — es una protección deliberada
-- del libro de movimientos y del recibo de abono, y está bien que exista.
--
-- Se desactiva SOLO durante este backfill y SOLO en esas dos tablas. Es
-- legítimo en una migración —versionada, revisada, de un solo tiro— y no en
-- código de aplicación, que es justo lo que el trigger existe para impedir.
-- El `account_id` que se escribe es información derivada del
-- `payment_method` que ya estaba en la fila: no altera ningún monto ni
-- ninguna fecha, así que el hecho registrado sigue siendo el mismo.
alter table public.cash_movement disable trigger trg_movement_immutable;
alter table public.contract_payment disable trigger trg_payment_immutable;

do $$
declare t text;
begin
  foreach t in array array['cash_movement', 'sale', 'contract_payment', 'expense',
                           'inventory_entry']
  loop
    execute format($f$
      update public.%I m
      set account_id = a.id
      from public.account a
      where a.company_id = m.company_id
        and m.payment_method is not null
        and a.name = case m.payment_method
                       when 'cash'     then 'Caja principal'
                       when 'transfer' then 'Transferencias'
                       else                 'Otros medios'
                     end
    $f$, t);
  end loop;
end $$;

alter table public.cash_movement enable trigger trg_movement_immutable;
alter table public.contract_payment enable trigger trg_payment_immutable;

-- Verificación: si el backfill dejó movimientos sin cuenta, algo no cuadró y
-- conviene saberlo ahora y no cuando el saldo por cuenta salga incompleto.
do $$
declare sueltos int;
begin
  select count(*) into sueltos
  from public.cash_movement where account_id is null;
  if sueltos > 0 then
    raise exception 'Quedaron % movimientos de caja sin cuenta asignada.', sueltos;
  end if;
end $$;

create index ix_cash_movement_account on public.cash_movement (company_id, account_id);
