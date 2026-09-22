-- Reparación de F21-10 — 21/09/2026
--
-- QUÉ REPARA
-- El job nocturno de Fly quedó clavado a su imagen del 08/09 y el 10/09 entró
-- `superseded` como estado terminal. Durante once días recalculó los contratos
-- reemplazados por una ampliación como si siguieran vivos. Segundo vector, con
-- el mismo efecto: `get_contract` también recalcula y PERSISTE el status en
-- cada lectura de detalle, y la app servida venía sin la guarda hasta el
-- deploy del 21/09. Detalle completo en `docs/QA_AUDITORIA.md` §F21-10.
--
-- Resultado: 4 contratos con sucesor quedaron fuera de `superseded`, y uno de
-- ellos (Empresa Demo Front Nº 1) con `extension_ends_at = 2026-10-16`, o sea
-- entrando solo a «Listos para remate» a partir del 17/10.
--
-- POR QUÉ VA ACOTADO A IDS Y NO AL PREDICADO
-- El predicado es el que hay que VIGILAR (ver `verificar_cadenas.py`), no el
-- que hay que ejecutar a ciegas sobre datos reales. Estos 4 ids se midieron y
-- se caracterizaron uno por uno el 21/09.
--
-- POR QUÉ `extension_ends_at = null` NO ES OPCIONAL
-- Solo el Nº 1 lo tiene sucio, pero dejarlo mantiene la bomba del 17/10 aunque
-- el status ya diga `superseded`, y deja una fila que contradice la invariante
-- de que un estado terminal no tiene prórroga viva.
--
-- LO QUE NO HACE FALTA TOCAR
-- `contract_item` ya está en `transferred` en los cuatro: el job solo escribe
-- `status` y `extension_ends_at` (`repository.update_contract_status`).
--
-- AUDITORÍA
-- Ningún servicio va a generar estas filas, y la regla 6 de CLAUDE.md exige
-- auditar toda acción sensible. `user_id` va NULL a propósito: no lo hizo un
-- usuario de la empresa, fue una corrección de datos. La etiqueta de
-- `correct_contract_status` se agregó a `features/audit/labels.ts` en el front,
-- o la pantalla la mostraría en crudo.

begin;

with victims as (
  select id, company_id, number, status, extension_ends_at
  from public.contract
  where id in ('08749b9a-ff50-4103-a0f9-5dfd92990f84',   -- Empresa Demo Front Nº 1  (in_extension, prórroga al 16/10)
               'cf442882-8f9b-4876-baca-d6f82f1eb2d4',   -- Empresa Demo Front Nº 20 (active)
               '688a2a11-71c2-416c-a4e4-1e61a3918c05',   -- LA GRAN LEGAL Nº 28      (active) — el único de un cliente real
               '00e8d008-d68d-4052-bfc8-06557ca43aeb')   -- ZZ QA auditoría Nº 9     (active)
    and status <> 'superseded'
  for update
),
upd as (
  update public.contract c
     set status = 'superseded',
         extension_ends_at = null
    from victims v
   where c.id = v.id
  returning c.id
)
insert into public.audit_log (company_id, user_id, module, action, entity_type, entity_id, before, after)
select v.company_id,
       null,
       'contracts',
       'correct_contract_status',
       'contract',
       v.id,
       jsonb_build_object('number', v.number::text,
                          'status', v.status,
                          'extension_ends_at', v.extension_ends_at),
       jsonb_build_object('number', v.number::text,
                          'status', 'superseded',
                          'extension_ends_at', null,
                          'motivo', 'F21-10: el job nocturno y get_contract recalcularon el contrato como vivo tras ser reemplazado por una ampliacion')
  from victims v;

commit;
