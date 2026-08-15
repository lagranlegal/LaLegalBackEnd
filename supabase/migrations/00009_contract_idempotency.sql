-- =====================================================================
-- 00009_contract_idempotency.sql — Idempotency-Key en la creación de
-- contratos (CLAUDE.md regla 4: toda operación de dinero exige
-- Idempotency-Key persistido). Gap documentado desde el paso 5: contratos
-- ya movían dinero (desembolso) sin esta garantía, a diferencia de
-- contract_payment y sale que sí la tuvieron desde su propia migración.
--
-- NULLABLE a propósito (a diferencia de contract_payment.idempotency_key
-- y sale.idempotency_key, que son NOT NULL): esta migración corre sobre
-- una tabla con filas existentes creadas antes de que el backend mandara
-- este header, y no hay forma de backfillear una key real para ellas.
-- UNIQUE(company_id, idempotency_key) con NULLs es seguro en Postgres —
-- cada NULL cuenta como distinto, así que las filas viejas no chocan
-- entre sí ni bloquean las nuevas.
-- =====================================================================

alter table public.contract add column idempotency_key text;

alter table public.contract
  add constraint contract_idempotency_key_unique unique (company_id, idempotency_key);
