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
{"id": "c1...", "name": "Compraventa El Dorado", "status": "active", "created_at": "2026-08-15T..."}
```
El admin invitado recibe un correo de Supabase Auth; hasta que no active su cuenta, aparece en `GET /api/v1/identity/users` con `status: "invited"`.

## 4. Módulo `identity` (dentro de una empresa)

Todo tenant-scoped: solo ve/afecta datos de la empresa del usuario autenticado (RLS real, no un filtro que se pueda olvidar).

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/identity/users` | `identity.manage_users` | Lista usuarios de la empresa (paginado). |
| `POST` | `/api/v1/identity/invitations` | `identity.manage_users` | Invita un usuario nuevo. Body `{email, full_name, role_id}` → 201 con el usuario en `status: "invited"`. |
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
| `GET` | `/api/v1/customers` | `customers.view` | Lista clientes (paginado). `?q=texto` busca por nombre (full-text en español). |
| `POST` | `/api/v1/customers` | `customers.create` | Crea cliente. Body: `{full_name, doc_type, doc_number, phone, address?, email?, doc_issue_place?, doc_photo_url?, notes?}`. `doc_type` ∈ `cc\|ce\|passport\|nit`. |
| `GET` | `/api/v1/customers/{id}` | `customers.view` | Detalle. |
| `PATCH` | `/api/v1/customers/{id}` | `customers.create` | Edición parcial (no hay `customers.edit` en el catálogo de permisos — usa el mismo que crear). No permite cambiar `doc_type`/`doc_number` (identidad del cliente). |

`doc_type` + `doc_number` es único por empresa → `409 CONFLICT` si ya existe un cliente con esos datos.

**No implementado todavía:** `status` (`active/frequent/alert`) automático — está marcado en la migración como "FASE 2" en `CLAUDE.md`; hoy todo cliente nace `active` y nadie lo cambia.

## 6. Módulo `catalogs`

Categorías (árbol de 3 niveles) y proveedores, compartidos entre Empeño y Tienda. **Lectura abierta a cualquier usuario autenticado y activo de la empresa** (no requiere `catalogs.manage`) — lo necesitan otros módulos (contratos, inventario, ventas) solo para *elegir* categoría/proveedor. Solo crear/editar requiere `catalogs.manage`.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/catalogs/categories` | ninguno (autenticado) | Lista **plana** (no anidada) ordenada por nivel y nombre — el front arma el árbol con `id`/`parent_id`. |
| `POST` | `/api/v1/catalogs/categories` | `catalogs.manage` | Crea categoría. Body: `{name, code_letter, parent_id?, applies_to?, default_term_months?, arrears_window_months?, max_ltv_pct?}`. `level` lo calcula el backend (`parent.level + 1`, o `1` si no hay `parent_id`) — no se manda. |
| `GET` | `/api/v1/catalogs/categories/{id}` | ninguno (autenticado) | Detalle. |
| `PATCH` | `/api/v1/catalogs/categories/{id}` | `catalogs.manage` | Edición parcial. **No permite reparentar** (cambiar `parent_id`) — fuera de alcance por ahora, ver `docs/ARCHITECTURE.md`. |
| `GET` | `/api/v1/catalogs/suppliers` | ninguno (autenticado) | Lista paginada. |
| `POST` | `/api/v1/catalogs/suppliers` | `catalogs.manage` | Crea proveedor. Body: `{name, code_letter, doc_type?, doc_number?, phone?, email?, address?, notes?}`. |
| `GET` | `/api/v1/catalogs/suppliers/{id}` | ninguno (autenticado) | Detalle. |
| `PATCH` | `/api/v1/catalogs/suppliers/{id}` | `catalogs.manage` | Edición parcial. |

Reglas de `code_letter` (1–3 caracteres, usado para armar el código de artículo — ver `CLAUDE.md`):
- Único entre **categorías hermanas** (mismo `parent_id`, incluyendo raíz — el `UNIQUE` de la migración no cubre raíz porque Postgres no compara `NULL` consigo mismo; el backend sí lo valida) → `409 CONFLICT`.
- Único por **empresa** entre proveedores (sin relación con categorías) → `409 CONFLICT`.
- Árbol de máximo 3 niveles: crear un hijo de una categoría nivel 3 → `400 BAD_REQUEST`.

## 7. Módulo `contracts` (contratos de empeño)

Requiere una **sesión de caja abierta** (fase 1: una caja por empresa) para desembolsar o cobrar — sin eso, `409 CASH_SESSION_NOT_OPEN`. Ver §8 (`cashbox`) para abrir/cerrar la sesión.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/contracts` | `contracts.create` | Header **`Idempotency-Key` obligatorio** (reenviar la misma key en un reintento de red devuelve el mismo contrato, no duplica el desembolso — gap cerrado, antes solo `contract_payment`/`sale` lo tenían). Crea contrato: snapshot legal (tasa la define el usuario, plazo/ventana de mora salen de la categoría del artículo), desembolsa el préstamo (`cash_movement`). Body: `{customer_id, principal, interest_rate_pct, appraisal_value?, items: [{category_id, description, weight_grams?, serial_imei?, item_appraisal?, photos?}], payment_method, extension_months?, legacy_code?, notes?}`. Todos los `items` deben usar categorías **nivel 3** con el mismo `default_term_months`/`arrears_window_months`. |
| `POST` | `/api/v1/contracts/import` | `contracts.import` (solo rol Admin de fábrica) | Migración de un contrato del sistema anterior (`docs/MIGRACION_CONTRATOS.md`): se importa la **foto financiera al corte**, no la historia de abonos. Header **`Idempotency-Key` obligatorio** (recomendado: el `legacy_code`). **No exige sesión de caja abierta y no genera `cash_movement`** — el desembolso ya ocurrió en el sistema viejo (a diferencia de `POST /contracts`). Body: `{legacy_code, customer_id, principal, capital_balance, interest_rate_pct, term_months, arrears_window_months, extension_months, start_date, interest_paid_until, items: [...], appraisal_value?, signed_photo_url?, notes?}` — a diferencia de la creación normal, `term_months`/`arrears_window_months`/`extension_months` son el snapshot real del contrato viejo (no salen de la categoría, y los `items` no necesitan compartirlos). `status` se inserta `active` y pasa por el mismo recálculo que `GET /contracts/{id}` antes de responder — nunca se acepta en el body. `legacy_code` duplicado en la empresa → `409 CONTRACT_LEGACY_CODE_EXISTS`; `capital_balance ≤ 0` o `> principal` → `422 IMPORT_CAPITAL_EXCEEDS_PRINCIPAL`; `interest_paid_until` que no cae en un número entero de meses desde `start_date` → `422 IMPORT_DATES_MISALIGNED`. No se migran contratos `paid`/rematados en el sistema viejo, ni el historial de abonos (`contract_payment` es inmutable) — el saldo a favor de un interés parcial ya pagado se reconoce como descuento en el primer abono dentro de la app. |
| `GET` | `/api/v1/contracts` | `contracts.view` | Lista paginada. `?status=active\|in_arrears\|in_extension\|auctioned\|paid` filtra. |
| `GET` | `/api/v1/contracts/{id}` | `contracts.view` | Detalle. Recalcula el estado (`active→in_arrears→in_extension`) si quedó desactualizado antes de responder — ver `docs/ARCHITECTURE.md`. |
| `PATCH` | `/api/v1/contracts/{id}` | `contracts.edit` | Solo `{appraisal_value?, notes?, signed_photo_url?}` — nunca `status`/`capital_balance` (los calcula el servicio). |
| `GET` | `/api/v1/contracts/{id}/payment-options` | `contracts.view` | Cotización: `{months_owed, monthly_interest, options: [{months, interest_amount, total, allows_capital}]}`. El front arma los botones de pago directo desde acá — nunca deja que el usuario escriba un monto de interés a mano. |
| `POST` | `/api/v1/contracts/{id}/payments` | `payments.create` (+`payments.apply_discount` si trae descuento) | Header **`Idempotency-Key` obligatorio**. Body: `{months_covered, capital_amount?, payment_method, discount_amount?, discount_reason?}`. `capital_amount` solo se acepta si `months_covered` cubre TODOS los meses adeudados — si no, `422 PAYMENT_PARTIAL_INTEREST_REJECTED`. Reenviar la misma `Idempotency-Key` devuelve el mismo abono ya creado (no duplica). |
| `GET` | `/api/v1/contracts/{id}/payments` | `contracts.view` | Historial de abonos (paginado). |
| `GET` | `/api/v1/contracts/ready-for-auction` | `contracts.auction` | Contratos en `in_extension` con la prórroga ya vencida — candidatos a Rematar. |
| `POST` | `/api/v1/contracts/{id}/auction` | `contracts.auction` | **Rematar.** Exige `status='in_extension'` y prórroga vencida (`409 CONTRACT_NOT_READY_FOR_AUCTION` si no). Crea UN `inventory_item` en `draft` por cada prenda del contrato (`origin='auction'`, `source_contract_id`), repartiendo saldo capital + intereses pendientes proporcional a `item_appraisal` de cada prenda (si ninguna tiene tasación, partes iguales — ver `docs/ARCHITECTURE.md`). Contrato y prendas quedan `auctioned`; `contract_item.inventory_item_id` guarda el vínculo. Los ítems creados salen en `draft`: usa `inventory` (§9) para publicarlos. |

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

## 9. Módulo `inventory`

Ítems entran en `draft` (desde un ingreso o desde un remate) y no son vendibles hasta publicarse — el código (`JOC0001I`) se emite AL PUBLICAR y es inmutable desde ahí.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/inventory/entries` | `inventory.create` | Ingreso de compra u "otro". Body: `{origin_type: "purchase"\|"other", supplier_id?, supplier_invoice?, notes?, lines: [{name, cat1_id, cat2_id, cat3_id, description?, unit_cost, quantity, photos?}]}`. `origin_type="purchase"` exige `supplier_id` (400 si falta). Crea un `inventory_item` en `draft` por línea — costeo por identificación específica, cada uno con su propio costo (nunca promediado). `cat1_id`/`cat2_id`/`cat3_id` deben formar una rama válida del árbol (niveles 1→2→3 encadenados). |
| `GET` | `/api/v1/inventory/entries`, `/{id}` | `inventory.view` | Incluye los ítems creados por ese ingreso. |
| `POST` | `/api/v1/inventory/exits` | `inventory.exit` | Egreso (ajuste/daño/devolución a proveedor/uso interno). Body: `{exit_type, reason, lines: [{item_id, quantity}]}`. Sin aprobación adicional — basta el permiso (CLAUDE.md). Descuenta `quantity`; si llega a 0, el ítem queda `written_off`. Auditado. |
| `GET` | `/api/v1/inventory/exits`, `/{id}` | `inventory.view` | |
| `GET` | `/api/v1/inventory/items`, `/{id}` | `inventory.view` | `?status=draft\|available\|reserved\|sold\|written_off` filtra. |
| `PATCH` | `/api/v1/inventory/items/{id}` | `inventory.create` | Solo mientras `status='draft'` (`409` si ya se publicó) — `{name?, description?, sale_price?, photos?}`. |
| `POST` | `/api/v1/inventory/items/{id}/publish` | `inventory.create` | Exige `sale_price` (body) y ≥1 foto ya cargada (`400` si falta cualquiera). Arma el código desde las letras de `cat1`/`cat2`/`cat3` + consecutivo (`next_counter` por prefijo) + letra de proveedor (o `R` si `origin='auction'`). `draft→available`. |

## 10. Módulo `sales`

No existe `sales.view` en el catálogo de permisos (seed.sql solo trae `sales.create`/`sales.void`/`sales.apply_discount`) — los `GET` quedan bajo `sales.create`, mismo criterio que `customers` en el paso 4.

| Método | Path | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/sales` | `sales.create` (+`sales.apply_discount` si trae descuento) | Header **`Idempotency-Key` obligatorio**. Body: `{customer_id?, payment_method, lines: [{item_id, quantity, unit_price}], discount_amount?, discount_reason?}`. Cada ítem debe estar `available` con `quantity` suficiente. Descuenta stock (a 0 → `sold`); `cash_movement(concept='sale', direction='in', module='store')`; exige sesión de caja abierta (`409 CASH_SESSION_NOT_OPEN` si no). Reenviar la misma `Idempotency-Key` devuelve la misma venta (no duplica ni vuelve a descontar stock). |
| `GET` | `/api/v1/sales`, `/{id}` | `sales.create` | |
| `POST` | `/api/v1/sales/{id}/void` | `sales.void` | Body `{reason}` (obligatorio). Repone stock de cada línea, `cash_movement` contrario (`direction='out'`), auditado. `409` si la venta ya estaba anulada. |

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

## 13. Esquema completo y tipos para el front

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

## 14. Catálogo de códigos de error usados hasta ahora

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
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | Falta el header `Idempotency-Key` en un endpoint de dinero. |
| `VALIDATION_ERROR` | 422 | Body no cumple el schema Pydantic — `details.errors` trae el detalle campo por campo. |
| `BAD_REQUEST` | 400 | Catch-all de reglas de negocio sin código más específico (p. ej. códigos de permiso inexistentes al armar una matriz de rol, categorías con distinto plazo en un mismo contrato, descuadre de caja sin justificación, stock insuficiente). |

## 15. Qué falta

Con `audit` + `reports` + el job nocturno, todo el núcleo operativo de `CLAUDE.md` (`platform` → `identity` → `customers`/`catalogs` → `contracts` → `cashbox` → `inventory`/`sales` → `audit`/`reports` → job nocturno) está completo — ver `docs/ARCHITECTURE.md` §11 para el detalle del job (`app/jobs/nightly.py`). Queda pendiente, fuera del alcance funcional del backend:

- **Desplegar `prod` en Fly.io**: `dev` ya está en producción de pruebas — `https://compraventa-backend-dev.fly.dev`, ver `docs/ARCHITECTURE.md` §8. `prod` usa el mismo `Dockerfile` + `fly.prod.toml`, pero necesita su propio proyecto Supabase (hoy solo existe el de `dev`) antes de poder desplegarse — no reusar el de `dev` para datos reales.
- **PDFs** (contrato firmado, acta de cierre de caja): requieren Storage + una librería de PDF, fuera de alcance por decisión explícita en los pasos 5 y 6 — el front puede armar ambos con los datos que ya expone la API mientras tanto.
- **Costeo FIFO por lote** para accesorios de bajo valor: por decisión explícita en el paso 7, todo `inventory_item` usa identificación específica (su propio costo real); FIFO por lote queda como optimización futura.

**Backlog explícito del front** (pedido durante la integración, deliberadamente pospuesto — no bloquean el arranque):
- **`GET /reports/series?months=12`**: serie histórica mensual de ingresos (empeño/tienda) para la gráfica principal del dashboard. Por ahora `GET /reports/dashboard` (§12) cubre hoy/mes — suficiente para arrancar.
- **`GET`/`PATCH /company/settings`** (tenant-scoped): pantalla de configuración de empresa (logo, firma, timezone, datos legales). Hoy esos campos existen en `company` pero no hay endpoint propio para editarlos fuera de `platform` (solo super-admin).
