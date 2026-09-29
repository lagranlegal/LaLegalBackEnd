-- =====================================================================
-- 00065_storage_perfil_propio.sql — En `perfil/` cada usuario escribe solo
-- su carpeta, y en todo el bucket solo se escriben extensiones de imagen.
--
-- Auditoría de QA, Fase 8 (28/09/2026):
--
-- F8-14. 00062 dejó `perfil` como «cualquier usuario activo» para leer Y
-- escribir, sin atar la ruta al usuario. Por la API de Storage, un Gestor sin
-- permisos de clientes subió `{empresa}/perfil/f8-….webp` con 200: cualquier
-- empleado podía reemplazar o borrar la foto de perfil de otro, incluido el
-- Admin. Desde acá la ruta de escritura es `{empresa}/perfil/{user_id}/…` y
-- `{user_id}` tiene que ser el `sub` del token. Leer sigue abierto a todo
-- usuario activo: la foto de perfil es lo que ve el resto del equipo.
--
-- F8-13. El bucket confía en el `Content-Type` que declara el cliente: un SVG
-- con `<script>` declarado `image/png` y guardado como `.svg` se aceptó. El
-- contenido (magic bytes) no se puede validar desde una política —la
-- política no ve los bytes—, así que acá va lo que sí se puede: escribir
-- exige una extensión de imagen (`.webp`, `.jpg`, `.jpeg`, `.png`, las mismas
-- de `allowed_mime_types` en 00013). El front solo arma `.webp`
-- (`uploadCompanyPhoto`), así que no cambia nada para él. Validar el
-- contenido de verdad exige que la subida pase por un paso del servidor
-- (Edge Function o backend) — anotado, no construido.
--
-- ORDEN DE DEPLOY (F8-14): el front tiene que subir la foto de perfil a
-- `perfil/{user_id}/` ANTES de aplicar esta migración en un entorno; con el
-- front viejo, subir la foto de perfil daría 403. Las fotos viejas
-- (`{empresa}/perfil/{archivo}`, sin usuario) se siguen leyendo, pero ya no
-- las puede reemplazar ni borrar nadie desde el front: quedan huérfanas
-- cuando su dueño cambie de foto. Es el costo de no poder saber, desde la
-- ruta, de quién eran.
--
-- `create or replace` conserva el dueño y los privilegios que dejaron 00062
-- y 00064 (sin EXECUTE para anon ni PUBLIC). Las políticas de
-- `storage.objects` no cambian: siguen llamando a esta función.
-- =====================================================================

create or replace function public.storage_object_allowed(
  p_bucket text, p_name text, p_write boolean
)
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  partes text[] := string_to_array(p_name, '/');
  seccion text;
begin
  if p_bucket is distinct from 'company-files' then
    return false;
  end if;
  -- `{company_id}/{sección}/{archivo}`: menos de tres partes no es una ruta
  -- que el front arme, y sin sección no hay permiso que aplicar.
  if coalesce(array_length(partes, 1), 0) < 3
     or partes[1] is distinct from public.current_company_id()::text then
    return false;
  end if;
  -- F8-13: solo se escriben nombres de imagen. Leer no lo exige, para no
  -- cerrarle el paso a lo que ya esté guardado con otro nombre.
  if p_write and lower(p_name) !~ '\.(webp|jpe?g|png)$' then
    return false;
  end if;
  seccion := partes[2];

  if seccion = 'customers' then
    return public.current_user_has_permission(
      case when p_write then 'customers.create' else 'customers.view' end);
  elsif seccion = 'contracts' then
    if p_write then
      return public.current_user_has_permission('contracts.create')
          or public.current_user_has_permission('contracts.edit');
    end if;
    return public.current_user_has_permission('contracts.view');
  elsif seccion = 'contract-items' then
    if p_write then
      return public.current_user_has_permission('contracts.create')
          or public.current_user_has_permission('contracts.edit')
          or public.current_user_has_permission('contracts.import');
    end if;
    return public.current_user_has_permission('contracts.view')
        or public.current_user_has_permission('inventory.view');
  elsif seccion = 'inventory' then
    return public.current_user_has_permission(
      case when p_write then 'inventory.create' else 'inventory.view' end);
  elsif seccion = 'expenses' then
    return public.current_user_has_permission(
      case when p_write then 'cashbox.expense' else 'cashbox.view' end);
  elsif seccion = 'company' then
    if p_write then
      return public.current_user_has_permission('company.configure');
    end if;
    return public.current_user_is_active_member();
  elsif seccion = 'perfil' then
    if p_write then
      -- F8-14: `{empresa}/perfil/{user_id}/{archivo}`, y la carpeta es la
      -- del usuario del token. Cuatro partes como mínimo: la ruta vieja de
      -- tres (sin usuario) no es de nadie y no se escribe.
      return coalesce(array_length(partes, 1), 0) >= 4
         and partes[3] = public.current_user_id()::text
         and public.current_user_is_active_member();
    end if;
    return public.current_user_is_active_member();
  end if;
  return false;
end;
$$;
