-- =====================================================================
-- 00047_document_template_layout.sql — formato visual de cada plantilla.
--
-- El editor de plantillas (00046) ya deja variar el TEXTO de un documento.
-- Este cambio agrega variar la PRESENTACIÓN: 3 identidades visuales fijas
-- (clásico/moderno/compacto) elegibles por plantilla, sin tocar el
-- contenido. Es un atributo más de `document_template`, igual que
-- `name`/`body` — no un concepto nuevo.
--
-- `default 'classic'` es intencional: cualquier plantilla ya guardada
-- queda con el formato más parecido al look de hoy, sin sorpresas.
-- =====================================================================

create type document_layout as enum ('classic', 'modern', 'compact');

alter table public.document_template
  add column layout document_layout not null default 'classic';
