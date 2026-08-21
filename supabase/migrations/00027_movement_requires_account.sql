-- =====================================================================
-- 00027_movement_requires_account.sql — Fase 3: la cuenta es obligatoria.
--
-- Cierra el catálogo de cuentas. Todo movimiento nace ya con su cuenta —
-- las operaciones la eligen y `resolve_account_for_movement` completa la
-- predeterminada cuando no viene— así que la columna puede volverse NOT
-- NULL y el saldo por cuenta deja de poder nacer incompleto.
--
-- `payment_method` NO se elimina, y es una decisión, no una omisión:
--
--   · Es el dato del DOCUMENTO. Una venta se cobró "en efectivo" y eso es
--     un hecho de la venta que sigue teniendo sentido aunque después la
--     cuenta se renombre, se desactive o se reorganice el catálogo.
--   · El comprobante impreso y el histórico lo muestran. Derivarlo de la
--     cuenta actual haría que un comprobante viejo cambiara de texto si
--     alguien renombra una cuenta hoy — el mismo problema que ya se evitó
--     congelando el costo en la línea de venta (00019).
--   · Borrarlo obligaría a migrar cinco tablas para ganar nada: el enum
--     ocupa un byte y no compite con la cuenta, la complementa.
--
-- La CUENTA es dónde está la plata; el MEDIO es cómo se cobró. Con
-- Sistecrédito la diferencia se ve clara: el medio es "otro" y la cuenta es
-- el convenio que te la debe.
--
-- Se relaja además el NOT NULL de `payment_method` en cash_movement: un
-- movimiento entre cuentas (una liquidación) no se cobra por ningún medio,
-- solo cambia de contenedor.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Auto-reparación antes de contraer.
--
-- El backfill de 00024 solo alcanzó a las empresas que existían ese día.
-- Las creadas después nacieron sin cuentas —`create_company_defaults` no
-- las creaba, ese era el hueco real— y sus movimientos quedaron sueltos.
-- Igual que 00022, esta migración repara en vez de solo negarse: exigir un
-- backfill manual previo convierte cada deploy en un procedimiento que hay
-- que recordar, y lo que no se automatiza se olvida.
-- ---------------------------------------------------------------------

insert into public.account (company_id, name, type, is_default)
select c.id, v.name, v.type::account_type, v.is_default
from public.company c
cross join (values
  ('Caja principal', 'cash', true),
  ('Transferencias', 'bank', true),
  ('Otros medios',   'bank', false)
) as v(name, type, is_default)
on conflict (company_id, name) do nothing;

-- Mismo motivo que en 00024: los triggers de inmutabilidad bloquean el
-- UPDATE. Solo se completa una columna que nació nula; ningún monto ni
-- fecha cambia, así que el hecho registrado sigue siendo el mismo.
alter table public.cash_movement disable trigger trg_movement_immutable;

update public.cash_movement m
set account_id = a.id
from public.account a
where m.account_id is null
  and a.company_id = m.company_id
  and a.name = case m.payment_method
                 when 'cash'     then 'Caja principal'
                 when 'transfer' then 'Transferencias'
                 else                 'Otros medios'
               end;

alter table public.cash_movement enable trigger trg_movement_immutable;

do $$
declare sueltos int;
begin
  select count(*) into sueltos from public.cash_movement where account_id is null;
  if sueltos > 0 then
    raise exception
      'Quedaron % movimientos sin cuenta tras la reparación. Revisar antes de contraer.',
      sueltos;
  end if;
end $$;

alter table public.cash_movement alter column account_id set not null;
alter table public.cash_movement alter column payment_method drop not null;

-- El desglose del acta pasa a agruparse por cuenta: este índice es el que
-- sostiene esa consulta.
create index if not exists ix_movement_session_account
  on public.cash_movement (company_id, session_id, account_id);
