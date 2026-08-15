-- =====================================================================
-- 00004_customers_catalogs.sql — Clientes, categorías (árbol 3 niveles)
-- y proveedores. Catálogos compartidos entre Empeño y Tienda.
-- =====================================================================

create type doc_type as enum ('cc', 'ce', 'passport', 'nit');
create type customer_status as enum ('active', 'frequent', 'alert');
create type category_applies as enum ('pawn', 'store', 'both');

create table public.customer (
  id              uuid primary key default gen_random_uuid(),
  company_id      uuid not null references public.company(id),
  full_name       text not null,
  doc_type        doc_type not null,
  doc_number      text not null,
  doc_issue_place text,
  address         text,
  phone           text not null,
  email           text,
  doc_photo_url   text,
  status          customer_status not null default 'active',  -- automático: FASE 2
  alert_reason    text,
  notes           text,
  created_by      uuid,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (company_id, doc_type, doc_number)
);
create trigger trg_customer_updated before update on public.customer
  for each row execute function public.set_updated_at();
create index ix_customer_company on public.customer (company_id);
create index ix_customer_name on public.customer using gin (to_tsvector('spanish', full_name));

-- ---------------------------------------------------------------------
-- Categorías: árbol FIJO de 3 niveles, todo dinámico por empresa.
-- code_letter forma el código del artículo (JOC0001I).
-- DECIDIDO: seeds recomendados — metales term=4/ventana=4, LTV oro 70%
-- plata 60%; tecnología term=1/ventana=1/LTV 40%. Editables por admin.
-- Los contratos existentes conservan su SNAPSHOT (ver 00005).
-- ---------------------------------------------------------------------
create table public.category (
  id                    uuid primary key default gen_random_uuid(),
  company_id            uuid not null references public.company(id),
  parent_id             uuid references public.category(id),
  level                 int not null check (level between 1 and 3),
  name                  text not null,
  code_letter           text not null check (char_length(code_letter) between 1 and 3),
  applies_to            category_applies not null default 'both',
  default_term_months   int,          -- plazo por defecto del contrato
  arrears_window_months int,          -- ventana de mora (meses de interés antes de prórroga)
  max_ltv_pct           numeric(5,2), -- % máximo de préstamo sobre tasación (advertencia)
  active                boolean not null default true,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (company_id, parent_id, code_letter),
  unique (company_id, parent_id, name)
);
create trigger trg_category_updated before update on public.category
  for each row execute function public.set_updated_at();

-- El nivel debe ser exactamente parent.level + 1 (raíz = 1)
create or replace function public.check_category_level()
returns trigger
language plpgsql
as $$
declare
  v_parent_level int;
begin
  if new.parent_id is null then
    if new.level <> 1 then
      raise exception 'Una categoría sin padre debe ser nivel 1';
    end if;
  else
    select level into v_parent_level from public.category where id = new.parent_id;
    if v_parent_level is null then
      raise exception 'Categoría padre inexistente';
    end if;
    if new.level <> v_parent_level + 1 then
      raise exception 'Nivel inválido: el padre es nivel %', v_parent_level;
    end if;
    if new.level > 3 then
      raise exception 'El árbol es de máximo 3 niveles';
    end if;
  end if;
  return new;
end;
$$;
create trigger trg_category_level before insert or update on public.category
  for each row execute function public.check_category_level();

create table public.supplier (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references public.company(id),
  name        text not null,
  doc_type    doc_type,
  doc_number  text,
  phone       text,
  email       text,
  address     text,
  code_letter text not null check (char_length(code_letter) between 1 and 3),
  notes       text,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (company_id, code_letter)
);
create trigger trg_supplier_updated before update on public.supplier
  for each row execute function public.set_updated_at();

-- RLS (patrón estándar de tenant)
alter table public.customer enable row level security;
alter table public.customer force row level security;
create policy tenant_isolation on public.customer
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

alter table public.category enable row level security;
alter table public.category force row level security;
create policy tenant_isolation on public.category
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());

alter table public.supplier enable row level security;
alter table public.supplier force row level security;
create policy tenant_isolation on public.supplier
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());
