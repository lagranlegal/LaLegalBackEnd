-- =====================================================================
-- 00025_account_opening_balance.sql — Saldo inicial de las cuentas.
--
-- Bug encontrado al sembrar datos reales en dev: la cuenta "Transferencias"
-- mostraba −$1.000.000. No era un error de suma — era que el saldo se
-- derivaba solo de los movimientos, y una cuenta bancaria YA TENÍA plata
-- antes de que el sistema existiera. El único movimiento registrado en ella
-- era un préstamo desembolsado (una salida), así que el neto daba negativo.
--
-- El efectivo no sufría lo mismo porque su base entra por otro lado: la
-- `opening_balance` de la sesión de caja. Las cuentas bancarias y las de
-- convenio no tienen sesión, así que necesitan su propio punto de partida.
--
-- Es el mismo error de fondo que ya apareció dos veces en este proyecto:
-- tomar el neto de los movimientos por el saldo real. Con las compras a
-- proveedor el neto ignoraba plata que sí salió; acá ignora plata que ya
-- estaba.
--
-- `settlement` arranca en cero de forma natural (nadie te debe nada el día
-- que creas el convenio), pero la columna aplica igual por si hay que
-- registrar un pendiente que venía de antes.
-- =====================================================================

alter table public.account
  add column opening_balance numeric(14, 2) not null default 0;

comment on column public.account.opening_balance is
  'Saldo con el que la cuenta entra al sistema. Para cuentas bank es lo que '
  'ya había en el banco; para settlement, lo que ya debían. El efectivo NO '
  'lo usa: su base viene de la opening_balance de cada sesión de caja.';
