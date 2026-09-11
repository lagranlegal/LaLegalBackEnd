-- =====================================================================
-- 00054_owner_capital.sql — el dinero del DUEÑO: aportes y retiros.
--
-- EL CASO QUE FALTA (Mateo, 11/09/2026, probando con el cliente). Dos
-- preguntas que son la misma operación en dos sentidos:
--
--   · "Estamos bajos de capital para prestar; el dueño le va a meter
--      x cantidad al negocio". ¿Dónde se registra?
--   · "El dueño quiere retirar x por utilidad". ¿Cómo se le da salida?
--
-- Ninguna de las dos existía. Hoy el dueño que mete plata tiene tres
-- salidas y las TRES están mal:
--
--   · como `adjustment` de arqueo  -> un ajuste significa "el sistema no
--        cuadra con la realidad y lo estoy corrigiendo". Acá cuadra
--        perfecto: hubo un hecho real, con fecha, monto y responsable.
--   · como traslado                -> solo sirve si la plata YA está en
--        una cuenta de la empresa. El bolsillo del dueño no lo es.
--   · sin registrar                -> la plata aparece en el cajón sin
--        documento. Es exactamente el "número inventado" que 00048 existe
--        para eliminar.
--
-- Y el retiro registrado como GASTO falsea la utilidad del período por
-- todo el monto retirado. Es el mismo error que este proyecto ya pagó tres
-- veces —"prestar no es un gasto, cobrar no es una ganancia"— y que 00032
-- documentó para las consignaciones.
--
-- =====================================================================
-- CÓMO LO RESUELVE UN SISTEMA CONTABLE, Y QUÉ TOMAMOS DE ESO
-- =====================================================================
--
-- En partida doble un aporte es `Débito Caja / Crédito Patrimonio` y un
-- retiro es `Débito Patrimonio / Crédito Caja`. Lo esencial de eso es UNA
-- frase: **ninguno de los dos pasa por el estado de resultados**. Un
-- aporte no es un ingreso y un retiro no es un gasto; los dos mueven el
-- patrimonio, no el resultado del período.
--
-- **Y esta app NO necesita construir partida doble para cumplirlo.**
-- `get_income_statement` lee DOCUMENTOS (`sale`, `contract_payment`,
-- `expense`), nunca `cash_movement`. Así que un documento nuevo que no sea
-- ninguno de esos tres queda fuera del resultado por construcción, sin una
-- sola línea de exclusión que alguien pueda olvidar. El modelo ya protegía
-- esto antes de que el caso existiera.
--
-- =====================================================================
-- UN SOLO DOCUMENTO PARA LOS DOS CASOS
-- =====================================================================
--
-- Aporte y retiro son el mismo concepto en dos sentidos, igual que un
-- traslado es una salida y una entrada. Partirlo en dos tablas (o en dos
-- módulos) duplicaría el número, la idempotencia, el RLS, la auditoría y
-- la pantalla, para expresar una diferencia que cabe en una columna.
--
-- POR QUÉ UNA TABLA Y NO SOLO UN `cash_movement` CON OTRO CONCEPTO:
-- CLAUDE.md regla 4 — los movimientos de caja los generan los servicios
-- DESDE DOCUMENTOS. El documento guarda la fecha real, el motivo, quién lo
-- hizo y la clave de idempotencia. Mismo argumento textual que 00032.
-- =====================================================================

alter type cash_concept add value if not exists 'owner_contribution';
alter type cash_concept add value if not exists 'owner_withdrawal';

create type capital_direction as enum ('contribution', 'withdrawal');

-- ---------------------------------------------------------------------
-- Qué clase de retiro es.
--
-- Contablemente NO son lo mismo: retirar utilidad reduce las ganancias
-- acumuladas; devolver capital reduce el aporte. Para el dueño de una
-- compraventa la distinción no existe hasta que llega la declaración.
--
-- Así que: una columna, un default, **cero UI el día uno**. Es el mismo
-- patrón que `extension_interest_policy` (00051), que quedó puesto sin
-- exponerse y resultó ser exactamente lo que hizo falta tres días después.
--
-- Solo aplica a los retiros: un aporte no tiene clase.
-- ---------------------------------------------------------------------
create type capital_withdrawal_kind as enum ('profit', 'capital_return');

create table public.capital_movement (
  id              uuid primary key default gen_random_uuid(),
  company_id      uuid not null references public.company(id),
  number          integer not null,
  direction       capital_direction not null,
  kind            capital_withdrawal_kind,
  -- A qué cuenta entra o de cuál sale. Una `settlement` no puede: es plata
  -- que te DEBEN, no un saldo del que se pueda sacar ni al que se pueda
  -- meter efectivo del bolsillo. Lo valida el servicio, como en 00032.
  account_id      uuid not null references public.account(id),
  amount          numeric(14,2) not null check (amount > 0),
  -- Cuándo se movió la plata. Por defecto hoy; nunca futura (lo valida el
  -- servicio contra el hoy de la EMPRESA, no el del servidor: ya hubo dos
  -- bugs por usar `current_date`, que es UTC).
  movement_date   date not null default current_date,
  -- Por qué. Obligatorio en el RETIRO y opcional en el aporte: meter plata
  -- al negocio se explica solo; sacarla es la decisión que alguien va a
  -- querer entender dentro de un año.
  notes           text,
  created_by      uuid,
  created_at      timestamptz not null default now(),
  -- Mover plata es una operación de dinero: exige `Idempotency-Key` y el
  -- reintento devuelve el mismo documento en vez de retirar dos veces.
  idempotency_key text,
  unique (company_id, number),
  unique (company_id, idempotency_key),
  -- `kind` es exactamente de los retiros: nulo en un aporte, obligatorio en
  -- un retiro. Sin esto quedarían aportes con "clase de retiro" y retiros
  -- sin clasificar, y el reporte de patrimonio no podría separarlos.
  constraint capital_movement_kind_matches_direction
    check ((direction = 'withdrawal') = (kind is not null)),
  constraint capital_movement_withdrawal_needs_reason
    check (direction <> 'withdrawal' or notes is not null)
);

create index ix_capital_movement_company
  on public.capital_movement (company_id, movement_date);

alter table public.capital_movement enable row level security;
alter table public.capital_movement force row level security;
create policy tenant_isolation on public.capital_movement
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

-- Inmutable, igual que un traslado, un movimiento de caja o un recibo de
-- abono: corregirlo es registrar el movimiento contrario, no editarlo.
create trigger trg_capital_movement_immutable
  before update or delete on public.capital_movement
  for each row execute function public.forbid_change();

-- ---------------------------------------------------------------------
-- Permisos propios desde el día uno.
--
-- "Un módulo nuevo trae sus propios permisos aunque parezcan redundantes.
-- Reusar los de otro deja el módulo fuera de la matriz de roles" — está
-- escrito en ESTADO.md porque ya pasó.
--
-- Son TRES y no uno, porque no son la misma decisión:
--
--   capital.view        ver el historial de aportes y retiros. Es el
--                       patrimonio del dueño: no es dato de mostrador.
--   capital.contribute  meter plata al negocio. Benigno — el riesgo de
--                       equivocarse es un ajuste, no una pérdida.
--   capital.withdraw    SACAR plata del negocio. Especial: es la única
--                       operación de la app que le quita capital a la
--                       empresa sin nada a cambio.
--
-- Se otorgan SOLO al Admin. Los roles semilla se arman en
-- `platform/service.py`: Admin recibe todos los códigos, así que basta con
-- excluirlos del Moderador ahí. Para las empresas que YA existen hay que
-- dárselos explícitamente a sus roles Admin, que es lo que hace el insert
-- de abajo — sin él, el dueño de LA GRAN LEGAL no vería el módulo.
-- ---------------------------------------------------------------------
insert into public.permission (code, module, action, is_special, description) values
  ('capital.view', 'capital', 'view', false,
   'Ver los aportes de capital y los retiros del dueño'),
  ('capital.contribute', 'capital', 'contribute', false,
   'Registrar un aporte de capital del dueño al negocio'),
  ('capital.withdraw', 'capital', 'withdraw', true,
   'Registrar un retiro de utilidades o de capital hacia el dueño')
on conflict (code) do nothing;

-- Solo a los roles que hoy pueden administrar la empresa entera. Se usa
-- `identity.manage_roles` como testigo de "es el rol de dueño/admin":
-- quien puede repartir permisos ya puede darse este.
insert into public.role_permission (role_id, permission_id)
select rp.role_id, p2.id
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'identity.manage_roles'
cross join public.permission p2
where p2.code in ('capital.view', 'capital.contribute', 'capital.withdraw')
on conflict do nothing;

-- Aditiva de punta a punta: tipos nuevos, tabla nueva, permisos nuevos.
-- Nada de lo que ya corre la mira. Se puede aplicar antes del deploy.
