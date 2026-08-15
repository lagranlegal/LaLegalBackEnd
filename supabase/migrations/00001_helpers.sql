-- =====================================================================
-- 00001_helpers.sql — Extensiones, funciones auxiliares y convenciones
-- Plataforma SaaS Compraventas. Todas las migraciones son idempotentes
-- hacia adelante: NUNCA editar una migración aplicada; crear una nueva.
-- =====================================================================

create extension if not exists pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- Claims del tenant.
-- PostgREST/supabase-js llenan request.jwt.claims automáticamente.
-- El backend FastAPI (vía Supavisor en modo transacción) debe fijarlos
-- POR TRANSACCIÓN:  select set_config('request.jwt.claims', :claims_json, true);
-- ---------------------------------------------------------------------
create or replace function public.current_company_id()
returns uuid
language sql stable
as $$
  select nullif(
    coalesce(
      current_setting('request.jwt.claims', true)::jsonb ->> 'company_id',
      ''
    ), ''
  )::uuid
$$;

create or replace function public.current_user_id()
returns uuid
language sql stable
as $$
  select nullif(
    coalesce(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', ''),
    ''
  )::uuid
$$;

-- Trigger genérico de updated_at
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Bloqueo genérico de UPDATE/DELETE (inmutabilidad)
create or replace function public.forbid_change()
returns trigger
language plpgsql
as $$
begin
  raise exception 'Registro inmutable: % en %', tg_op, tg_table_name
    using errcode = 'raise_exception';
end;
$$;
