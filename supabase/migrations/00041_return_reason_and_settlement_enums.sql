-- =====================================================================
-- 00041_return_reason_and_settlement_enums.sql — los catálogos base de
-- "devolución de cliente".
--
-- 00033 dejó constancia explícita de que esta feature quedaba afuera a
-- propósito: "no es anular la venta del mismo día (eso ya lo cubre
-- sales.void): la venta ocurrió, hubo ingreso, y ahora sale plata. Merece
-- su propio camino y su propia decisión de negocio." Esta migración y las
-- que siguen (00042-00045) son ese camino.
--
-- DOS ENUMS NUEVOS, uno por cada decisión de negocio que hay que capturar
-- desde el día uno porque migrar datos históricos después es caro:
--
--   return_reason             defecto / cambio de decisión / otro. Una
--                              devolución por defecto tiene respaldo legal
--                              (garantía) distinto a un cambio de opinión —
--                              sin este dato no se pueden distinguir después.
--
--   return_settlement_method  efectivo / nota crédito. Elegido por
--                              transacción, no configurado por empresa: cada
--                              compraventa es libre de aceptar las dos, y no
--                              hay un estándar legal en Colombia para
--                              devoluciones en tienda física (el derecho de
--                              retracto de la Ley 1480/2011 solo aplica a
--                              ventas a distancia) que obligue a elegir una.
--
-- DOS VALORES NUEVOS EN ENUMS EXISTENTES, agregados aparte porque un valor
-- nuevo de enum no se puede usar en la misma transacción que lo crea (mismo
-- motivo que 00033): esta migración solo los agrega, nada acá los referencia.
--
--   entry_origin  + 'customer_return'  — reingreso de mercancía devuelta
--                                        cuyo lote original ya no es
--                                        reabrible (fue transformado, dado de
--                                        baja, etc.). Simétrico a
--                                        'supplier_return' del lado de
--                                        egresos: aquella es devolver AL
--                                        proveedor, esta es que el cliente
--                                        devuelve A la compraventa.
--
--   cash_concept  + 'sale_return'      — el contra-movimiento de una
--                                        devolución en efectivo. No reusa
--                                        'sale' con direction=out: ese ya es
--                                        `sales.void_sale` (mismo día, la
--                                        venta entera). Una devolución es un
--                                        hecho distinto, días o semanas
--                                        después, casi siempre parcial.
--
-- ADITIVA.
-- =====================================================================

create type return_reason as enum ('defect', 'change_of_mind', 'other');
create type return_settlement_method as enum ('cash', 'credit_note');

alter type entry_origin add value if not exists 'customer_return';
alter type cash_concept add value if not exists 'sale_return';
