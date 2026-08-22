-- =====================================================================
-- 00037_inventory_transformation.sql — entran N artículos, salen M, y el
-- COSTO VIAJA.
--
-- EL CASO QUE LA PIDIÓ: fundir prendas rematadas y quedarse con el oro. Pero
-- se generaliza a propósito, porque esto es un SaaS y cada compraventa lo va
-- a usar distinto:
--
--   fundir      3 prendas rematadas      -> oro 18k por gramos
--   despiezar   un celular dañado        -> pantalla, batería, carcasa
--   armar       consola + 2 controles    -> "kit gamer"
--   reparar     prenda + material        -> prenda reparada
--
-- Una sola operación, no cuatro. Y lo que pase DESPUÉS con lo que sale no es
-- asunto de esta función: es inventario común y corriente — se vende al
-- mostrador, se le vende a un mayorista, o se vuelve a transformar.
--
-- EL PRINCIPIO CONTABLE: lo que costó lo que entra es lo que cuesta lo que
-- sale, más lo que cueste el proceso. Ni se pierde ni se inventa.
--
-- Sin esto, fundir tres cadenas de 575.000 obligaba a darlas de baja como
-- pérdida (castiga 575.000 contra resultados, como si se hubieran evaporado)
-- y meter el oro como sobrante de conteo (inventa 575.000 de la nada). Dos
-- errores que se compensan en el saldo y destrozan el estado de resultados:
-- aparece una pérdida enorme y después un regalo del mismo tamaño.
--
-- LA MERMA SE ABSORBE SOLA. Entran 34 g de prendas y salen 31,2 g de oro:
-- los 2,8 g de diferencia son soldadura, impurezas, pérdida del proceso. No
-- se registran como nada — los 575.000 ahora se reparten entre menos gramos y
-- el costo por gramo sube, que es exactamente la verdad. Y ese costo por
-- gramo es el número que dice si fundir CONVENÍA: contra el precio del oro
-- del día, se sabe si se ganó o se perdió.
--
-- LO QUE COBRA EL FUNDIDOR SE CAPITALIZA. No es un gasto del mes: es parte
-- de producir ese activo, igual que el flete de una compra. Por eso entra al
-- costo del resultado y no al estado de resultados.
--
-- CÓMO SE IMPLEMENTA: reusando lo que ya existe en vez de inventar un camino
-- paralelo. La transformación es un DOCUMENTO que apunta a:
--   · un `inventory_exit`  con `exit_type = 'transformation'`   (lo consumido)
--   · un `inventory_entry` con `origin_type = 'transformation'` (lo producido)
-- Así el stock se mueve por los mismos caminos de siempre —con sus mismas
-- validaciones— y la trazabilidad de una pieza rematada sobrevive: contrato
-- -> remate -> artículo -> transformación -> lote de oro.
--
-- ADITIVA.
-- =====================================================================

alter type exit_type add value if not exists 'transformation';
alter type entry_origin add value if not exists 'transformation';

create table public.inventory_transformation (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references public.company(id),
  number      integer not null,
  -- Cuándo se transformó. Por defecto hoy; nunca futura.
  transform_date date not null default current_date,
  -- Lo que cobró el tercero (el fundidor, el técnico). Se CAPITALIZA: suma al
  -- costo de lo que sale, no es un gasto del período.
  extra_cost  numeric(14,2) not null default 0 check (extra_cost >= 0),
  notes       text,
  -- Los dos documentos que mueven el stock. La transformación es el vínculo
  -- entre ellos: sin esto serían un egreso y un ingreso sin relación, que es
  -- justo lo que hace imposible explicar de dónde salió el oro.
  exit_id     uuid not null references public.inventory_exit(id),
  entry_id    uuid not null references public.inventory_entry(id),
  created_by  uuid,
  created_at  timestamptz not null default now(),
  idempotency_key text,
  unique (company_id, number),
  unique (company_id, idempotency_key)
);

create index ix_transformation_company on public.inventory_transformation
  (company_id, transform_date);

alter table public.inventory_transformation enable row level security;
alter table public.inventory_transformation force row level security;
create policy tenant_isolation on public.inventory_transformation
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

-- Inmutable, como el resto de documentos que mueven stock o plata: fundir no
-- se deshace. Corregir es transformar de vuelta, y eso casi nunca es posible
-- —de una barra de oro no salen las tres cadenas otra vez—, razón de más para
-- que la operación pida confirmación antes y no permita "editar" después.
create trigger trg_transformation_immutable
  before update or delete on public.inventory_transformation
  for each row execute function public.forbid_change();

-- ---------------------------------------------------------------------
-- Permiso propio. DESTRUYE INVENTARIO de forma irreversible, así que va
-- aparte de `inventory.create` y de `inventory.exit` — mismo criterio que
-- separó `accounts.transfer` e `inventory.pay_purchase`.
--
-- Se otorga a quien ya podía hacer egresos: dar de baja mercancía es la
-- capacidad más cercana que existe, y quien la tiene ya tiene esa confianza.
-- Nadie gana un poder que no tuviera de alguna forma.
-- ---------------------------------------------------------------------

insert into public.permission (code, module, action, is_special, description) values
  ('inventory.transform', 'inventory', 'transform', true,
   'Transformar inventario: fundir, despiezar o armar (consume artículos y crea otros)')
on conflict (code) do nothing;

insert into public.role_permission (role_id, permission_id)
select rp.role_id, (select id from public.permission where code = 'inventory.transform')
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'inventory.exit'
on conflict do nothing;
