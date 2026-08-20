-- =====================================================================
-- 00013_storage_buckets.sql — Bucket privado de Storage + RLS por
-- company_id (docs/STORAGE_PENDIENTE.md): el front reportó storage.buckets
-- vacío en el proyecto de dev — bloqueaba PhotoUploader (paso 7,
-- "Publicar" un artículo exige >=1 foto) y todo uso futuro de fotos
-- (cédula del cliente, contrato firmado, comprobante de gasto).
--
-- Un solo bucket privado, subcarpetas por tipo de documento dentro de
-- {company_id}/ (items/, contracts/, customers/, expenses/...). RLS reusa
-- public.current_company_id() — el mismo helper que ya usa el resto del
-- esquema (00001_helpers.sql) — porque el gateway de Storage/PostgREST de
-- Supabase fija request.jwt.claims automáticamente desde el JWT del
-- usuario en cada request, igual que para cualquier lectura React ->
-- PostgREST protegida por RLS (docs/ARCHITECTURE.md §2). El front pide la
-- URL firmada directo con supabase-js, con la sesión del usuario — no
-- hace falta un endpoint propio del backend para esto.
--
-- public=false + sin políticas anon: nada de esto es accesible sin sesión
-- autenticada, ni con URL adivinada (por eso URLs firmadas de vida corta,
-- nunca públicas — Habeas Data, Ley 1581).
-- =====================================================================

-- GUARDA DE ENTORNO. `storage` es un esquema que crea el SERVICIO de Storage
-- de Supabase, no Postgres. En un proyecto hospedado siempre existe, pero:
--   · CI aplica las migraciones contra un `postgres:15` pelado, sin Storage
--   · `supabase db reset` local falla si el contenedor de storage está caído
-- Sin esta guarda, la cadena de migraciones no se puede aplicar desde cero en
-- esos entornos y el error aparece lejos de su causa. Se salta con aviso en
-- vez de fallar: el bucket es infraestructura del ambiente, no parte del
-- esquema de negocio que los tests necesitan.
do $$
begin
  -- Se comprueba la TABLA, no el esquema: `storage` puede existir vacío (así
  -- queda si el contenedor de storage nunca arrancó) mientras `buckets` la
  -- crea el servicio. Verificar solo el esquema daba un falso positivo.
  if not exists (
    select 1 from information_schema.tables
    where table_schema = 'storage' and table_name = 'buckets'
  ) then
    raise notice 'storage.buckets ausente (CI o local sin el servicio): se omite el bucket.';
    return;
  end if;

  execute $ins$insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values (
    'company-files',
    'company-files',
    false,
    8388608,  -- 8 MB: holgado sobre una foto ya comprimida client-side
    array['image/jpeg', 'image/png', 'image/webp']
  )
  on conflict (id) do nothing$ins$;

  -- storage.objects ya tiene RLS habilitado por Supabase; solo falta la
  -- policy (sin ninguna, deniega todo por defecto — mismo bug de fondo que
  -- 00010/00011 en tablas de public).
  if not exists (
    select 1 from pg_policies
    where schemaname = 'storage' and tablename = 'objects' and policyname = 'tenant_isolation'
  ) then
    execute $pol$
      create policy tenant_isolation on storage.objects
        using (
          bucket_id = 'company-files'
          and (storage.foldername(name))[1] = public.current_company_id()::text
        )
        with check (
          bucket_id = 'company-files'
          and (storage.foldername(name))[1] = public.current_company_id()::text
        )
    $pol$;
  end if;
end $$;
