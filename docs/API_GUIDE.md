# Guía de la API — para integrar el front

> Se actualiza en cada paso del orden de implementación de `CLAUDE.md`, en la misma PR que agrega el módulo. Si un endpoint no está acá, no está implementado todavía — revisar `app/modules/*/router.py` como fuente de verdad exacta (el esquema completo y siempre actualizado vive en `/openapi.json` del servidor corriendo, ver §11).

## 1. Convenciones generales

- Base path: `/api/v1`.
- Auth: header `Authorization: Bearer <access_token>` — el `access_token` lo emite **Supabase Auth**, no este backend (ver §2).
- Content-Type: `application/json` en todo, sin excepciones.
- Dinero: siempre número decimal exacto en JSON (`"1000000.00"`, nunca float) — validado en el backend con `app/common/money.py` (`Money`, `NUMERIC(14,2)`).
- Idempotencia: los endpoints que mueven dinero exigen el header `Idempotency-Key: <string único por intento>` — reenviar el mismo valor en un reintento de red devuelve el resultado ya creado, no duplica. Generar un UUID nuevo por cada acción de usuario (no por cada request — un reintento automático debe reusar el mismo).
- Paginación: por cursor en toda lista. Query params `?cursor=<string>&limit=<int, default 50, max 200>`. Respuesta:
  ```json
  {"items": [...], "next_cursor": "base64-del-último-id-o-null"}
  ```
  Pedir la página siguiente = repetir la misma request con `cursor=<next_cursor>` de la respuesta anterior. `next_cursor: null` significa que no hay más.
- Errores: forma uniforme, ver `docs/ARCHITECTURE.md` §7 y el catálogo de códigos en §12 de este documento.

## 2. Cómo autenticarse (flujo completo para el front)

Este backend **no tiene login propio**. El front habla directo con Supabase Auth para login/logout/refresh, y le pasa el `access_token` resultante a este backend en cada request.

1. **Login** (el front llama a Supabase, no a este backend):
   ```
   POST {SUPABASE_URL}/auth/v1/token?grant_type=password
   apikey: <publishable/anon key>
   { "email": "...", "password": "..." }
   ```
   → devuelve `access_token` (JWT), `refresh_token`, `expires_in`.
2. El front guarda el `access_token` y lo manda como `Authorization: Bearer <access_token>` a **este** backend.
3. **Altas son solo por invitación** (signups públicos desactivados). El flujo es: un admin invita (`POST /api/v1/identity/invitations`, ver §4) → Supabase manda un correo con un link mágico → la persona pone su contraseña → puede hacer login normalmente. La primera vez que ese usuario le pega a cualquier endpoint del backend con un token válido, su estado pasa de `invited` a `active` automáticamente (no hace falta un endpoint de "aceptar invitación").
4. **Refresh**: `POST {SUPABASE_URL}/auth/v1/token?grant_type=refresh_token` con el `refresh_token` — maneja el front, este backend ni se entera.
5. Un JWT trae (además de lo estándar `sub`, `exp`, `aud`) los claims `company_id` y `role_id` **solo si** el usuario tiene una fila activa en `app_user` de una empresa activa (los inyecta el Custom Access Token Hook en Supabase). Si el backend responde `401 UNAUTHORIZED` con un token que por lo demás es válido, casi siempre es por esto — revisar que el usuario esté `active` y su empresa también.
6. **`GET /api/v1/me`** — llamarlo justo después del login, antes de renderizar nada. Cualquier usuario autenticado (sin exigir un permiso específico — es información sobre sí mismo):
   ```json
   {
     "user": {"id": "...", "full_name": "María Gerente", "email": "..."},
     "company": {"id": "...", "name": "Compraventa El Dorado", "timezone": "America/Bogota", "logo_url": null},
     "role": {"id": "...", "name": "Asesor"},
     "permissions": ["contracts.create", "contracts.view", "customers.create", "..."],
     "subscription": {"status": "active", "expires_at": "2027-01-01"},
     "plan": {"code": "full", "name": "Completo"}
   }
   ```
   `permissions` es exactamente el set que `require_permission` va a aceptar (mismo cache TTL 60s) — es lo que reemplaza a intentar `GET /identity/roles/{id}/permissions` (exige `identity.manage_roles`, que un Asesor no tiene) solo para que el front sepa qué botones mostrar. Usarlo para ocultar/deshabilitar acciones en vez de degradar en `403` después del click.

## 3. Módulo `platform` (solo super-admin)

Gestión de empresas/suscripciones. Nada de esto es visible ni accesible para usuarios normales de una empresa — requiere que el JWT traiga `app_metadata.platform_role == "super_admin"` (se configura manualmente en Supabase Auth, no hay self-service). Sesión de BD sin RLS (bypass intencional — es plataforma, no tenant).

| Método | Path | Descripción |
|---|---|---|
| `POST` | `/api/v1/platform/companies` | Crea una empresa: seeds 4 roles (Admin/Moderador/Asesor/Bodega) con su matriz de permisos, 1 caja principal, suscripción activa, e invita al primer admin. Body: `{name, plan_code, subscription_expires_at, first_admin_email, first_admin_full_name}`. |
| `GET` | `/api/v1/platform/companies` | Lista empresas (paginado). |
| `GET` | `/api/v1/platform/companies/{id}` | Detalle de una empresa. |
| `POST` | `/api/v1/platform/companies/{id}/suspend` | Suspende (bloquea login/API, no borra datos). |
| `POST` | `/api/v1/platform/companies/{id}/activate` | Reactiva. |
| `POST` | `/api/v1/platform/companies/{id}/subscription/extend` | Body `{new_expires_at, notes?}` → 204. |
| `GET` | `/api/v1/platform/plans` | Catálogo de planes. |

**Ejemplo — crear empresa:**
```http
POST /api/v1/platform/companies
Authorization: Bearer <token con app_metadata.platform_role=super_admin>

{
  "name": "Compraventa El Dorado",
  "plan_code": "full",
  "subscription_expires_at": "2027-01-01",
  "first_admin_email": "gerente@eldorado.com",
  "first_admin_full_name": "María Gerente"
}
```
```json
201
{
  "id": "c1...", "name": "Compraventa El Dorado", "status": "active", "created_at": "2026-08-15T...",
  "plan_code": "full", "plan_name": "Completo", "subscription_expires_at": "2027-01-01"
}
```
El admin invitado recibe un correo de Supabase Auth; hasta que no active su cuenta, aparece en `GET /api/v1/identity/users` con `status: "invited"`.

`CompanyOut` (creación, detalle y listado) siempre trae `plan_code`/`plan_name`/`subscription_expires_at` de la suscripción `active` actual — `null` los tres si la empresa no tiene ninguna suscripción activa (recién creada sin insertarla nunca, o vencida). `PlanOut` trae `modules: {"pawn": bool, "store": bool}` además de `{id, name, code, price, active}`.

## 4. Módulo `identity` (dentro de una empresa)

Todo tenant-scoped: solo ve/afecta datos de la empresa del usuario autenticado (RLS real, no un filtro que se pueda olvidar).

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/identity/users` | `identity.manage_users` | Lista usuarios de la empresa (paginado). |
| `POST` | `/api/v1/identity/invitations` | `identity.manage_users` | Invita un usuario nuevo. Body `{email, full_name, role_id}` → 201 con el usuario en `status: "invited"`. |
| `POST` | `/api/v1/identity/users/{id}/recovery-link` | `identity.manage_users` | **Enlace para volver a poner la contraseña, sin mandar correo.** Mismo mecanismo que `send_email: false` al invitar (`generate_link`, `type=recovery`): no consume cuota y el admin lo entrega a mano. Devuelve `{user_id, email, recovery_link}`. **Es una credencial de un solo uso** — quien la tenga puede cambiar esa contraseña y entrar como esa persona; queda auditado quién la generó y para quién, y el enlace NO se guarda en el `audit_log`. Rechaza usuarios inactivos (`409`): darles el enlace sería deshacer la desactivación por la puerta de atrás. |
| `PATCH` | `/api/v1/identity/users/{id}/role` | `identity.manage_users` | Reasigna de rol. Body `{role_id}`. |
| `POST` | `/api/v1/identity/users/{id}/deactivate` | `identity.manage_users` | → 204. |
| `POST` | `/api/v1/identity/users/{id}/reactivate` | `identity.manage_users` | → 204. |
| `GET` | `/api/v1/identity/roles` | `identity.manage_roles` | Lista roles de la empresa. |
| `POST` | `/api/v1/identity/roles` | `identity.manage_roles` | Crea rol. Body `{name, description?, clone_from_role_id?}` — si viene `clone_from_role_id`, copia sus permisos. |
| `PATCH` | `/api/v1/identity/roles/{id}` | `identity.manage_roles` | Renombra. Body `{name, description?}`. |
| `GET` | `/api/v1/identity/roles/{id}/permissions` | `identity.manage_roles` | Lista códigos de permiso asignados. |
| `PUT` | `/api/v1/identity/roles/{id}/permissions` | `identity.manage_roles` | Reemplaza el set completo. Body `{permission_codes: string[]}`. |
| `GET` | `/api/v1/identity/permissions` | `identity.manage_roles` | Catálogo global de permisos (referencia para armar UI de matriz). |

**Salvaguarda del último admin** (aplica a `PATCH .../role`, `.../deactivate` y `PUT .../permissions`): si la operación dejaría a la empresa sin ningún usuario activo con el permiso `identity.manage_roles`, el backend la rechaza con `409 LAST_ADMIN_SAFEGUARD` en vez de ejecutarla. El front debería mostrar esto como un error explícito, no reintentar.

**No implementado todavía** (a propósito, ver `docs/ARCHITECTURE.md`): eliminar o desactivar un rol. Los roles solo se crean, clonan, renombran y les cambian los permisos.

## 5. Módulo `customers`

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/customers` | `customers.view` | Lista clientes (paginado). `?q=texto` busca por nombre (full-text en español) **o por `doc_number`** (coincidencia exacta o por prefijo — pensado para tipear la cédula tal cual, no fragmentos como en un nombre). |
| `POST` | `/api/v1/customers` | `customers.create` | Crea cliente. Body: `{full_name, doc_type, doc_number, phone, address?, email?, doc_issue_place?, doc_photo_url?, notes?}`. `doc_type` ∈ `cc\|ce\|passport\|nit`. |
| `GET` | `/api/v1/customers/{id}` | `customers.view` | Detalle. |
| `PATCH` | `/api/v1/customers/{id}` | `customers.create` | Edición parcial (no hay `customers.edit` en el catálogo de permisos — usa el mismo que crear). No permite cambiar `doc_type`/`doc_number` (identidad del cliente). |

`doc_type` + `doc_number` es único por empresa → `409 CONFLICT` si ya existe un cliente con esos datos.

**No implementado todavía:** `status` (`active/frequent/alert`) automático — está marcado en la migración como "FASE 2" en `CLAUDE.md`; hoy todo cliente nace `active` y nadie lo cambia.

## 6. Módulo `catalogs`

Categorías (árbol de 3 niveles) y proveedores, compartidos entre Empeño y Tienda. **Lectura abierta a cualquier usuario autenticado y activo de la empresa** (no requiere `catalogs.manage`) — lo necesitan otros módulos (contratos, inventario, ventas) solo para *elegir* categoría/proveedor. Solo crear/editar requiere `catalogs.manage`.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/catalogs/categories` | `catalogs.view` | Lista **plana** (no anidada) ordenada por nivel y nombre — el front arma el árbol con `id`/`parent_id`. |
| `POST` | `/api/v1/catalogs/categories` | `catalogs.manage` | Crea categoría. Body: `{name, code_letter, parent_id?, applies_to?, default_term_months?, arrears_window_months?, max_ltv_pct?}`. `level` lo calcula el backend (`parent.level + 1`, o `1` si no hay `parent_id`) — no se manda. |
| `GET` | `/api/v1/catalogs/categories/{id}` | `catalogs.view` | Detalle. |
| `PATCH` | `/api/v1/catalogs/categories/{id}` | `catalogs.manage` | Edición parcial. **No permite reparentar** (cambiar `parent_id`) — fuera de alcance por ahora, ver `docs/ARCHITECTURE.md`. |
| `GET` | `/api/v1/catalogs/suppliers` | `catalogs.view` | Lista paginada. |
| `POST` | `/api/v1/catalogs/suppliers` | `catalogs.manage` | Crea proveedor. Body: `{name, code_letter, doc_type?, doc_number?, phone?, email?, address?, notes?}`. |
| `GET` | `/api/v1/catalogs/suppliers/{id}` | `catalogs.view` | Detalle. |
| `GET` | `/api/v1/catalogs/suppliers/{id}/summary` | `catalogs.view` | **Ficha del proveedor**: `purchase_count`, `total_purchased`, `pending_count`/`pending_total` (lo que se le debe), `first_purchase_date`/`last_purchase_date` y `product_count` (productos distintos comprados). Los totales cuentan solo `origin_type='purchase'`. |
| `GET` | `/api/v1/catalogs/suppliers/{id}/purchases` | `catalogs.view` | Historial de compras a ese proveedor, paginado por cursor. |
| `PATCH` | `/api/v1/catalogs/suppliers/{id}` | `catalogs.manage` | Edición parcial. |

Reglas de `code_letter` (1–3 caracteres, usado para armar el código de artículo — ver `CLAUDE.md`):
- Único entre **categorías hermanas** (mismo `parent_id`, incluyendo raíz — el `UNIQUE` de la migración no cubre raíz porque Postgres no compara `NULL` consigo mismo; el backend sí lo valida) → `409 CONFLICT`.
- Único por **empresa** entre proveedores (sin relación con categorías) → `409 CONFLICT`.
- **Se normaliza a mayúscula y solo admite A-Z** (00039) → `422 VALIDATION_ERROR`. El índice de unicidad distingue mayúsculas, así que sin esto un proveedor `r` y otro `R` convivían como dos distintos y generaban códigos que solo se diferencian por algo invisible en una etiqueta impresa. Nada de `Ñ` ni dígitos: el código termina escrito a mano en un buscador.
- **`R`, `P` y `T` están reservadas para PROVEEDORES** (00039) → `422 VALIDATION_ERROR`. Son las que el emisor de códigos usa como sufijo cuando no hay proveedor: remate, propio, transformado. Sin la reserva, un proveedor "Rodríguez" con letra `R` producía artículos indistinguibles de los rematados — y el remate es el caso donde el origen tiene consecuencias legales, porque esa pieza fue la prenda de un cliente. **Solo se valida al escribir**: los proveedores que ya tuvieran una de esas letras siguen funcionando, porque prohibirlas hacia atrás rompería códigos ya impresos y pegados a la mercancía.
- La reserva **no aplica a categorías**: sus letras forman el *prefijo* del código (`JOC0001`) y la de origen el *sufijo* (`-01R`), así que no colisionan y "Relojes" conserva su inicial.
- Árbol de máximo 3 niveles: crear un hijo de una categoría nivel 3 → `400 BAD_REQUEST`.

> **Los parámetros de categoría se HEREDAN.** `default_term_months`, `arrears_window_months` y `max_ltv_pct` se pueden definir en cualquiera de los tres niveles; al crear un contrato, cada campo se resuelve subiendo por `parent_id` hasta el ancestro más cercano que lo defina — **por separado**, así que una hoja puede heredar el plazo de su padre y el LTV de su abuelo. Antes se leían solo de la hoja: los campos de los niveles 1 y 2 eran configuración muerta, y olvidar el plazo en UNA hoja rompía la creación de contratos con esa prenda. Sin migración (los campos ya existían); los contratos vivos no cambian porque congelan su snapshot al nacer.

## 7. Módulo `contracts` (contratos de empeño)

Requiere una **sesión de caja abierta** (fase 1: una caja por empresa) para desembolsar o cobrar — sin eso, `409 CASH_SESSION_NOT_OPEN`. Ver §8 (`cashbox`) para abrir/cerrar la sesión.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/contracts` | `contracts.create` | Header **`Idempotency-Key` obligatorio** (reenviar la misma key en un reintento de red devuelve el mismo contrato, no duplica el desembolso — gap cerrado, antes solo `contract_payment`/`sale` lo tenían). Crea contrato: snapshot legal (tasa la define el usuario, plazo/ventana de mora salen de la categoría del artículo), desembolsa el préstamo (`cash_movement`). Body: `{customer_id, principal, interest_rate_pct, appraisal_value?, items: [{category_id, description, weight_grams?, serial_imei?, item_appraisal?, photos?}], payment_method, extension_months?, legacy_code?, notes?}`. Todos los `items` deben usar categorías **nivel 3** con el mismo `default_term_months`/`arrears_window_months`. |
| `POST` | `/api/v1/contracts/import` | `contracts.import` (solo rol Admin de fábrica) | Migración de un contrato del sistema anterior (`docs/MIGRACION_CONTRATOS.md`): se importa la **foto financiera al corte**, no la historia de abonos. Header **`Idempotency-Key` obligatorio** (recomendado: el `legacy_code`). **No exige sesión de caja abierta y no genera `cash_movement`** — el desembolso ya ocurrió en el sistema viejo (a diferencia de `POST /contracts`). Body: `{legacy_code, customer_id, principal, capital_balance, interest_rate_pct, term_months, arrears_window_months, extension_months, start_date, interest_paid_until, items: [...], appraisal_value?, signed_photo_url?, notes?}` — a diferencia de la creación normal, `term_months`/`arrears_window_months`/`extension_months` son el snapshot real del contrato viejo (no salen de la categoría, y los `items` no necesitan compartirlos). `status` se inserta `active` y pasa por el mismo recálculo que `GET /contracts/{id}` antes de responder — nunca se acepta en el body. `legacy_code` duplicado en la empresa → `409 CONTRACT_LEGACY_CODE_EXISTS`; `capital_balance ≤ 0` o `> principal` → `422 IMPORT_CAPITAL_EXCEEDS_PRINCIPAL`; `interest_paid_until` que no cae en un número entero de meses desde `start_date` → `422 IMPORT_DATES_MISALIGNED`. No se migran contratos `paid`/rematados en el sistema viejo, ni el historial de abonos (`contract_payment` es inmutable) — el saldo a favor de un interés parcial ya pagado se reconoce como descuento en el primer abono dentro de la app. |
| `GET` | `/api/v1/contracts` | `contracts.view` | Lista paginada. `?status=active\|in_arrears\|in_extension\|auctioned\|paid` filtra. `?customer_id=` filtra por cliente (agregado 27/08/2026 — mismo patrón que `?customer_id=` de `GET /sales`, §10; reemplazó el parche client-side de 200 registros que tenía el historial de contratos de un cliente). |
| `GET` | `/api/v1/contracts/{id}` | `contracts.view` | Detalle. Recalcula el estado (`active→in_arrears→in_extension`) si quedó desactualizado antes de responder — ver `docs/ARCHITECTURE.md`. |
| `PATCH` | `/api/v1/contracts/{id}` | `contracts.edit` | Solo `{appraisal_value?, notes?, signed_photo_url?}` — nunca `status`/`capital_balance` (los calcula el servicio). |
| `GET` | `/api/v1/contracts/{id}/payment-options` | `contracts.view` | Cotización: `{months_owed, monthly_interest, options: [{months, interest_amount, total, allows_capital}]}`. El front arma los botones de pago directo desde acá — nunca deja que el usuario escriba un monto de interés a mano. |
| `POST` | `/api/v1/contracts/{id}/payments` | `payments.create` (+`payments.apply_discount` si trae descuento) | Header **`Idempotency-Key` obligatorio**. Body: `{months_covered, capital_amount?, payment_method, discount_amount?, discount_reason?}`. `capital_amount` solo se acepta si `months_covered` cubre TODOS los meses adeudados — si no, `422 PAYMENT_PARTIAL_INTEREST_REJECTED`. Reenviar la misma `Idempotency-Key` devuelve el mismo abono ya creado (no duplica). |
| `GET` | `/api/v1/contracts/{id}/payments` | `contracts.view` | Historial de abonos (paginado). |
| `GET` | `/api/v1/contracts/ready-for-auction` | `contracts.auction` | Contratos en `in_extension` con la prórroga ya vencida — candidatos a Rematar. |
| `POST` | `/api/v1/contracts/{id}/auction` | `contracts.auction` | **Rematar.** Exige `status='in_extension'` y prórroga vencida (`409 CONTRACT_NOT_READY_FOR_AUCTION` si no). Crea UN `inventory_item` en `draft` por cada prenda del contrato (`origin='auction'`, `source_contract_id`), repartiendo saldo capital + intereses pendientes proporcional a `item_appraisal` de cada prenda (si ninguna tiene tasación, partes iguales — ver `docs/ARCHITECTURE.md`). Contrato y prendas quedan `auctioned`; `contract_item.inventory_item_id` guarda el vínculo **y ya sale en la respuesta** (`items[].inventory_item_id` en `ContractOut`/`GET /contracts/{id}`, `null` mientras la prenda no se remata) — es el mismo vínculo que `ItemOut.source_contract_id` visto desde el otro lado, así que se puede navegar contrato→artículo y artículo→contrato sin adivinar por nombre/descripción. Los ítems creados salen en `draft`: usa `inventory` (§9) para publicarlos. |

**No implementado todavía** (a propósito): generar el PDF imprimible del contrato con la firma de la empresa — requiere Storage + una librería de PDF, es una pieza de infra aparte. `signed_photo_url` se actualiza vía `PATCH` después de que el front suba la foto del contrato firmado a Supabase Storage por su cuenta.

**Idempotencia real:** `contract`, `contract_payment` y `sale` tienen `UNIQUE(company_id, idempotency_key)` en la migración — el dedupe de los tres es durable, no solo de API. La columna en `contract` es `NULLABLE` (a diferencia de las otras dos, que son `NOT NULL`): la migración que la agregó corrió sobre una tabla con filas ya existentes de antes de que el backend mandara este header, y no hay forma de backfillear una key real para ellas — `UNIQUE` con `NULL`s es seguro en Postgres (cada `NULL` cuenta distinto).

## 8. Módulo `cashbox`

Acto único diario de apertura/cierre, base única de efectivo (fase 1: una sola caja por empresa — ya se crea sola al dar de alta la empresa, ver `platform`). `get_open_session`/`record_movement` (usados por `contracts` para desembolsar/cobrar) viven en `app/modules/cashbox/integration.py` desde el paso anterior; esto completa el resto.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/cashbox/sessions/open` | `cashbox.open_close` | Body `{opening_balance}`. `409 CASH_SESSION_ALREADY_OPEN` si ya hay una abierta; `409 CASH_SESSION_ALREADY_CLOSED_TODAY` si la de hoy ya se cerró (un solo ciclo apertura/cierre por día calendario). |
| `GET` | `/api/v1/cashbox/sessions/current` | `cashbox.view` | La sesión abierta ahora mismo, o `404` si no hay ninguna. |
| `GET` | `/api/v1/cashbox/sessions` | `cashbox.view` | Historial paginado. |
| `GET` | `/api/v1/cashbox/sessions/{id}` | `cashbox.view` | Detalle. |
| `GET` | `/api/v1/cashbox/sessions/{id}/report` | `cashbox.view` | Desglose módulo×dirección×concepto×medio de pago + `expected_cash` calculado. Funciona tanto para una sesión abierta (vista previa antes de cerrar) como cerrada (el acta ya definitiva). |
| `POST` | `/api/v1/cashbox/sessions/{id}/close` | `cashbox.open_close` | Body `{counted_cash, difference_reason?}`. El backend calcula `expected_cash` (base + efectivo `in` − efectivo `out`, SOLO `payment_method=cash`); si `counted_cash` no coincide, `difference_reason` es obligatorio (`400` si falta — **sin tolerancia**, ni un peso). |
| `POST` | `/api/v1/cashbox/sessions/{id}/reopen` | `cashbox.reopen` | Body `{reason}`. Auditado. Rechaza si ya hay otra sesión (de otro día) abierta — cerrarla primero. |
| `GET` | `/api/v1/cashbox/expense-categories` | `cashbox.view` | Catálogo de categorías de gasto. |
| `POST` | `/api/v1/cashbox/expense-categories` | `cashbox.expense` | Body `{name}`. |
| `GET` | `/api/v1/cashbox/expenses` | `cashbox.view` | Lista paginada. `?session_id=` filtra por sesión. |
| `POST` | `/api/v1/cashbox/expenses` | `cashbox.expense` | Body `{category_id, description, amount, payment_method, module?, receipt_url?}`. Siempre contra la sesión abierta actual (no se manda `session_id`) — `409 CASH_SESSION_NOT_OPEN` si no hay ninguna. Genera su `cash_movement` (concepto `expense`) en la misma transacción; auditado (CLAUDE.md: sin aprobación adicional, basta el permiso). |

**No implementado todavía:** el acta de cierre en PDF (`cash_session.report_url`) — igual que con contratos, requiere Storage + una librería de PDF; el desglose para armarla ya está completo en `GET /sessions/{id}/report`, el front puede renderizarlo directamente mientras tanto.

**Bug real que encontré y corregí — ahora resuelto de fondo:** el pre-chequeo de "¿ya existe sesión hoy?" comparaba contra `date.today()` de Python (hora del servidor, UTC en Fly.io) mientras el `INSERT` dejaba que Postgres pusiera la fecha con su propio `current_date` (también UTC, pero un reloj distinto). Colombia es UTC-5 sin horario de verano: entre las 7pm y la medianoche hora Colombia, UTC ya está "un día adelante" — una ventana de **5 horas todos los días, en pleno horario de atención**, no un caso raro de medianoche. Fix aplicado: `app/common/tenant_time.py` + `app/modules/platform/integration.py::get_company_today` calculan "hoy" a partir de `company.settings.timezone` (default `America/Bogota`, ya venía en el esquema) en vez de la hora del servidor — usado ahora en `contracts` (meses adeudados, vencimientos, snapshot) y `cashbox` (sesión diaria) por igual. Test de regresión determinístico (con el instante fijo del bug real) en `tests/unit/test_tenant_time.py`.

**Histórico vs. el turno de hoy** (00031). `cashbox.view` alcanza para la sesión **de hoy** —abierta o ya cerrada— y su reporte; el resto es histórico y exige `cashbox.view_history`:

| Método | Path | Permiso |
|---|---|---|
| `GET` | `/api/v1/cashbox/sessions/current` | `cashbox.view` (404 si no hay ninguna abierta) |
| `GET` | `/api/v1/cashbox/sessions/today` | `cashbox.view` — la de hoy, abierta o cerrada (404 si no se ha abierto) |
| `GET` | `/api/v1/cashbox/sessions` | `cashbox.view_history` |
| `GET` | `/api/v1/cashbox/sessions/{id}` y `/report` | `cashbox.view` si es la de hoy; `cashbox.view_history` si no |
| `GET` | `/api/v1/reports/closings` | `reports.view` **+** `cashbox.view_history` |

El corte es la **fecha de la sesión**, no su estado: una sesión de hoy ya cerrada sigue siendo el turno de quien la cerró (necesita imprimir su acta) y una abierta que quedó de ayer sigue siendo la sesión en curso.

`/reports/closings` exige los dos permisos porque expone **el mismo dato** desde el módulo de reportes — quitarle el histórico al cajero por un lado y dejarle esa URL por el otro sería un control que se rodea escribiendo otra dirección.

`/sessions/today` existe para que el front pueda preguntar "¿ya cerré hoy?" con `cashbox.view`. Antes lo deducía de `/reports/closings`, así que el permiso nuevo le habría **roto la pantalla** al cajero en vez de acotarla.

## 9. Módulo `inventory`

Ítems entran en `draft` (desde un ingreso o desde un remate) y no son vendibles hasta publicarse — el código (`JOC0001I`) se emite AL PUBLICAR y es inmutable desde ahí.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/inventory/entries` | `inventory.create` | Ingreso de mercancía. `origin_type`: `purchase` \| `initial_stock` \| `adjustment_in` \| `other` (00033). Body: `{origin_type, supplier_id?, supplier_invoice?, notes?, lines: [{name, cat1_id, cat2_id, cat3_id, description?, unit_cost, quantity, photos?}]}`. `origin_type="purchase"` exige `supplier_id` y es el ÚNICO que puede llevar `payment_method` (los demás no tocan caja: `initial_stock` es lo que ya había al arrancar con el sistema, `adjustment_in` un sobrante de conteo). `origin_type="other"` exige `notes` — es un cajón de sastre y sin motivo no queda rastro de dónde salió la mercancía. Crea un `inventory_item` en `draft` por línea — costeo por identificación específica, cada uno con su propio costo (nunca promediado). `cat1_id`/`cat2_id`/`cat3_id` deben formar una rama válida del árbol (niveles 1→2→3 encadenados). |
| `GET` | `/api/v1/inventory/entries`, `/{id}` | `inventory.view` | Incluye los ítems creados por ese ingreso. Filtros: `?supplier_id=`, `?origin_type=`, `?payment_status=pending\|paid`, `?from_date=`/`?to_date=` (sobre `entry_date`), `?q=` (número o factura). **`payment_status=pending` responde "¿qué compras tengo por pagar?"** — solo cuenta compras, porque los demás orígenes no entregan plata y contarlos inflaría la deuda con proveedores. |
| `POST` | `/api/v1/inventory/exits` | `inventory.exit` | Egreso: `adjustment` \| `damage` \| `loss` \| `supplier_return` \| `internal_use`. Body: `{exit_type, reason, lines: [{item_id, quantity}]}`. Sin aprobación adicional — basta el permiso (CLAUDE.md). Descuenta `quantity`; si llega a 0, el ítem queda `written_off`. Auditado. |
| `GET` | `/api/v1/inventory/exits`, `/{id}` | `inventory.view` | Filtros: `?exit_type=`, `?from_date=`/`?to_date=`. |
| `GET` | `/api/v1/inventory/items`, `/{id}` | `inventory.view` | Filtros combinables: `?status=`, `?q=` (código por prefijo o nombre por full-text español), `?cat1_id=`/`?cat2_id=`/`?cat3_id=`, `?supplier_id=`, `?origin=supplier\|auction\|other`. |
| `PATCH` | `/api/v1/inventory/items/{id}` | `inventory.create` | Solo mientras `status='draft'` (`409` si ya se publicó) y **solo `{photos?}`**. Desde 00022/00023 el nombre, la descripción, la categoría y el precio son del **producto** y se editan con `PATCH /products/{id}`, donde el cambio aplica a todos sus lotes — editarlos por lote permitía que dos lotes del mismo producto divergieran. Las fotos sí son del lote. |
| `POST` | `/api/v1/inventory/items/{id}/publish` | `inventory.create` | Exige `sale_price` (body). La **foto solo es obligatoria si el producto es `is_unique`** (remates y piezas únicas) — ver abajo. El `sale_price` se fija en el **producto**, no en el lote. Arma el código desde las letras de `cat1`/`cat2`/`cat3` + consecutivo (`next_counter` por prefijo) + letra de proveedor (o `R` si `origin='auction'`). `draft→available`. |

**Transformación de inventario** (00037). `POST /api/v1/inventory/transformations` con `inventory.transform` + `Idempotency-Key`. Entran N artículos, salen M, y **el costo viaja**: lo que costó lo que entra es lo que cuesta lo que sale, más `extra_cost`. El costo de las salidas **no se digita**.

Cubre fundir, despiezar, armar y reparar con una sola operación — y lo que pase después con lo que sale es inventario común. `extra_cost` (lo que cobra el fundidor o el técnico) **se capitaliza**: exige `payment_method` y genera un movimiento con concepto `purchase`, no `expense`, porque es parte de producir el activo y no un gasto del mes.

Con varias salidas el costo se reparte proporcional a `estimated_value` (mismo mecanismo que el remate); sin estimaciones, en partes iguales. La **merma** no se declara: sale de la diferencia entre lo que entró y lo que se dice haber recuperado, y sube el costo unitario sola.

Consume artículos `available` **y `draft`** — fundir una prenda que nunca se publicó es el caso más común. Genera un egreso `transformation` y un ingreso `transformation` vinculados por el documento, que es **inmutable**: de una barra de oro no salen las tres cadenas otra vez. `GET /inventory/transformations/{id}` (`inventory.view`) devuelve lo consumido y lo producido juntos.

**Kardex por producto** (00040). `GET /api/v1/inventory/products/{id}/kardex` con `inventory.view`. El libro auxiliar de inventario: la historia completa de un producto en una sola línea de tiempo, con saldo de unidades y de costo corriendo.

El dato existía y la pregunta no: los movimientos viven en **tres tablas de líneas** (`inventory_entry_line`, `inventory_exit_line`, `sale_line`) indexadas por su documento porque siempre se consultaron **hacia adelante** — *dado un ingreso, qué artículos trajo*. *"¿Qué pasó con este producto?"* es la dirección contraria.

Reúne cuatro clases de movimiento (`entry`, `exit`, `sale`, `sale_void`), y **una no existe como fila**: anular una venta repone el stock pero no escribe línea inversa —`void_sale` solo cambia el `status`— así que se sintetiza. Sin eso el kardex mostraría una salida que nunca vuelve y su saldo no cuadraría contra el stock real. Su fecha sale de `updated_at`, confiable porque `void_sale` es el único `UPDATE` sobre `sale` en todo el backend.

**La valoración es POR LOTE, nunca promediada** (identificación específica, NIIF): `running_value` **no** se deriva de `running_quantity` — tres unidades valen distinto según de qué lote salgan. Por eso cada línea trae `item_id`/`item_code`.

Sin `from_date` devuelve la historia entera, al revés que `GET /accounts/{id}/statement` (últimos 30 días): en un extracto se busca conciliar el mes, en un kardex de dónde salió el saldo. Lo anterior al rango se comprime en `opening_quantity`/`opening_value`.

**Trazabilidad de vuelta** (00039). `inventory_item.source_transformation_id` es el **tercer puntero de origen**, junto a `supplier_id` y `source_contract_id`; los tres son excluyentes y dicen respectivamente que la mercancía se compró, se remató o se produjo acá. Ninguno de los tres = mercancía propia sin documento externo (inventario inicial o sobrante de conteo).

Hasta 00039 el vínculo existía solo hacia adelante: parado en el lote de oro, llegar a la fundición requería `item → línea de ingreso → ingreso → transformación`, cuatro saltos sin ningún endpoint que los recorriera. Importa porque ese oro puede venir de la prenda de un cliente, y ante un reclamo la cadena tiene que poder recorrerse hacia atrás. `ItemOut` expone el campo, y el documento se inserta **antes** de los lotes que produce (la FK lo exige; de paso el choque de `Idempotency-Key` revienta antes de tocar stock).

Con ese puntero, `publish_item` emite **`T`** de transformado en vez de la `P` genérica de "propio" — que mezclaba oro fundido con mercancía que ya estaba el día uno. **Los códigos ya emitidos no se recalculan**: son inmutables y la etiqueta impresa está pegada a la bolsa.

| `GET` | `/api/v1/inventory/transformations` | `inventory.view` | Historial paginado, **de la más reciente a la más vieja**. Filtros `from_date`/`to_date` sobre `transform_date`. Cada fila trae `reason`, `total_cost`, `extra_cost`, conteos y los nombres de producto de las dos puntas (`input_names`/`output_names`) para leerse sin abrir el detalle — **no** los `ItemOut` completos, que serían dos consultas por fila. El cursor sigue siendo el `id` y se traduce a su `number` en la consulta: `number` ordena cronológicamente, un `uuid4` no. |

**Unidad de medida y cantidad decimal** (00036). `product.unit` es un enum (`unit` | `gram` | `kilogram` | `meter` | `liter`) y `quantity` es `numeric(14,3)` en `inventory_item`, `inventory_entry_line`, `inventory_exit_line` y `sale_line` — antes era `int`, así que **no se podía vender nada por peso ni por medida**. `ItemOut` y `ProductOut` traen además `unit_abbr` (`g`, `kg`, `m`, `L`, `u`) para que todos los consumidores muestren lo mismo.

Tres reglas, todas en el servicio:
- Un producto medido en `unit` **rechaza cantidades fraccionarias** (`400`), al comprar y al vender. Media cadena no existe.
- Una línea de `POST /entries` puede traer `unit`, pero **solo se usa si CREA el producto**: si ya existe, se conserva la suya.
- `PATCH /products/{id}` rechaza cambiar `unit` si el producto **ya tiene lotes** (`409`): reinterpretaría stock y ventas ya registradas.

**La foto es del PRODUCTO, y solo obligatoria en piezas únicas** (00034). `product.photos` describe cómo se ve el producto: se toma una vez y **todos sus lotes la heredan**. `inventory_item.photos` se conserva como *override* del lote, para lo que sí es propio de una compra (una tara, el estado de una pieza rematada). `ItemOut.photos` devuelve las **efectivas**: las del lote si tiene, si no las del producto.

Publicar exige foto únicamente cuando `product.is_unique` — el caso del remate, donde la foto es la evidencia de qué prenda dejó el cliente en garantía y donde cada pieza es irrepetible. Para mercancía fungible es opcional: obligarla hacía re-fotografiar en cada reposición algo ya fotografiado. Las fotos que llegan en una línea de `POST /entries` se guardan en el **producto**.

**Pagar una compra pendiente** (`POST /api/v1/inventory/entries/{id}/pay`) exige **`inventory.pay_purchase`** (00035), no `inventory.create`. Pagarle a un proveedor mueve plata, no inventario: la mercancía ya entró, lo que cambia es el efectivo y la deuda. Antes bastaba con el permiso de registrar mercancía, o sea que bodega podía decidir cuánto sale de la caja — mismo criterio que separó `accounts.settle` y `accounts.transfer`.

**Publicación automática al ingresar.** Si una línea de `POST /entries` trae `sale_price`, el lote **se publica en el acto**: emite código y queda `available`. El precio puede omitirse si el producto ya tiene uno (reponer no obliga a redigitarlo). Sin precio queda en `draft`, que es correcto — lo que cambió es que eso ahora es la EXCEPCIÓN y no el camino obligatorio de toda compra.

**La letra final del código** sale del proveedor; `R` si es remate; y **`P` ("propio")** si no hay ninguno de los dos — inventario inicial, sobrante de conteo. Antes ese caso lanzaba `400` y la mercancía quedaba atrapada en borrador para siempre, o sea que `initial_stock` no servía para lo único que existe.

**Ojo con el precio al publicar.** El precio se manda en `publish` y aterriza en el producto; `PATCH /items/{id}` **no lo acepta**. El front tenía un diálogo que mostraba el campo "precio" junto a un botón "Guardar fotos" que solo mandaba las fotos: el precio se descartaba en silencio y había que escribirlo dos veces. Corregido — el diálogo hace ahora las dos llamadas por dentro (guardar fotos → publicar) sin que el usuario tenga que saber en qué tabla vive cada dato.

**Historial de compras de un producto.** `GET /api/v1/inventory/products/{id}/purchases` (`inventory.view`) devuelve, de la más reciente a la más vieja: fecha, proveedor, cantidad, `unit_cost` de ESA compra y si está pagada. Responde "¿cómo se movió el costo?" y "¿a quién conviene comprarle?" — la lista de productos ya insinuaba esto con el rango `min_cost`/`max_cost` pero no dejaba abrirlo. Sale de `inventory_entry_line` (que congela el costo de la compra) e incluye todos los orígenes, no solo `purchase`: un inventario inicial también explica de dónde salió el stock, y se distingue porque `supplier_name` viene en `null`.

**Vista agrupada por producto.** `GET /api/v1/inventory/products` (`inventory.view`) devuelve el inventario agrupado, con `lot_count`, `available_quantity` y el RANGO de costos entre lotes (informativo — los costos nunca se promedian). Filtros: `?q=` (SKU o nombre), `?cat1_id=`/`?cat2_id=`/`?cat3_id=`, `?supplier_id=` (productos con al menos un lote de ese proveedor), `?in_stock=true` (solo lo que tiene unidades disponibles), `?active=`, `?include_unique=` (las piezas de remate son productos de un solo lote y se excluyen por defecto). `GET /products/{id}/lots` da el detalle por lote, del más antiguo al más nuevo (FIFO); `PATCH /products/{id}` cambia nombre, descripción, precio o `active` **para todos sus lotes a la vez**.

**Los artículos de remate heredan las fotos de la prenda.** `POST /contracts/{id}/auction` copia `contract_item.photos` al `inventory_item` que crea. Antes nacía con `photos=[]`, y como publicar exige al menos una foto, toda pieza rematada quedaba bloqueada esperando que alguien volviera a fotografiar una prenda **ya fotografiada** al firmar el contrato. En una compraventa los rematados son buena parte del inventario, así que era trabajo rehecho todos los días.

## 10. Módulo `sales`

`sales.view` existe desde 00030 (derivado de `sales.create` en el otorgamiento retroactivo) y cubre los `GET`; `sales.create`/`sales.void` cada acción propia.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/sales` | `sales.create` (+`sales.apply_discount` si trae descuento) | Header **`Idempotency-Key` obligatorio**. Body: `{customer_id?, payment_method, lines: [{item_id, quantity, unit_price}], discount_amount?, discount_reason?, credit_note_id?, credit_note_amount?}`. Cada ítem debe estar `available` con `quantity` suficiente. Descuenta stock (a 0 → `sold`); `cash_movement(concept='sale', direction='in', module='store')` **solo por lo que queda por cobrar en efectivo/cuenta** — si `credit_note_id` viene, redime esa nota crédito (00043) por `min(saldo, total)` o por `credit_note_amount` si se especifica, y el movimiento de caja sale por la diferencia (`0` si la nota cubre el total entero: no exige caja abierta, igual que una venta 100% descontada). La nota debe ser del mismo `customer_id` de la venta. Acepta `account_id` opcional (§13); **solo exige sesión de caja abierta si el cobro en efectivo/cuenta cae en una cuenta `cash`** (`409 CASH_SESSION_NOT_OPEN`). Reenviar la misma `Idempotency-Key` devuelve la misma venta (no duplica ni vuelve a descontar stock ni a redimir la nota otra vez). |
| `GET` | `/api/v1/sales`, `/{id}` | `sales.view` | `GET /sales` acepta `?customer_id=` y `?status=completed\|voided`. `SaleOut` trae `account_id` y `credit_note_redeemed_amount` (`null` si no se usó nota crédito). |
| `POST` | `/api/v1/sales/{id}/void` | `sales.void` | Body `{reason}` (obligatorio). Repone stock de cada línea, `cash_movement` contrario (`direction='out'`), auditado. `409` si la venta ya estaba anulada. Distinto de una devolución (abajo): anular es "esto no debió pasar", mismo día, todo o nada. |

### Devolución de cliente (00042-00045) y nota crédito (00043)

La venta ocurrió, hubo ingreso, y días o semanas después sale plata (o un compromiso de plata) — por eso es un evento propio, no una variante de `void`. Soporta devolución **parcial** (una o varias líneas, cantidad parcial de una línea).

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/sales/{sale_id}/returns` | `sales.return` | Header **`Idempotency-Key` obligatorio**. Body: `{lines: [{sale_line_id, quantity, restock?}], reason: defect\|change_of_mind\|other, settlement_method: cash\|credit_note, customer_id?, notes?}`. `customer_id` se hereda de la venta si la tenía; obligatorio si `settlement_method='credit_note'` y la venta era de mostrador. Por línea: si el lote sigue `sold`/`available` (nadie lo tocó desde la venta) se reabre el MISMO lote; si ya no (`written_off` u otro estado — se transformó, se dio de baja) se crea un lote nuevo con letra de código `D`, al costo ya congelado en la línea de venta. `restock=false` (default `true`) es una devolución puramente financiera, sin reingreso de stock. `cash`: contra-movimiento en la sesión de caja **de hoy** (no la de la venta original, que puede estar en un cierre ya cerrado), `409 CASH_SESSION_NOT_OPEN` si no hay una abierta. `credit_note`: no toca caja, emite una nota crédito. **`400 SALE_ACCOUNT_NOT_SETTLED`** si `settlement_method='cash'` y la venta se cobró por una cuenta `settlement` (Sistecrédito) todavía sin liquidar — devolver en efectivo sacaría plata que el negocio nunca recibió. **`400 RETURN_TIME_LIMIT_EXCEEDED`** si pasó el plazo configurado (`company.settings.return_window_days`, default 30, `0`=sin límite) y el actor no tiene `sales.return_override_time_limit`; con el permiso, pasa igual y `time_limit_warning=true` en la respuesta (advierte, nunca bloquea duro). Excede lo disponible de una línea → `400` con `details.available`. |
| `GET` | `/api/v1/sales/{sale_id}/returns`, `/{return_id}` | `sales.view` | `SaleReturnOut.total_amount` se deriva de las líneas × precio de venta, nunca guardado. `credit_note_id` viene si emitió nota. |
| `GET` | `/api/v1/credit-notes` | `sales.view` | `?customer_id=`, paginado por cursor. `CreditNoteOut.redeemed_amount`/`balance` se derivan de `credit_note_redemption` en cada lectura — nunca una columna guardada (mismo patrón que §12 cuentas por pagar). |
| `GET` | `/api/v1/credit-notes/{id}` | `sales.view` | Una nota puntual, mismo shape. |

## 11. Módulo `audit`

Solo lectura sobre `audit_log` (inmutable — la insertan los demás módulos en su propia transacción, nunca este). Paginado por cursor, más reciente al final.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/audit-log` | `audit.view` | `?module=`, `?entity_type=`, `?entity_id=`, `?user_id=` filtran (todos opcionales, combinables). Cada entrada trae `{user_id, module, action, entity_type, entity_id, before, after, created_at}` — `before`/`after` son el detalle que cada módulo decidió auditar (no un diff genérico de fila completa). |

## 12. Módulo `reports`

Solo lectura, agrega datos que ya existen en otros módulos — no muta nada. `GET /dashboard` usa la zona horaria de la empresa (`platform.integration.get_company_timezone`) para que "ventas de hoy" y "ventas del mes" sean el día/mes calendario de Colombia, no UTC (misma regla del §10 de `ARCHITECTURE.md`).

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/reports/dashboard` | `reports.view` | KPIs de un vistazo: `contracts` (conteo por estado `active`/`in_arrears`/`in_extension`/`auctioned`, `ready_for_auction_count` = en prórroga y ya vencida, `capital_outstanding` = suma de `capital_balance` de los contratos vivos), `sales` (`today_total`/`today_count`/`month_total`, solo ventas `completed`), `inventory` (`available_count`/`available_value` = costo×cantidad de lo `available`, `draft_count`), `cashbox` (si hay sesión `open` ahora mismo, y sus datos básicos). Refleja el `status` persistido de cada contrato (recalculado on-read en cada `GET /contracts/{id}` y por el job nocturno — no vuelve a recalcular todo el libro en cada llamada al dashboard). |
| `GET` | `/api/v1/reports/closings` | `reports.view` | Histórico de cierres de caja (`status='closed'`), paginado por cursor. `?from_date=`/`?to_date=` filtran por `session_date`. Trae `{session_id, session_date, opening_balance, expected_cash, counted_cash, difference, difference_reason, closed_by, closed_at}` — el mismo desglose módulo×concepto×medio de una sesión puntual sigue viviendo en `GET /cashbox/sessions/{id}/report` (éste es el listado, aquél el detalle). |

**Reportes contables** (Tanda D). Los tres son una **foto de hoy**, no un resumen de un rango, y por eso no llevan `from_date`/`to_date`: "¿cuánto debo?" no tiene versión "en marzo".

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/reports/income-statement` | `reports.view` | **Estado de resultados** del período (`?from_date=`/`?to_date=`): ingresos (ventas netas + intereses) − costo de ventas − gastos = utilidad, con `margin_pct` (`null` si no hubo ingresos). Reusa `profit_summary` y `pawn_performance`, así que no duplica reglas. Sale de los **documentos** y no de los movimientos de caja: el desglose de caja solo cubre sesiones cerradas, y una venta a crédito es ingreso aunque la plata no haya entrado. Devuelve además `inventory_purchased`, `capital_disbursed` y `capital_recovered` **fuera** del resultado — prestar no es gasto, cobrar no es ganancia, comprar inventario es convertir efectivo en activo. |
| `GET` | `/api/v1/reports/payables` | `reports.view` | Cuentas por pagar a proveedores, agrupadas y con antigüedad `days_0_30` / `days_31_60` / `days_over_60`. La antigüedad se mide desde `entry_date` (la fecha desde la que el proveedor cuenta el plazo). Solo cuenta `origin_type='purchase'`: los demás orígenes no entregan plata y contarlos inflaría la deuda. Un proveedor sin asignar aparece igual, agrupado como "Sin proveedor asignado". |
| `GET` | `/api/v1/reports/inventory-valuation` | `reports.view` | Valor del inventario **al costo**, con desglose por categoría de primer nivel. Solo `status='available'`. `retail_value` va aparte y **no es el valor del inventario** — es lo que se cobraría vendiendo todo hoy. `potential_profit` puede ser **negativa** (mercancía por debajo del costo) y se devuelve así a propósito. |
| `GET` | `/api/v1/reports/stale-inventory` | `reports.view` | Mercancía disponible sin rotación. `?threshold_days=` (default 90) y `?limit=`. Se mide sobre el lote **más antiguo todavía disponible**: una reposición reciente no debe esconder la pieza vieja. |

## 13. Módulo `accounts` (catálogo de cuentas)

Dónde está la plata, separado de **cómo** se cobró (`payment_method`). Ver `docs/ARCHITECTURE.md` §12 para el porqué del modelo. Tres tipos: `cash` (el cajón), `bank` (banco/Nequi/Daviplata) y `settlement` (un convenio que te debe — Sistecrédito).

El **saldo se deriva** de `cash_movement`, nunca se guarda, y se calcula distinto según el tipo: una `cash` reporta lo que debería haber en el cajón *ahora* (base de la sesión abierta + movimientos de esa sesión, `0.00` si no hay sesión); una `bank` o `settlement` reporta `opening_balance` + el acumulado histórico.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/accounts` | `accounts.view` | Lista con saldo. `?include_inactive=true` para ver también las desactivadas. |
| `POST` | `/api/v1/accounts` | `accounts.manage` | Body `{name, type, reference?, is_default?, opening_balance?}`. Marcar `is_default` desmarca la anterior de ese tipo (hay un índice único parcial). |
| `PATCH` | `/api/v1/accounts/{id}` | `accounts.manage` | Renombrar, cambiar `reference`, `is_default` o `active`. El **tipo no se edita**: cambiarlo reinterpretaría todos los movimientos históricos de la cuenta. |
| `GET` | `/api/v1/accounts/{id}/statement` | `accounts.view` | **Extracto** de la cuenta (`?from_date=`/`?to_date=`): saldo inicial, cada movimiento con su saldo corriente y saldo final, del más viejo al más nuevo. Para conciliar contra el extracto real del banco. En cuentas de **efectivo** `has_running_balance: false` y los saldos en `null` — la base del cajón se redeclara en cada apertura y no es un movimiento, así que acumular el histórico no daría un saldo; ahí la verificación es el arqueo. Los movimientos se devuelven igual. |
| `POST` | `/api/v1/accounts/{id}/settle` | `accounts.settle` + `Idempotency-Key` | Liquidar un convenio. Body `{to_account_id, amount_settled, amount_received, notes?}`. Devuelve `{settled, received, commission, commission_pct, new_pending_balance}`. Genera dos movimientos (sale de la `settlement`, entra a la destino). La comisión se **deriva** (`amount_settled − amount_received`) y **no genera movimiento propio**: no es plata que salió, es plata que nunca llegó. |

**Cuál cuenta se usa.** Todas las operaciones de dinero (`POST /sales`, `/contracts`, `/contracts/{id}/payments`, `/cashbox/expenses`, `/inventory/entries`, `/inventory/entries/{id}/pay`) aceptan `account_id` opcional. Si no viene, se usa la predeterminada del tipo que implica el `payment_method` (`cash` → la `cash` por defecto; `transfer`/`other` → la `bank` por defecto).

**Quién exige sesión de caja.** El **tipo de cuenta**, no la operación: solo un movimiento sobre una cuenta `cash` necesita el cajón abierto (`409 CASH_SESSION_NOT_OPEN`). Una venta por Sistecrédito o una transferencia no pasa por el cajón y no se bloquea si nadie abrió caja.

**Una cuenta `settlement` NO puede pagar** (`400 ACCOUNT_CANNOT_FUND_PAYMENT`). Es una cuenta **por cobrar**: representa plata que un convenio todavía te debe, no un saldo disponible. Toda operación que saca dinero — `POST /cashbox/expenses`, `POST /inventory/entries` pagada en el acto, `POST /inventory/entries/{id}/pay`, y el desembolso de `POST /contracts` — la rechaza como origen. Cobrar *hacia* una `settlement` sigue siendo válido y es justamente para lo que existe.

> El bug que motivó la regla salió en uso real: el selector de cuenta del front filtraba solo por medio de pago (`other`) sin mirar la dirección del movimiento, así que al registrar una compra ofrecía Sistecrédito como fuente de pago. El front ya no la ofrece, pero la validación vive acá porque la UI oculta y no protege (`CLAUDE.md` regla 7). La única salida legítima de una cuenta por cobrar es su **liquidación**, que tiene endpoint propio y no pasa por esta validación.

**Traslados entre cuentas propias** (00032). `POST /api/v1/accounts/transfers` con `accounts.transfer` + `Idempotency-Key`. Body `{from_account_id, to_account_id, amount, transfer_date?, notes?}`; devuelve el traslado con los saldos resultantes de ambas cuentas. `GET /api/v1/accounts/transfers` lista el histórico con `accounts.view`.

El caso real es **consignar en el banco el efectivo del día**, y antes no existía: solo quedaba registrarlo como gasto (que falsea la utilidad por casi toda la caja del día) o no registrarlo (y entonces el saldo del banco queda mentiroso y el efectivo esperado del día siguiente, inflado). **Un traslado no es ingreso ni egreso: es la misma plata en otro bolsillo**, así que no toca el estado de resultados.

Genera dos movimientos con conceptos **propios** `transfer_out` / `transfer_in` (módulo `general`) — no `adjustment`, que significa "el sistema no cuadra con la realidad" cuando acá sí cuadra. Los reportes los excluyen del cálculo de ingresos, gastos y flujo; el arqueo **sí** los cuenta, que es lo correcto: si consignaste, esos billetes ya no están en el cajón.

Reglas: origen ≠ destino; **ninguna de las dos puede ser `settlement`** (no se saca plata que aún te deben, ni se "consigna" hacia una deuda ajena — para eso está la liquidación, que además calcula la comisión); no se puede trasladar más de lo disponible; la fecha nunca es futura. Si toca efectivo **exige caja abierta** (`409 CASH_SESSION_NOT_OPEN`) y por eso va **antes** del cierre: una sesión cerrada es inmutable.

**Alta de empresa.** Cada empresa nueva nace **solo con `Caja principal`** (`cash`, default). Antes se sembraban también `Transferencias` y `Otros medios`, que eran un artefacto de la migración 00024: existían para mapear el enum viejo de medios de pago al catálogo nuevo y no perder el histórico de las empresas que ya estaban. Una empresa nueva no tiene historia que mapear, y el módulo existe para responder **dónde** está la plata — cosa que un nombre como "Transferencias" no hace. Las bancarias las crea el dueño con el nombre de su banco. Si alguien registra una transferencia antes de haber creado ninguna, se crea una al vuelo como red de seguridad: perder el registro de un movimiento de dinero sería peor que crear una cuenta implícita.

**Permisos propios, no prestados** (migración 00029). El módulo nació reusando `cashbox.view` y `company.configure`, y eso tenía dos defectos: no se podía dar acceso a cuentas sin dar toda la caja, ni administrarlas sin dar también logo, firma y documentos — o sea que el módulo **no era parametrizable** desde la matriz de roles. Y peor: `settle` **mueve plata** pero exigía `cashbox.view`, un permiso de solo lectura, así que cualquiera que pudiera mirar la caja podía liquidar Sistecrédito. Ahora son tres (`accounts.view` / `accounts.manage` / `accounts.settle`, este último `is_special`), y la separación sigue el mismo criterio del resto del catálogo: ver, administrar, y la acción sensible aparte.


## 14. Esquema completo y tipos para el front

El backend expone OpenAPI 3.1 completo y siempre sincronizado con el código real (generado por FastAPI, no de mantenimiento manual):

- Interactivo: `GET /docs` (Swagger UI) — útil para probar a mano.
- Máquina: `GET /openapi.json`.
- Sin servidor corriendo (útil en CI del front): `python scripts/export_openapi.py openapi.json` en este repo.

Para generar tipos TypeScript desde el front (con el backend corriendo local o apuntando al de dev):
```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.ts
# o, sin servidor corriendo, contra un archivo ya exportado:
npx openapi-typescript openapi.json -o src/types/api.ts
```
Esta tabla de este documento describe **intención y reglas de negocio** (qué hace cada endpoint, por qué puede fallar); el **shape exacto** de request/response (campos, tipos, opcionalidad) siempre sale de `/openapi.json`, nunca de acá — si alguna vez quedan desincronizados, el OpenAPI manda.

## 15. Catálogo de códigos de error usados hasta ahora

| `code` | HTTP | Cuándo |
|---|---|---|
| `UNAUTHORIZED` | 401 | Sin token, token inválido/expirado, o usuario/empresa inactivos. |
| `PERMISSION_DENIED` | 403 | Token válido pero el rol no tiene el permiso requerido. |
| `SUBSCRIPTION_EXPIRED` | 402 | La empresa no tiene suscripción activa. |
| `NOT_FOUND` | 404 | El recurso no existe (o no pertenece a tu empresa — mismo código, no se revela cuál). |
| `CONFLICT` / `LAST_ADMIN_SAFEGUARD` | 409 | Ver salvaguarda del último admin arriba. |
| `CASH_SESSION_NOT_OPEN` | 409 | Se intentó desembolsar/cobrar/registrar un gasto sin una sesión de caja abierta. |
| `CASH_SESSION_ALREADY_OPEN` | 409 | Se intentó abrir una sesión (o reabrir una) habiendo ya otra abierta para esa caja. |
| `CASH_SESSION_ALREADY_CLOSED_TODAY` | 409 | Se intentó abrir una sesión el mismo día en que ya se cerró una (un solo ciclo diario). |
| `PAYMENT_PARTIAL_INTEREST_REJECTED` | 422 | Abono con `capital_amount` sin cubrir todos los meses de interés adeudados. |
| `CONTRACT_CLOSED` | 400 | Abono sobre un contrato ya `paid`/`auctioned`. |
| `CONTRACT_NOT_READY_FOR_AUCTION` | 409 | Se intentó Rematar un contrato que no está en `in_extension` con la prórroga vencida. |
| `CONTRACT_LEGACY_CODE_EXISTS` | 409 | `POST /contracts/import` con un `legacy_code` que ya existe en la empresa. |
| `IMPORT_CAPITAL_EXCEEDS_PRINCIPAL` | 422 | `POST /contracts/import` con `capital_balance ≤ 0` o `capital_balance > principal`. |
| `IMPORT_DATES_MISALIGNED` | 422 | `POST /contracts/import` con `interest_paid_until` que no cae en un número entero de meses completos desde `start_date`. |
| `ACCOUNT_CANNOT_FUND_PAYMENT` | 400 | Se intentó pagar (gasto, compra, desembolso) o trasladar desde una cuenta `settlement`. Es plata por cobrar, no un saldo disponible. |
| `SALE_ACCOUNT_NOT_SETTLED` | 400 | Devolución en efectivo sobre una venta cobrada por una cuenta `settlement` (Sistecrédito) todavía sin liquidar. |
| `RETURN_TIME_LIMIT_EXCEEDED` | 400 | Devolución pasado `company.settings.return_window_days`, sin el permiso `sales.return_override_time_limit`. |
| `CREDIT_NOTE_INSUFFICIENT_BALANCE` | 400 | `POST /sales` con `credit_note_id` cuyo saldo no alcanza el monto solicitado. |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | Falta el header `Idempotency-Key` en un endpoint de dinero. |
| `VALIDATION_ERROR` | 422 | Body no cumple el schema Pydantic — `details.errors` trae el detalle campo por campo. |
| `BAD_REQUEST` | 400 | Catch-all de reglas de negocio sin código más específico (p. ej. códigos de permiso inexistentes al armar una matriz de rol, categorías con distinto plazo en un mismo contrato, descuadre de caja sin justificación, stock insuficiente). |

## 16. Qué falta

Con `audit` + `reports` + el job nocturno, todo el núcleo operativo de `CLAUDE.md` (`platform` → `identity` → `customers`/`catalogs` → `contracts` → `cashbox` → `inventory`/`sales` → `audit`/`reports` → job nocturno) está completo, más lo agregado después: `company` (§4 bis), el modelo **producto + lote** (el precio vive en el producto, el costo en el lote) y el **catálogo de cuentas** (§13). El backend no tiene trabajo funcional pendiente — ver `docs/ARCHITECTURE.md` §11 para el detalle del job (`app/jobs/nightly.py`). Queda pendiente, fuera del alcance funcional del backend:

- **Desplegar `prod` en Fly.io**: `dev` ya está en producción de pruebas — `https://compraventa-backend-dev.fly.dev`, ver `docs/ARCHITECTURE.md` §8. `prod` usa el mismo `Dockerfile` + `fly.prod.toml`, pero necesita su propio proyecto Supabase (hoy solo existe el de `dev`) antes de poder desplegarse — no reusar el de `dev` para datos reales.
- **PDFs** (contrato firmado, acta de cierre de caja): requieren Storage + una librería de PDF, fuera de alcance por decisión explícita en los pasos 5 y 6 — el front puede armar ambos con los datos que ya expone la API mientras tanto.
- **Costeo FIFO por lote** para accesorios de bajo valor: por decisión explícita en el paso 7, todo `inventory_item` usa identificación específica (su propio costo real); FIFO por lote queda como optimización futura.

**Backlog explícito del front** (pedido durante la integración, deliberadamente pospuesto — no bloquean el arranque):
- **Pantalla de cuentas** (§13): listado con saldo, alta/edición, y el selector de cuenta en cada punto de cobro. Hoy el backend resuelve la predeterminada cuando el front no manda `account_id`, así que todo funciona sin la pantalla — pero sin ella no hay forma de liquidar un convenio ni de ver cuánto debe Sistecrédito.
- **`GET /reports/series?months=12`**: serie histórica mensual de ingresos (empeño/tienda) para la gráfica principal del dashboard. Por ahora `GET /reports/dashboard` (§12) cubre hoy/mes — suficiente para arrancar.
