-- =====================================================================
-- 00050_customer_doc_photos.sql — Un documento tiene dos caras
--
-- POR QUÉ: `customer.doc_photo_url` es UNA sola foto, y una cédula tiene
-- frente y reverso. Reportado por Mateo probando con el cliente: al
-- registrar a alguien solo se puede subir una cara.
--
-- POR QUÉ UN ARREGLO Y NO UNA SEGUNDA COLUMNA (`doc_photo_back_url`):
--
--   · Es el patrón que el proyecto ya usa tres veces para exactamente esto
--     — `contract_item.photos`, `inventory_item.photos`, `product.photos`,
--     las tres `jsonb not null default '[]'`. Una cuarta forma de guardar
--     fotos sería una cuarta cosa que aprender.
--   · Generaliza sin adivinar: una cédula tiene dos caras, un pasaporte
--     una, un RUT puede tener más. "Frente" y "reverso" son el ORDEN, no
--     dos campos distintos — el `PhotoUploader` ya sabe reordenar.
--   · El front ya trabaja con arreglos de rutas de Storage en ese
--     componente: hoy `CustomerFormDialog` envuelve el valor único en un
--     arreglo de uno y lo desenvuelve al guardar, justamente porque el
--     componente pide una lista.
--
-- EXPANDIR / CONTRAER: esta migración solo AGREGA y copia. `doc_photo_url`
-- se conserva y se sigue escribiendo, para que un bundle viejo del front
-- —o el backend anterior, si el despliegue queda a medias— siga viendo la
-- foto del frente. La columna se elimina en una migración posterior, una
-- vez desplegadas las dos puntas.
-- =====================================================================

alter table public.customer
  add column if not exists doc_photos jsonb not null default '[]';

-- La foto que ya existía es, por definición, la primera: nadie sube el
-- reverso sin el frente.
update public.customer
set doc_photos = jsonb_build_array(doc_photo_url)
where doc_photo_url is not null
  and doc_photos = '[]'::jsonb;

comment on column public.customer.doc_photos is
  'Fotos del documento de identidad, en orden: [frente, reverso, ...]. Rutas de Storage, no URLs. Reemplaza a doc_photo_url, que se conserva sincronizada con el primer elemento hasta que se contraiga.';

comment on column public.customer.doc_photo_url is
  'DEPRECADO (00050): usar doc_photos. Se mantiene sincronizada con doc_photos[0] durante la transición.';
