-- =====================================================================
-- 00049_vault_accounts.sql — La caja fuerte, y el vínculo cuenta↔caja
--
-- POR QUÉ (docs/CAJA_TRAZABILIDAD.md §5):
--   `account.type` mezclaba dos preguntas independientes:
--
--                       ¿es efectivo físico?   ¿es operativa?
--                       (se cuenta a mano)     (una venta la puede elegir)
--     cash                      sí                    sí
--     CAJA FUERTE               sí                    NO      <- no existía
--     bank                      no                    no
--     settlement                no                    no
--
--   La combinación de la caja fuerte no existía, y las dos salidas fáciles
--   fallaban. Como `bank`, los números cuadran pero el efectivo en custodia
--   figura como saldo bancario y el día que alguien concilie contra el
--   extracto sobra plata que no está ahí. Como `cash`, el arqueo diario del
--   cajón te pide contar también la caja fuerte, todos los días.
--
--   Resultado: una empresa que guarda plata fuera del cajón la tenía
--   INVISIBLE para el sistema. No es una comodidad que falte; es un hueco.
--
-- LO QUE ESTE TIPO SIGNIFICA:
--   · Es efectivo físico: cuenta como efectivo en reportes y se puede
--     arquear con la frecuencia que cada negocio quiera (contándola).
--   · NO es operativa: ninguna venta, préstamo, abono, gasto ni compra la
--     puede elegir. Solo recibe y entrega por TRASLADO, que ya existe y ya
--     deja documento numerado. Lo impone `resolve_account_for_movement`.
--   · No exige turno abierto ni entra al `expected_cash` del turno: el
--     arqueo diario sigue siendo el del cajón, que es lo que se cuenta cada
--     noche.
--
-- NADA SE CONFIGURA. "¿Esta empresa tiene caja fuerte?" se responde con
-- "¿existe esa cuenta?". Una empresa que no la tenga nunca la crea y el
-- producto se comporta igual que antes.
-- =====================================================================

-- OJO: `alter type ... add value` no puede USARSE en la misma transacción
-- que lo declara. Por eso este archivo no menciona 'vault' en ningún otro
-- lado: el resto de las reglas viven en el servicio, y la primera migración
-- que lo use como literal tendrá que ser otra.
alter type account_type add value if not exists 'vault';

-- ---------------------------------------------------------------------
-- A qué caja registradora pertenece una cuenta de efectivo.
--
-- NULLABLE y sin uso todavía: es la fase 2 de multi-caja que `00007` ya
-- dejó anunciada ("El modelo conserva cash_register para multi-caja /
-- sucursal"). Se agrega ahora, vacía, porque agregar una columna nullable
-- no cuesta nada y el día que aparezca un segundo mostrador —o una segunda
-- sucursal— la diferencia entre conectar la UI y rediseñar el modelo es
-- exactamente esta columna.
--
-- Hoy `cash_session` ya cuelga de `register_id` y el índice de sesión
-- abierta ya es POR REGISTRADORA (`uq_session_open`), así que la base
-- admite varias cajas con su turno abierto en simultáneo. Lo único que
-- falta para usarlas es saber qué cajón es de cuál, que es esto.
--
-- Las cuentas `vault` y las que no son efectivo la dejan en NULL: una caja
-- fuerte no pertenece a un mostrador.
-- ---------------------------------------------------------------------
alter table public.account
  add column if not exists register_id uuid references public.cash_register(id);

create index if not exists ix_account_register on public.account (company_id, register_id)
  where register_id is not null;

comment on column public.account.register_id is
  'Caja registradora a la que pertenece este cajón. NULL en cuentas que no son un cajón operativo (banco, convenio, caja fuerte). Sin uso hasta la fase 2 de multi-caja.';
