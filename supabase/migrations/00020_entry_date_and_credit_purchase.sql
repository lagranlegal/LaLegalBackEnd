-- =====================================================================
-- 00020_entry_date_and_credit_purchase.sql — Separa CUÁNDO SE COMPRÓ de
-- CUÁNDO SE PAGÓ.
--
-- Problema real del cliente: el admin carga las facturas del proveedor de
-- días anteriores, o a las 11 de la noche con la caja ya cerrada. Hoy una
-- compra exige sesión abierta (00014) y queda con fecha de hoy, así que ese
-- flujo simplemente no se puede registrar.
--
-- LO QUE NO SE PUEDE HACER, Y POR QUÉ: no sirve "backdatear" el movimiento de
-- caja al día real de la compra. Una sesión cerrada es INMUTABLE por diseño
-- (00007, y `get_open_session` solo devuelve sesiones `open`), y con razón:
-- el acta de cierre ya se imprimió y se cuadró contra el efectivo contado.
-- Insertar un movimiento en un día ya cerrado invalidaría un documento
-- firmado. Así que una compra registrada tarde NO puede afectar la caja de
-- ese día — ninguna solución honesta puede prometer eso.
--
-- LA SALIDA CORRECTA es separar los dos hechos, que en contabilidad ya son
-- distintos:
--
--   `entry_date`  — cuándo ENTRÓ la mercancía. Es lo que importa para costo
--                   de ventas e inventario. Puede ser pasada.
--   pago          — cuándo SALIÓ la plata. Es lo que importa para la caja.
--                   Ocurre en la sesión abierta del momento en que se paga.
--
-- Con eso, los tres escenarios reales quedan cubiertos:
--   · compré y pagué hoy      -> `payment_method` en la creación (como hoy)
--   · compré ayer, ya pagué   -> se crea sin pago y se marca pagada; el
--                                movimiento cae en la sesión de HOY, que es
--                                lo único contablemente posible
--   · compré a crédito        -> se crea sin pago y queda pendiente hasta que
--                                se le pague al proveedor
--
-- El CHECK de 00014 (`purchase` => `payment_method not null`) se reemplaza:
-- ahora una compra PUEDE nacer sin medio de pago (pendiente), pero un ingreso
-- que no es compra sigue sin poder tenerlo — un remate con medio de pago
-- seguiría sin tener sentido en el acta.
-- =====================================================================

alter table public.inventory_entry
  add column entry_date date not null default current_date;

-- Marca de cuándo se registró el egreso de caja. NULL = compra pendiente de
-- pago. No es lo mismo que `created_at` (cuándo se digitó) ni que
-- `entry_date` (cuándo llegó la mercancía).
alter table public.inventory_entry add column paid_at timestamptz;

-- Backfill: las compras que ya existen se pagaron al crearse (era el único
-- camino posible antes de esta migración), así que su fecha de compra es la
-- de registro y su pago ya ocurrió.
update public.inventory_entry
set entry_date = created_at::date,
    paid_at    = created_at
where origin_type = 'purchase' and payment_method is not null;

update public.inventory_entry
set entry_date = created_at::date
where origin_type <> 'purchase';

alter table public.inventory_entry
  drop constraint if exists inventory_entry_payment_method_matches_origin;

-- Un medio de pago sigue siendo exclusivo de las compras; lo que cambia es
-- que ahora puede llegar después (o nunca, si se anula el trato).
alter table public.inventory_entry
  add constraint inventory_entry_payment_method_only_on_purchase check (
    payment_method is null or origin_type = 'purchase'
  ) not valid;

-- Coherencia entre las dos columnas nuevas: no puede haber fecha de pago sin
-- medio de pago, ni medio de pago sin fecha. Van juntas o ninguna.
alter table public.inventory_entry
  add constraint inventory_entry_payment_pair check (
    (payment_method is null and paid_at is null)
    or (payment_method is not null and paid_at is not null)
  ) not valid;

-- El reporte de compras pendientes filtra por esto.
create index ix_entry_pending_payment on public.inventory_entry (company_id, entry_date)
  where origin_type = 'purchase' and paid_at is null;
