-- =====================================================================
-- 00055_keep_anchor_for_live_contracts.sql — que el arreglo de 00053
-- sirva HOY, y no solo para los contratos que nazcan de ahora en
-- adelante.
--
-- EL PROBLEMA QUE DEJÓ 00053. `extension_interest_policy` es SNAPSHOT y
-- el default nuevo (`keep_anchor`) solo aplica al INSERT, así que los
-- contratos que ya existían siguieron en `forgive`. Consecuencia: el
-- desfase que reportó el cliente —un recargo el día 25 corre la fecha de
-- cobro al 25— seguiría pasando en todos ellos hasta que se cerraran, que
-- es exactamente el problema que 00053 vino a resolver.
--
-- POR QUÉ ESTO NO VIOLA EL SNAPSHOT, que es la regla que sostiene media
-- app. El snapshot protege **lo que el cliente firmó**: la tasa, el plazo,
-- la ventana de mora, los meses de prórroga. Cambiarlos después sería
-- alterar la obligación.
--
-- `extension_interest_policy` no está en el papel. No dice cuánto debe el
-- cliente ni cuándo vence: dice cómo se construye un contrato FUTURO que
-- todavía no existe y que el cliente va a firmar aparte. Y además nadie la
-- eligió nunca — era un default de columna, no una decisión de negocio de
-- ninguna empresa.
--
-- SOLO LOS CONTRATOS VIVOS. `paid`, `auctioned` y `superseded` son
-- terminales y `extend_loan` los rechaza con `CONTRACT_CLOSED` antes de
-- mirar la política, así que actualizarlos no cambiaría ningún
-- comportamiento — solo tocaría filas de documentos terminados. El
-- proyecto ya eligió no hacer eso en otros lados.
--
-- IDEMPOTENTE: el `where` excluye las filas que ya están en el valor
-- nuevo, así que volver a correrla no escribe nada.
-- =====================================================================

update public.contract
set extension_interest_policy = 'keep_anchor'
where status in ('active', 'in_arrears', 'in_extension')
  and extension_interest_policy = 'forgive';
