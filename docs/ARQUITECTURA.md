# Arquitectura del backend

> **Qué es.** Cómo está construido el backend y por qué: aislamiento entre empresas, capas, autenticación,
> errores, concurrencia, trabajo fuera del request y el job nocturno. Las reglas de negocio están en
> [`DOMINIO.md`](DOMINIO.md); el contrato de cada endpoint en [`API_GUIDE.md`](API_GUIDE.md); cómo se despliega
> y opera en [`OPERACION.md`](OPERACION.md). Las reglas obligatorias para escribir código, en `../CLAUDE.md`.
>
> **Fuente de verdad: el código.** Cada sección nombra el archivo que la ejecuta. Si este documento y el
> código dicen cosas distintas, gana el código y se corrige este documento.

## 1. Qué es

Monolito modular multi-tenant en **FastAPI** (Python 3.12+, async, SQLAlchemy 2.0 Core, Pydantic v2) sobre
**Supabase** (Postgres + Auth + Storage). Una sola base compartida por todas las empresas; el aislamiento lo
hace **Row Level Security** de Postgres, no el código de aplicación. El backend no filtra "a qué empresa
pertenece esto": se lo dice a Postgres una vez por transacción y la base hace cumplir el resto aunque una
consulta tenga un bug. Esquema-por-tenant y microservicios se evaluaron y se descartaron.

```
Navegador ──login──► Supabase Auth ──► JWT (company_id, role_id vía Custom Access Token Hook)
    │
    ├── Bearer JWT ──► FastAPI (Fly.io) ──SET LOCAL ROLE authenticated + claims por TX──► Supavisor :6543 ──► Postgres (RLS)
    └── fotos ──────► Supabase Storage (supabase-js con su propia sesión; RLS sobre storage.objects)
```

- El front **nunca** escribe negocio directo a Postgres: todo pasa por la API, que aplica las reglas.
  **Storage es la excepción explícita** (§8).
- El backend no valida contraseñas ni emite tokens: **verifica** la firma contra el JWKS de Supabase, con la
  llave pública cacheada (sin llamada de red por request).
- La conexión va por **Supavisor en modo transacción** (puerto 6543), nunca en modo sesión.

## 2. Aislamiento multi-tenant (lo más importante)

Cada tabla de negocio tiene `company_id`, RLS **activo y forzado**, y una política
`USING (company_id = current_company_id())`. Pero un rol superusuario ignora RLS, así que cada request hace,
dentro de su transacción (`app/core/db.py`, `get_tenant_db`):

```sql
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claims', '{"sub":…,"company_id":…,"role_id":…}', true);
```

**Por transacción, nunca por sesión:** Supavisor reutiliza la misma conexión física para usuarios distintos;
un claim fijado a nivel de sesión lo heredaría el siguiente request, y eso es una fuga de datos entre
empresas. Mismo motivo para crear el engine con `poolclass=NullPool` y `statement_cache_size=0`: bajo un
pooler en modo transacción la conexión física cambia entre statements y un *prepared statement* cacheado por
`asyncpg` apuntaría a una conexión que ya no es la suya.

**Toda tabla con `force row level security` necesita al menos una policy de SELECT** antes de que algo la lea
con sesión `authenticated`: sin policy, Postgres devuelve **cero filas sin error**. Los catálogos globales
(`permission`, `plan`) usan `USING (current_company_id() IS NOT NULL)`.

**Las sesiones de bypass** (sin RLS) existen para lo que por diseño cruza empresas: el panel de plataforma, el
job nocturno y los endpoints públicos con token firmado (§5.2). En esas, **toda** consulta filtra por la
empresa que dice el token o el recorrido, nunca por algo que traiga el request.

**El rol `anon` no tiene privilegios en `public`** (00064): toda la app entra con sesión, así que ningún camino
legítimo lee ni escribe como `anon` (`tests/rls/test_anon_privileges.py`).

Tests: `tests/rls/test_tenant_isolation.py` recorre tabla por tabla que la empresa A nunca ve a la B.

## 3. Capas dentro de un módulo

```
router.py      HTTP: parseo, status, Depends(require_permission(...))
service.py     reglas de negocio; un método = una transacción
repository.py  SQL parametrizado, sin decisiones
schemas.py     Pydantic in/out (dinero y cantidades validados aquí)
integration.py lo que OTROS módulos pueden llamar
rules.py       (contracts, inventory) reglas puras, sin BD, testeables con un instante fijo
```

**Un módulo no importa el `service` de otro**: usa su `integration.py` (`cashbox.integration.record_movement`,
`inventory.integration.create_draft_items_from_auction`, `identity.integration.invite_user`…). Así cada módulo
es dueño de sus reglas y un cambio interno no rompe a otro en silencio. **Excepción consciente:** los routers
que despachan correos importan `notifications.dispatcher` directo, porque ponerlo en `integration` cerraba un
ciclo de imports (`dispatcher → identity.integration → notifications.integration`).

**Los 15 módulos** (`app/modules/`):

| Módulo | Qué es |
|---|---|
| `platform` | empresas, planes, suscripciones (solo super-admin); `get_company_today`/`get_company_timezone` |
| `identity` | usuarios, invitaciones, roles, permisos (`auth_admin.py` habla con Supabase Auth) |
| `company` | configuración de la empresa y plantillas de documentos (`template_body.py`) |
| `customers` | clientes, base legal del correo |
| `catalogs` | categorías (árbol de 3 niveles con herencia), proveedores |
| `contracts` | contratos de empeño: snapshot, abonos, estados, ampliación, remate, import (`rules.py`) |
| `cashbox` | turnos de caja, movimientos, gastos, arqueo, reapertura |
| `accounts` | catálogo de cuentas (cash, bank, settlement, vault), traslados, liquidaciones |
| `capital` | aportes y retiros del dueño (patrimonio, no resultado) |
| `inventory` | producto + lote, códigos, ingresos, egresos, transformaciones, compras a crédito (`rules.py`, `units.py`) |
| `sales` | ventas, anulación, devoluciones, notas crédito (`settlement.py`) |
| `audit` | consulta de `audit_log` (inmutable; lo escriben los demás en su transacción) |
| `reports` | dashboard, estado de resultados, rentabilidad, inventario, cierres, series, Excel |
| `notifications` | avisos por correo: catálogo, preferencias, límites, resumen, recordatorios, despachador, baja |

`app/core/`: settings, db, security (JWKS, `get_current_user`, `require_permission`), errors, logging,
security_headers, observability. `app/common/`: paginación por cursor, `Money`, idempotencia, `tenant_time`,
`search`, `rate_limit`, `cors`, `co_holidays`. `app/jobs/nightly.py`: el job nocturno.

## 4. Autenticación y autorización

- **Autenticación** (`security.decode_token` + `get_verified_claims`): ¿el JWT es válido? Firma por JWKS,
  `exp`, `aud`, `iss`. No toca la base. Un JWT sin `company_id`/`role_id` es 401.
- **Sesión de usuario** (`get_current_user`): ¿existe, está activo, su empresa está activa y con suscripción
  vigente? Toca la base con caché de **30 s**. Suscripción vencida → `402 SUBSCRIPTION_EXPIRED`.
- **Autorización** (`require_permission("modulo.accion")`): RBAC dinámico por empresa, caché por rol de
  **60 s**. **Deny-by-default:** un endpoint sin `require_permission` es un bug de revisión, y
  `tests/unit/test_endpoint_guards.py` lo detecta; las excepciones a propósito se escriben ahí con su porqué
  (`SIN_PERMISO_A_PROPOSITO`).
- **Super-admin de plataforma:** sin fila en `app_user`; se identifica por
  `app_metadata.platform_role == "super_admin"`, fijado a mano en Supabase Auth (`require_super_admin`).

**Los cambios de permisos tardan hasta 60 s** en verse (caché deliberado, alineado con el `/me` del front).
Consecuencia para los tests: revocarle un permiso a un rol ya cacheado no se ve dentro del test; hay que crear
un **rol nuevo**.

### 4.1 El Custom Access Token Hook y el estado `invited`

Los claims los emite `public.custom_access_token_hook` (migración 00003) al firmar el token, para
`status in ('active','invited')`. **`invited` tiene que estar**: sin él había un ciclo (el hook no emitía
claims hasta `active`, el backend rechazaba tokens sin claims, y lo que pasaba a `active` vivía detrás de ese
rechazo) y ningún invitado podía entrar (00028). La condición **enumera lo permitido** para que un estado
nuevo nazca excluido.

**`active` significa "ya entró con su propia contraseña"**, no "hizo un request": el claim `amr` distingue una
sesión de enlace (`otp`) de un login (`password`). Antes, abrir el enlace de invitación dejaba al usuario
"Activo" sin clave y bloqueado para siempre. Estados y flujo de alta: [`OPERACION.md`](OPERACION.md) §6.

### 4.2 Enlaces de un solo uso

Los enlaces de invitación y recuperación apuntan a la **app**, no a GoTrue:
`{FRONTEND_URL}/auth/callback?token_hash=…&type=invite|recovery` (`identity/auth_admin.py::_app_link`). El
front los canjea con `verifyOtp` (un **POST**) y solo tras un clic en «Continuar». Motivo: las vistas previas
de WhatsApp/Telegram/Slack y los escáneres de correo **piden cada URL** antes que el destinatario, y un token
que se canjea por GET muere ahí. **El enlace es una credencial: nunca va a logs ni a `audit_log`.**

## 5. Endpoints y trabajo fuera del request

### 5.1 Trabajo después del commit

En FastAPI las `BackgroundTasks` corren **antes** del commit de la dependencia `get_db` (comparten el
`AsyncExitStack` del request). Una tarea que abre otra conexión busca filas que todavía no existen y no falla:
simplemente no encuentra nada. **Regla:** el servicio registra el aviso como último paso de su transacción
(`notifications.integration.record_customer_notice` / `record_company_alert`) y devuelve
`(documento, entregas)`; el router llama `notifications.dispatcher.send_after_commit(db, background, *entregas)`
como **última** acción, que hace `commit` explícito y recién ahí agenda. Sin entregas no commitea.

**Un aviso es consecuencia de un hecho ya registrado, no puede tumbar la operación:** si el correo falla, la
venta o el abono ya quedaron.

### 5.2 Endpoints públicos: solo con un token firmado que dice a quién

El único hoy es la **baja de avisos** (`GET`/`POST /api/v1/public/unsubscribe/{token}`, `notifications/unsubscribe.py`).
Reglas para el próximo:

- La autorización **es el token** (HMAC con `NOTIFICATIONS_LINK_SECRET`) y dice sobre qué fila actúa; toda
  consulta filtra por lo que dice el token. **Sin secreto configurado, ningún token vale.**
- **El GET nunca escribe**; la acción es un POST disparado por una persona.
- **Un solo código** para todo lo que no sirve (`UNSUBSCRIBE_LINK_INVALID`, 404): a quien fabrica tokens no
  se le explica en qué se equivocó.
- Prefijo `/api/v1/public/`, excepción escrita en `test_endpoint_guards.py`, y **límite de tasa** en memoria y
  por máquina (`app/common/rate_limit.py`): corta abuso, no es una cuota global.
- Los correos al cliente llevan `List-Unsubscribe` + `List-Unsubscribe-Post` (baja de un clic, RFC 8058).

## 6. Dinero, concurrencia e idempotencia

**Una operación de negocio = una transacción**: documento + movimientos de caja + contadores + auditoría. El
dinero es `Decimal`/`NUMERIC(14,2)`, jamás `float`; las cantidades de inventario `NUMERIC(14,3)`.

### 6.1 Bloqueos

Las validaciones "hay saldo", "el contrato sigue activo", "la factura no está pagada" leen antes de escribir;
bajo concurrencia, dos requests pasan la validación a la vez. La auditoría del 27/09/2026 lo midió en contratos,
caja, cuentas e inventario (doble cobro, dos sucesores del mismo contrato, cuentas sobregiradas, factura pagada
dos veces). Desde la tanda de arreglos, **toda operación que modifica un documento o valida un saldo toma
primero la fila con `FOR UPDATE`** y revalida después del bloqueo:

| Qué se bloquea | Dónde | Por qué |
|---|---|---|
| el contrato | `contracts/repository.py` (`get_contract_for_update`) | abonos, ampliación, remate y saldar sobre el mismo contrato se serializan |
| las cuentas | `accounts/repository.py::lock_accounts` | el saldo se deriva de `cash_movement`, no vive en una fila: la fila de `account` es el **mutex del saldo**. Varias cuentas se bloquean en un solo `select … order by id` para que dos traslados cruzados no se esperen mutuamente |
| la registradora | `cashbox/repository.py` | abrir, cerrar y reabrir el turno de una caja |
| la venta, la nota crédito | `sales/repository.py` | anular, devolver y redimir sobre la misma venta o nota |
| la compra a crédito | `inventory/repository.py` | pagar la factura una sola vez |
| entregas de correo | `notifications/repository.py` | `for update skip locked`: dos despachadores no toman la misma |

Para lo que no tiene fila propia se usan **advisory locks de transacción** (`identity/repository.py`: invitar al
mismo correo, salvaguarda del último admin). Detrás de todo, la base: `CHECK (quantity >= 0)`, `UNIQUE`,
índices parciales (`uq_session_open`).

### 6.2 Idempotencia

`Idempotency-Key` es **una por acción del usuario, no por request** (el front la genera al abrir el formulario y
la conserva en los reintentos, incluso tras un 401). Se persiste con `UNIQUE(company_id, idempotency_key)` en la
tabla del documento, y **la clave se busca después del bloqueo**: un reintento con la misma clave devuelve el
mismo documento sin mover plata. `app/common/idempotency.py` tiene dos dependencias:
`require_idempotency_key` (obligatoria: abonos, contratos, ampliación, ventas, liquidaciones, traslados,
capital, pago de compras…) y `optional_idempotency_key` (remate, gasto, egreso de inventario: se persiste si
viene, para no romper un front ya desplegado que no la manda; pasa a obligatoria cuando el front la mande
siempre). 00061 le dio documento propio a la liquidación de convenios (`account_settlement`) para tener dónde
guardar la clave.

## 7. Errores

Toda excepción de negocio hereda de `AppError` (`app/core/errors.py`) y sale siempre igual:

```json
{"code": "PERMISSION_DENIED", "message": "Falta el permiso 'identity.manage_users'.", "details": {"permission": "identity.manage_users"}}
```

`code` es estable y el front decide comportamiento por él (modal de abrir caja, pantalla de bloqueo, error por
campo); `message` es para humanos. **Un código de error es un contrato entre dos capas que nadie compila**: el
backend devolvía `NOT_FOUND` donde el front escuchaba `CASH_SESSION_NOT_OPEN` y una empresa pasó once días sin
poder crear contratos. Por eso `tests/unit/test_error_catalog.py` compara, en las dos direcciones, los códigos
que emite `app/` con la tabla del **§15 de `API_GUIDE.md`**: un código sin documentar o uno documentado que ya
nadie emite rompen la suite.

**Lo que hace cumplir la base también sale como error de negocio.** Los handlers de `errors.py` traducen:

| La base rechaza | Sale como |
|---|---|
| `UNIQUE` sobre `idempotency_key` | `409 IDEMPOTENCY_IN_PROGRESS` (el reintento llegó mientras la original seguía en vuelo) |
| `uq_session_open` | `409 CASH_SESSION_ALREADY_OPEN` |
| `quantity_check` | `400 BAD_REQUEST` "No hay suficiente cantidad disponible" |
| otro `UNIQUE` con nombre conocido | su código (`_UNIQUE_CODES`), o `409 CONFLICT` |
| `NOT NULL`, `CHECK`, clase 22 (valor que no cabe) | `422 VALIDATION_ERROR` con la misma forma que Pydantic |
| cualquier otra cosa | **sube como 500**: traducir a ciegas convertiría un bug desconocido en un mensaje tranquilizador |

**Un error tiene que nombrar la acción que falta**, no solo negar la que se intentó: "ya invitaste a esta
persona, genera el enlace desde su ficha" se resuelve en diez segundos; un 502 "no se pudo invitar" manda a
reintentar en círculos.

## 8. Storage

Bucket privado `company-files`; URLs firmadas; rutas `{company_id}/{sección}/…` armadas por el front. El front
sube y lee directo con `supabase-js` y su sesión: no hay regla de negocio que aplicar, solo acceso, y lo hace
RLS sobre `storage.objects`. **La subcarpeta decide el permiso** (00062): `customers` con `customers.*`,
`contracts`/`contract-items` con `contracts.*` (las fotos de la prenda viajan al inventario con el remate),
`inventory`, `expenses` con `cashbox.expense`, `company` (logo y firma, legibles por todos) con
`company.configure`, y `perfil/{user_id}/…` donde cada usuario escribe solo su carpeta (00065). Solo se aceptan
extensiones de imagen. Cualquier otra sección: nadie (deny-by-default). El backend usa la `service_role`, que no
pasa por RLS.

## 9. "Hoy" es la fecha de la EMPRESA

Fly corre en UTC; Colombia es UTC-5. Un `date.today()` o un `current_date` calcula el día equivocado **cinco
horas cada noche** (7 p. m.–medianoche), en horario de atención. **Ninguna regla con fecha usa `date.today()`
ni `current_date`:** se usa `platform.integration.get_company_today(db, company_id=…)` (lee
`company.settings.timezone`, default `America/Bogota`, caché 5 min) y, para filtrar timestamps en SQL,
`get_company_timezone`. `app/common/tenant_time.py` tiene la conversión pura. **Vale también en los fixtures de
tests:** un `current_date - 1` en un fixture pasa de día y falla de noche.

## 10. Paginación y búsqueda

- **Cursor, siempre** (`app/common/pagination.py`). Por `id` (`encode_cursor`) solo donde el orden no
  importa; **donde el orden ES la función (auditoría, históricos) la llave va por fecha**: `encode_time_cursor`
  (`created_at`, cuándo se registró) o `encode_date_cursor` (`(fecha del documento, id)`, para documentos con
  fecha propia). Un `order by id` sobre UUID pagina bien y no significa nada.
- **Búsqueda** (`app/common/search.py`): `plainto_tsquery` compara **lexemas enteros** ("Mate" no encuentra a
  Mateo: parece un umbral, no lo es), así que se combina con un `ilike` por prefijo. El stemmer del español
  normaliza tildes pero **no la eñe**: todo pasa por `f_unaccent` (00056). No usar `to_tsquery`: acepta
  sintaxis y convierte un error de dedo en un 500.

## 11. Job nocturno

`app/jobs/nightly.py` (`python -m app.jobs.nightly`) es el único código que corre fuera del request. Corre en una
**Fly Machine programada** (`nightly-job`, `--schedule daily`), no en pg_cron, para que la lógica siga en Python
y no se duplique en PL/pgSQL; y no como `[processes]` de `fly.toml`, que la mantendría encendida 24/7. En orden,
cada paso en su propia transacción de bypass:

1. `contracts.service.recompute_all_statuses` — recalcula el estado de los contratos no terminales de todas
   las empresas contra el "hoy" de cada una. (El detalle de un contrato también recalcula al leerlo.)
2. `platform.service.expire_overdue_subscriptions` — marca `expired` las vencidas y audita. **Esto es lo que
   bloquea el acceso:** `get_current_user` mira el `status` persistido, no recalcula `expires_at`.
3. `notifications.digest.build_all_digests` — resumen a la empresa. **Después del paso 1** porque lee el estado
   recién persistido. Una transacción por empresa; registra el resumen diario **salga o no**, así "¿corrió
   anoche?" se contesta con `select max(occurred_on) from notification_event`.
4. `notifications.reminders.build_all_reminders` — recordatorios R1–R4 al cliente. Llave construida con la
   fecha objetivo: correrlo dos veces o tres días tarde no duplica.
5. `notifications.dispatcher.dispatch_due` — manda las entregas pendientes, con su propio reloj tomado después
   de 3 y 4. Sin `RESEND_API_KEY` no falla: quedan `skipped_no_provider`.

**La Machine no pertenece al process group de la app**: `fly deploy` y `fly secrets set` no la actualizan, y en
una limpieza de "máquinas huérfanas" parece sobrante (ya la borraron una vez y nadie lo notó en doce días). Su
ausencia es silenciosa. Cómo se actualiza y cómo se vigila: [`OPERACION.md`](OPERACION.md) §3. **Un job que no
audita no deja rastro forense**: el recálculo nocturno no escribe en `audit_log`, y el día de un incidente
(F21-10) no se pudo saber qué vector dañó cada fila.

## 12. Permisos: cómo nace uno

**Un módulo nuevo trae sus propios permisos desde el día uno**, aunque parezcan redundantes. Reusar el de otro
módulo lo saca de la matriz de roles (quien configura no puede otorgarlo a conciencia), acopla cosas que no van
juntas y cuela acciones sensibles detrás de permisos de lectura (así terminó `accounts.settle` colgando de
`cashbox.view`). Mínimo `<modulo>.view` / `<modulo>.manage`, más uno **especial** (`is_special = true`) por cada
acción que mueva plata, cambie un estado irreversible o exija auditoría.

**Al agregarlos a un módulo ya desplegado, la migración los otorga a los roles que tenían los equivalentes**,
o todos pierden acceso de un día para otro — salvo cuando el mapeo viejo *era* el error (00029 con `settle`).
**Los permisos base y los planes viven en `supabase/seed.sql`**, que `db push` no aplica: en un ambiente nuevo
el seed va aparte ([`PRODUCCION.md`](PRODUCCION.md) §1.6).

**Si un permiso se puede rodear por otra URL, no es un permiso**, y **ocultar el botón no es protección**: la
UI oculta (gate en el menú **y** guard en la ruta), el backend protege. Catálogo de los 43:
[`DOMINIO.md`](DOMINIO.md) §11.

## 13. Principios de sistema que ya costaron

- **Un `limit 1` sobre un conjunto que puede tener más de un elemento es una suposición.** Costó tres veces.
  Si el conjunto debe tener uno, la consulta los trae todos y el servicio **rechaza si hay más**.
- **Una lista escrita a mano vence.** Donde un criterio se aplica en dos capas, las dos leen la misma
  constante (`contracts.rules.TERMINAL_STATUSES` alimenta la guarda del estado, el filtro del job, la puerta
  de abonos y el cupo de ampliación). Un estado terminal nuevo nace **cerrado**: cerrado de más se nota,
  abierto de más no.
- **Una invariante sobre datos vivos que nadie vigila es invisible**: su lugar es un script que sale con
  código 1 (`scripts/qa/verificar_cadenas.py`), no un test contra una base efímera.
- **Un bug de datos rara vez tiene un solo vector:** antes de cerrar uno, buscar **todos** los lugares que
  escriben el dato (F21-10: el job y el recálculo al leer).
- **Deshacer una operación es deshacer sus efectos, no su registro** (reabrir una caja revierte el ajuste
  que emitió el cierre, no solo el acta).
- **Una configuración que se ignora en silencio es peor que una que falla** (Supabase descarta un
  `redirect_to` no permitido y el síntoma aparece tres pasos después).
- **Los comentarios que afirman algo del mundo exterior envejecen mal.** Verificarlos antes de confiar.
- **Cambiar la firma de una función exportada exige buscar sus usos en todo `tests/`**: los tests no viven
  junto al código.
- **Toda migración nueva trae RLS y su test de aislamiento; nunca se edita una migración aplicada.**
  `alter type … add value` no se puede usar en la misma transacción que lo declara: va en su propia migración.
