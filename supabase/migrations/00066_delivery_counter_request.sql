-- =====================================================================
-- 00066_delivery_counter_request.sql — el comprobante que el cliente pide
-- en el mostrador (QA F8-07; docs/DOMINIO.md §9.2).
--
-- Decisión del dueño, como lo hacen Shopify POS o Square: al cobrar, el
-- mostrador pregunta «¿le mando el comprobante al correo?». Si el cliente
-- dice que sí, ESE comprobante sale aunque el cliente no tenga base legal
-- general (`customer.email_basis` nula): la base de ese único envío es el
-- pedido del titular, y no cambia la de ningún otro aviso (los
-- recordatorios siguen exigiendo contrato vivo o consentimiento).
--
--   legal_basis   gana el valor 'request' = lo pidió el titular en el
--                 mostrador. Solo en entregas de un comprobante pedido.
--   requested_by  quién registró el pedido (el usuario que cobró). Es la
--                 constancia: la base 'request' sin un autor no prueba nada,
--                 por eso el CHECK las amarra.
--
-- Aditiva: el código viejo nunca escribe 'request' ni lee `requested_by`,
-- así que se puede aplicar antes o después del deploy.
-- =====================================================================

alter table public.notification_delivery
  drop constraint notification_delivery_legal_basis_check;
alter table public.notification_delivery
  add constraint notification_delivery_legal_basis_check
  check (legal_basis in ('contract', 'consent', 'request'));

alter table public.notification_delivery
  add column requested_by uuid references public.app_user(id);

alter table public.notification_delivery
  add constraint notification_delivery_request_has_author
  check (legal_basis is distinct from 'request' or requested_by is not null);

comment on column public.notification_delivery.requested_by is
  'Quién registró en el mostrador que el cliente pidió este comprobante por correo '
  '(legal_basis = request). Nulo en toda entrega que no fue pedida.';
