-- =====================================================================
-- 00056_unaccent_search.sql — buscar sin eñes ni tildes.
--
-- EL PROBLEMA ES **LA EÑE**, y no las tildes — que es lo contrario de lo
-- que yo había anotado al arreglar el buscador el 11/09/2026. Conviene
-- dejar la medición, porque la intuición falla acá:
--
--   El stemmer snowball de `spanish` SÍ normaliza las vocales acentuadas.
--   `to_tsvector('spanish', 'José')` da el lexema 'jos', y 'Gómez' da
--   'gomez'. O sea que buscar "jose" o "gomez" YA funcionaba.
--
--   La eñe NO la toca: 'Muñoz' queda 'muñoz' y 'Peña' queda 'peñ'. Así que
--   "munoz" y "pena" no encuentran nada, y tampoco los encuentra el `ilike`
--   de respaldo.
--
-- Medido sobre apellidos colombianos corrientes — 8 de 11 fallaban, y los
-- 8 por la misma razón:
--
--     José · Gómez · Andrés              ya funcionaban
--     Muñoz · Peña · Castaño · Ordóñez   no
--     Zúñiga · Núñez · Acuña · Piña      no
--
-- Y nadie teclea la eñe buscando: el teclado del celular la esconde. El
-- buscador quedaba "arreglado" y seguía sin encontrar a una parte grande
-- de la base.
--
-- `unaccent` mapea ñ→n, así que funciona en los dos sentidos: quien teclee
-- "munoz" y quien teclee "muñoz" encuentran a Muñoz. Y "peña"/"pena" pasan
-- a ser la misma búsqueda, que es lo que uno quiere en un mostrador.
--
-- =====================================================================
-- POR QUÉ HACE FALTA UNA FUNCIÓN ENVOLTORIO
-- =====================================================================
--
-- `unaccent(text)` es **STABLE, no IMMUTABLE**: depende del diccionario
-- que resuelva el `search_path` en ese momento, y Postgres se niega a
-- indexar una expresión que puede cambiar de resultado. Sin envoltorio, el
-- índice funcional no se puede crear y cada búsqueda sería un seq scan
-- recalculando el `tsvector` de toda la tabla.
--
-- `f_unaccent` fija el diccionario por nombre y el `search_path` de la
-- función, con lo que el resultado SÍ es determinista y se puede declarar
-- `immutable`. Es el patrón estándar para esto.
--
-- El `set search_path` no es decorativo: sin él, la función resolvería
-- `unaccent` contra el search_path de QUIEN la llame — y el backend cambia
-- de rol por transacción (`set local role authenticated`, core/db.py). Una
-- función inmutable cuyo resultado dependa de quién la invoca es
-- exactamente lo que el planificador no espera.
-- =====================================================================

create extension if not exists unaccent with schema extensions;

create or replace function public.f_unaccent(text)
returns text
language sql
immutable
parallel safe
strict
set search_path = extensions, public, pg_catalog
as $$ select unaccent('unaccent'::regdictionary, $1) $$;

comment on function public.f_unaccent(text) is
  'Envoltorio IMMUTABLE de unaccent(), para poder indexar la expresión. '
  'unaccent() es STABLE porque depende del search_path; acá el diccionario '
  'queda fijado por nombre y el search_path de la función. Se usa en los '
  'buscadores por nombre (app/common/search.py).';

-- ---------------------------------------------------------------------
-- El índice.
--
-- EXPANDIR, no reemplazar: el `ix_customer_name` viejo —sobre
-- `to_tsvector('spanish', full_name)` sin unaccent— SIGUE HACIENDO FALTA
-- hasta que el backend nuevo esté desplegado, porque es el que usa el
-- código que está corriendo ahora mismo. Borrarlo acá dejaría al buscador
-- en vivo haciendo seq scan hasta el deploy.
--
-- La contracción (drop del viejo) va en su propia migración DESPUÉS del
-- despliegue, como manda el orden del proyecto.
-- ---------------------------------------------------------------------
create index if not exists ix_customer_name_unaccent
  on public.customer
  using gin (to_tsvector('spanish', public.f_unaccent(full_name)));

-- `product.name` nunca tuvo índice de full-text: sus búsquedas ya eran seq
-- scan antes de esto. Se le pone ahora que se está tocando la expresión de
-- todos modos — el picker del carrito de venta lo consulta en cada tecla.
create index if not exists ix_product_name_unaccent
  on public.product
  using gin (to_tsvector('spanish', public.f_unaccent(name)));

-- Aditiva: una extensión, una función nueva y dos índices nuevos. Nada de
-- lo que ya corre cambia de comportamiento hasta que el código nuevo use
-- `f_unaccent`. Se puede aplicar antes del deploy.
