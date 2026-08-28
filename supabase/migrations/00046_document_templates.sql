-- =====================================================================
-- 00046_document_templates.sql — plantillas editables de documentos.
--
-- Hoy los documentos imprimibles (contrato de empeño, y ahora paz y salvo)
-- son 100% JSX hardcodeado en el frontend — lo único configurable por
-- empresa es texto plano suelto (`company.settings.documents`). Esta tabla
-- guarda el CUERPO completo del documento como JSON estructurado
-- (ProseMirror/Tiptap), con campos dinámicos ({{cliente.nombre}}, etc.)
-- resueltos al imprimir.
--
-- A diferencia de `sale_return`/`inventory_transformation`, esta tabla NO
-- es inmutable: una plantilla se edita libremente, no es un documento de
-- negocio que ocurrió una vez. Sin `forbid_change`.
--
-- Guardar JSON estructurado (no HTML crudo) es la mitigación de seguridad:
-- el renderer del frontend solo puede emitir las etiquetas que sus nodos
-- conocidos definen, así que no hay superficie de XSS aunque cualquier
-- usuario con `company.configure` escriba lo que quiera.
--
-- Reusa el permiso `company.configure` que ya existe — es la misma
-- superficie de "cómo se ve/comunica la empresa" que header_note/logo/
-- firma, no amerita un permiso nuevo.
-- =====================================================================

create type document_type as enum ('contract', 'settlement');
-- Extensible después sin migrar filas viejas (mismo patrón ya usado varias
-- veces en este proyecto):
--   alter type document_type add value if not exists 'receipt';
--   alter type document_type add value if not exists 'closing_act';

create table public.document_template (
  id            uuid primary key default gen_random_uuid(),
  company_id    uuid not null references public.company(id),
  document_type document_type not null,
  name          text not null,
  body          jsonb not null,
  is_active     boolean not null default false,
  created_by    uuid,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index ix_document_template_company_type
  on public.document_template (company_id, document_type);

-- Una sola plantilla activa por (empresa, tipo de documento) a la vez —
-- "activar" una nueva desactiva la anterior en la misma transacción
-- (app/modules/company/service.py::activate_template), nunca deja dos
-- activas ni un hueco donde ninguna lo esté por error.
create unique index ux_document_template_one_active
  on public.document_template (company_id, document_type) where is_active;

create trigger trg_document_template_updated before update on public.document_template
  for each row execute function public.set_updated_at();

alter table public.document_template enable row level security;
alter table public.document_template force row level security;
create policy tenant_isolation on public.document_template
  using (company_id = public.current_company_id())
  with check (company_id = public.current_company_id());
