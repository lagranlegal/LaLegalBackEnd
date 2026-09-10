-- =====================================================================
-- 00051_contract_extend_loan.sql — Ampliar el préstamo sobre un contrato
-- vivo ("recargo"). Diseño completo: docs/RECARGOS.md
--
-- EL CASO: una prenda avaluada en 2.000.000 sobre la que se prestó
-- 1.000.000 tiene cupo sin usar. El cliente vuelve a los pocos días y
-- quiere retirar parte de ese sobrante.
--
-- POR QUÉ NO ES UN `UPDATE` DEL CAPITAL, y no es una preferencia:
-- el interés se cobra en MESES COMPLETOS anclados a `interest_paid_until`
-- y toda la máquina de estados —mora, prórroga, remate— cuelga de esa
-- ancla. Subir el capital a mitad de mes obligaría a prorratear, y
-- prorratear es reescribir el núcleo del producto. Y hay una razón legal
-- además de una técnica: el papel que el cliente firmó dice un capital;
-- si el capital cambia, ese papel ya no describe la deuda.
--
-- Así que un recargo NO modifica el contrato: lo SUCEDE. El viejo queda
-- `superseded` con su foto firmada intacta, y nace uno nuevo que hay que
-- imprimir y firmar.
-- =====================================================================

-- OJO: un valor nuevo de enum no se puede USAR en la misma transacción que
-- lo declara. Este archivo no menciona 'superseded' ni 'transferred' en
-- ningún otro lado a propósito — las reglas viven en el servicio.
alter type contract_status      add value if not exists 'superseded';
alter type contract_item_status add value if not exists 'transferred';

-- ---------------------------------------------------------------------
-- La ventana: hasta cuándo se puede pedir un recargo.
--
-- SNAPSHOT en el contrato, como la tasa y el plazo: cambiar la política de
-- la empresa no puede alterar un contrato ya firmado.
--
-- El default de la COLUMNA es 28, pero el valor que se precarga al crear un
-- contrato sale de `company.settings.extension_window_days` — cada empresa
-- maneja su política. Mismo patrón que `return_window_days` (00045): la
-- política vive en `settings` y el documento se queda con su foto.
--
-- 0 = esta empresa (o este contrato) no admite recargos.
-- ---------------------------------------------------------------------
alter table public.contract
  add column if not exists extension_window_days int not null default 28
    check (extension_window_days >= 0);

-- ---------------------------------------------------------------------
-- Qué pasa con el interés del mes YA EMPEZADO al momento del recargo.
--
--   forgive       el reloj se reinicia; los días corridos se perdonan.
--   charge_month  exige el mes de interés pagado antes de ampliar.
--
-- `forgive` por defecto porque el daño está acotado por la ventana. Los
-- números son contraintuitivos y conviene dejarlos escritos: sobre un
-- capital de 1.000.000 al 5%, un recargo el DÍA 1 perdona 1.667 (nada) y
-- uno el día 27 perdona ~45.000 (casi un mes entero). El costo de perdonar
-- CRECE con los días, no al revés.
--
-- No hay 'prorate' y no lo va a haber: prorratear rompe la regla de meses
-- completos que sostiene abonos, mora, prórroga y remate.
-- ---------------------------------------------------------------------
alter table public.contract
  add column if not exists extension_interest_policy text not null default 'forgive'
    check (extension_interest_policy in ('forgive', 'charge_month'));

-- ---------------------------------------------------------------------
-- La cadena.
--
-- `root_contract_id` no es redundante con `parent_contract_id`: la ventana
-- se mide desde la RAÍZ, nunca desde el contrato actual. Sin eso, un
-- recargo de $1 el día 27 reinicia el reloj y el cliente encadena recargos
-- para siempre. Con el ancla en la raíz, 28 días son 28 días haya habido
-- uno o cinco.
-- ---------------------------------------------------------------------
alter table public.contract
  add column if not exists parent_contract_id uuid references public.contract(id),
  add column if not exists root_contract_id   uuid references public.contract(id);

create index if not exists ix_contract_root on public.contract (company_id, root_contract_id)
  where root_contract_id is not null;

-- ---------------------------------------------------------------------
-- Permisos.
--
-- `contracts.extend_loan` — entregar plata sobre un contrato vivo. Se
-- otorga a quien ya puede crear contratos: es la misma decisión (prestar),
-- solo que sobre una garantía que ya está en custodia.
--
-- `contracts.override_ltv` — pasarse del cupo de la tasación.
--
--   Mateo propuso una casilla por empresa ("advierte" / "bloquea"). Se
--   descartó: nadie sabe responder eso al dar de alta una empresa, parte el
--   producto en dos comportamientos, y contradice al propio sistema —crear
--   un contrato por encima del LTV advierte—, así que la misma regla se
--   comportaría distinto en dos pantallas.
--
--   Un permiso cubre lo mismo Y MÁS: quien lo tiene recibe la advertencia y
--   queda auditado como quien autorizó; quien no, queda bloqueado. La
--   casilla sigue siendo expresable (dárselo a todos o a nadie) y encima
--   cubre el caso que un booleano no puede — que el asesor no pueda y el
--   dueño sí, que es lo que va a querer la mayoría.
--
--   Se otorga a TODO rol que hoy pueda crear contratos, para que nadie
--   pierda acceso el día del despliegue: hasta hoy pasarse del LTV solo
--   advertía, para todos. La empresa que quiera apretar se lo quita al
--   Asesor. Mismo criterio que usó 00029 con los permisos de cuentas.
-- ---------------------------------------------------------------------
insert into public.permission (code, module, action, is_special, description) values
  ('contracts.extend_loan', 'contracts', 'extend_loan', false,
   'Ampliar el préstamo de un contrato vivo, entregando más dinero sobre la misma garantía'),
  ('contracts.override_ltv', 'contracts', 'override_ltv', true,
   'Prestar por encima del LTV máximo de la categoría (queda advertido y auditado)')
on conflict (code) do nothing;

insert into public.role_permission (role_id, permission_id)
select rp.role_id, p2.id
from public.role_permission rp
join public.permission p on p.id = rp.permission_id and p.code = 'contracts.create'
cross join public.permission p2
where p2.code in ('contracts.extend_loan', 'contracts.override_ltv')
on conflict do nothing;
