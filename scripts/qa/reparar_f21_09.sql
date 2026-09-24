-- Reparación de F21-09 — 23/09/2026
--
-- QUÉ REPARA
-- La migración `00051_contract_extend_loan.sql:113-119` hizo un backfill que le
-- dio `contracts.extend_loan` y `contracts.override_ltv` a TODO rol que ya
-- tuviera `contracts.create`, para que nadie perdiera acceso el día del
-- despliegue. Eso incluyó al rol **Asesor** — el mostrador.
--
-- POR QUÉ ES UN DEFECTO Y NO UNA DECISIÓN
-- Porque el propio código ya decidió lo contrario: `_ASESOR_CODES`
-- (`app/modules/platform/service.py:27-43`) NO incluye ninguno de los dos, así
-- que un Asesor de una empresa creada HOY no los recibe. Lo que hay no es un
-- criterio distinto, es una divergencia entre las empresas que existían el día
-- del backfill y las que nacieron después. El lado correcto ya está escrito.
--
-- POR QUÉ LOS DOS, Y POR QUÉ `extend_loan` IMPORTA MÁS
-- `override_ltv` es `is_special` y autoriza prestar por encima del tope de la
-- categoría: si lo tiene todo el mostrador, el LTV deja de ser un límite.
-- `extend_loan` es más grave y el hallazgo original no lo nombraba: no autoriza
-- una excepción, DESEMBOLSA más dinero sobre una garantía ya entregada.
--
-- POR QUÉ VA ACOTADO A UN role_id Y NO AL PREDICADO
-- Mismo criterio que `reparar_f21_10.sql`: el predicado es lo que hay que
-- vigilar, no lo que se ejecuta a ciegas sobre datos reales. Las otras seis
-- empresas de dev que tienen la misma divergencia son de prueba (ZZ */
-- Compraventa de Prueba QA) y quedan fuera a propósito: el alcance autorizado
-- por Mateo el 23/09 fue LA GRAN LEGAL, la única con usuarios reales (2 activos).
--
-- LO QUE NO HACE FALTA TOCAR
-- El front ya está preparado para la ausencia de los dos permisos, y se
-- verificó ANTES de ejecutar esto — porque hasta hoy esa rama no la había visto
-- nadie ("un permiso que se otorgó a todos no protege a nadie todavía"):
--   · `LtvHint.tsx:24` lee `usePermission('contracts.override_ltv')` y cambia el
--     texto a quién pedírselo, en vez de dejar al asesor llegar al 403 final.
--   · `ExtendLoanPanel.tsx:126` está envuelto en `<Can permission=...>`, así que
--     el panel desaparece en vez de fallar.
-- El cambio tarda hasta ~1 minuto en verse: `/me` se cachea 60s en el front y el
-- backend cachea permisos por rol otro tanto (es deliberado).
--
-- AUDITORÍA
-- Regla 6 de CLAUDE.md. Se reusa la acción `update_role_permissions` que ya
-- emite `identity/service.py:347` —es literalmente lo que esto hace— en vez de
-- inventar una nueva: ya está en el catálogo y en `features/audit/labels.ts:63`,
-- así que la pantalla no la muestra en crudo. `user_id` va NULL a propósito: no
-- lo hizo un usuario de la empresa, fue una corrección de datos.

begin;

with target as (
  select r.id as role_id, r.company_id, r.name as role_name
  from public.role r
  where r.id = '6028e104-1136-4e3a-9c1c-4f3f38c9dd91'   -- LA GRAN LEGAL · Asesor · 2 usuarios activos
    and r.name = 'Asesor'
),
victims as (
  select t.role_id, t.company_id, t.role_name, p.id as permission_id, p.code
  from target t
  join public.role_permission rp on rp.role_id = t.role_id
  join public.permission p on p.id = rp.permission_id
  where p.code in ('contracts.extend_loan', 'contracts.override_ltv')
  for update of rp
),
del as (
  delete from public.role_permission rp
   using victims v
   where rp.role_id = v.role_id and rp.permission_id = v.permission_id
  returning rp.role_id
)
insert into public.audit_log (company_id, user_id, module, action, entity_type, entity_id, before, after)
select v.company_id,
       null,
       'identity',
       'update_role_permissions',
       'role',
       v.role_id,
       jsonb_build_object('role', v.role_name, 'permission', v.code, 'granted', true),
       jsonb_build_object('role', v.role_name, 'permission', v.code, 'granted', false,
                          'motivo', 'F21-09: el backfill de la migracion 00051 le dio este permiso a todo rol con contracts.create, incluido el mostrador. _ASESOR_CODES nunca lo incluyo, asi que una empresa nueva no lo recibe.')
  from victims v;

commit;
