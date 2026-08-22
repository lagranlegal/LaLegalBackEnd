-- =====================================================================
-- 00036_product_unit_and_decimal_quantity.sql — vender por peso o medida.
--
-- EL LÍMITE QUE ESTO QUITA: `quantity` es `int` en las cuatro tablas del
-- flujo de mercancía, así que HOY NINGUNA COMPRAVENTA PUEDE VENDER NADA
-- POR PESO NI POR MEDIDA. Oro por gramo, cable por metro, lo que sea:
-- 12,5 g no se puede representar.
--
-- Salió mientras diseñábamos la FUNDICIÓN (fundir prendas rematadas y
-- quedarse con el oro), pero no es una función de oro: es un límite del
-- modelo de inventario que afecta a cualquier tenant que no venda cosas
-- contables de a una. Por eso va aparte y sirve solo.
--
-- Curiosamente el lado de EMPEÑO ya lo hacía bien desde 00005:
-- `contract_item.weight_grams` es `numeric(10,2)`. Era el inventario el que
-- se había quedado corto.
--
-- DOS PIEZAS
--
--   1. `product.unit` — en qué se mide este producto. Enum y no texto libre
--      a propósito: con texto libre terminan conviviendo "gr", "grs",
--      "gramo" y "gramos" en la misma base, y no hay forma de sumar ni de
--      mostrar nada consistente.
--
--   2. `quantity` pasa a `numeric(14,3)` en las cuatro tablas. Tres
--      decimales: al miligramo, más que suficiente para joyería, y en la
--      misma familia que el dinero (`numeric(14,2)`) para no mezclar
--      floats en ningún lado.
--
-- POR QUÉ SE PUEDE APLICAR ANTES DEL DEPLOY: ensanchar `int` a `numeric` es
-- lossless, y el código viejo sigue funcionando en la ventana entre migrar y
-- desplegar — asyncpg devuelve `Decimal` y Pydantic lo convierte a `int` sin
-- problema mientras no haya decimales, que es el caso de TODO el dato
-- existente. Nadie puede escribir 1,5 hasta que exista la unidad, y la
-- unidad nace acá.
--
-- LA REGLA QUE HABILITA, y que vive en el servicio: un producto medido en
-- `unit` RECHAZA cantidades fraccionarias. Media cadena no existe. La
-- columna acepta decimales para todos; qué producto puede usarlos lo decide
-- su unidad.
-- =====================================================================

create type product_unit as enum ('unit', 'gram', 'kilogram', 'meter', 'liter');

alter table public.product
  add column unit product_unit not null default 'unit';

-- ---------------------------------------------------------------------
-- Cantidad decimal. El `check` de cada tabla se recrea porque el original
-- se escribió contra el tipo viejo.
-- ---------------------------------------------------------------------

alter table public.inventory_item
  alter column quantity type numeric(14,3) using quantity::numeric(14,3);

alter table public.inventory_entry_line
  alter column quantity type numeric(14,3) using quantity::numeric(14,3);

alter table public.inventory_exit_line
  alter column quantity type numeric(14,3) using quantity::numeric(14,3);

alter table public.sale_line
  alter column quantity type numeric(14,3) using quantity::numeric(14,3);

-- Verificación: ensanchar no puede haber perdido nada, pero si algún dato
-- quedó en NULL o negativo por un `using` mal aplicado, mejor saberlo acá
-- que cuando un arqueo no cuadre.
do $$
declare malos int;
begin
  select count(*) into malos from public.inventory_item where quantity is null or quantity < 0;
  if malos > 0 then
    raise exception 'Quedaron % lotes con cantidad inválida tras el cambio de tipo.', malos;
  end if;
end $$;
