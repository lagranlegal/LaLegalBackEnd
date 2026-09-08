# Auditoría de QA — registro por fases

> **Qué es este archivo.** El registro de la auditoría de calidad de la aplicación: qué se probó, qué se encontró, qué se arregló y qué queda abierto. Una sección por fase, la más reciente arriba. Se actualiza al cerrar cada fase.
>
> **Qué NO es.** No es el estado del proyecto (`ESTADO.md`) ni el traspaso de la última sesión (`CONTINUAR.md`). Acá vive solo lo que sale de probar la app contra sus propias reglas.
>
> **Dónde vive y por qué.** Cruza los dos repos, pero está acá y no en la raíz del workspace para que quede **versionado**: la raíz no es un repo git. Vive en el backend porque la auditoría verifica reglas de negocio y esas viven acá — si alguna fase de UI genera mucho material propio, se puede partir entonces, no antes.
>
> Los scripts que produjeron todo esto están en [`scripts/qa/`](../scripts/qa/), con su propio README.

---

## Estado de las fases

| Fase | Alcance | Estado |
|---|---|---|
| **0** · Laboratorio | Empresas espejo, usuarios por rol, arsenal de scripts, mapa de endpoints | ✅ 08/09/2026 |
| **1** · Identidad, permisos y aislamiento | Matriz completa de permisos, roles, ciclo de vida del usuario, multi-tenancy, guards de UI | ✅ 08/09/2026 |
| **2** · Dinero y caja | Ciclo diario, arqueo sin tolerancia, reapertura, cuentas, traslados, idempotencia | ⏳ siguiente |
| **3** · Contratos | Snapshot legal, herencia de categoría, meses completos, máquina de estados, remate, import | ⏳ |
| **4** · Inventario y tienda | Códigos y letras, producto vs lote, unidades, transformaciones, kardex, ventas, devoluciones | ⏳ |
| **5** · El círculo completo | Que cada operación de dinero aparezca a la vez en caja, reportes, auditoría y kardex | ⏳ |
| **6** · UX, UI y accesibilidad | Estados de carga, mensajes, responsive, teclado, contraste, tema oscuro, impresión | ⏳ |
| **7** · Regresión | Convertir lo encontrado en suite automatizada | ⏳ |

**Principios de método** (los mismos del proyecto, aplicados a probar):

- **Toda aserción de error va contra el `code`, nunca contra el status solo.** Un test que mira el status y no el código no cubre nada — le costó once días de trabajo a un cliente.
- **Cada permiso se prueba dos veces:** en la pantalla (¿oculta?) y en la API pelada con el JWT de ese rol (¿403?). La UI oculta, no protege.
- **Un test que pasa no prueba nada hasta que se ve fallar sin el fix.** Todo test nuevo de esta auditoría se ejecutó con el arreglo revertido, para confirmar que falla con el error exacto.

---

## Fase 1 — Identidad, permisos y aislamiento (08/09/2026)

**Veredicto: el control de acceso está sólido.** 420 comprobaciones (105 endpoints × 4 roles, con el permiso y sin él) y las 420 coinciden con lo esperado. Los 167 casos sin permiso devolvieron `403 PERMISSION_DENIED` sin una sola excepción. Ningún endpoint quedó sin guard. Lo que falla está fuera de la capa de permisos.

**14 hallazgos: 3 altos (los tres arreglados), 3 medios, 8 documentales (los ocho corregidos).**

### H-01 · El job nocturno no existía en Fly — ALTA, resuelto

`fly machines list` devolvía una sola máquina, la del process group `app`. La Fly Machine programada que describe `ARCHITECTURE.md` §11 no estaba. `ESTADO.md` registra que el 27/08 se borró «una máquina huérfana, fuera del process group, sin deploys desde el 17/08» — el perfil exacto del job, porque estar fuera del fleet de `fly deploy` es justo su diseño.

**Evidencia de que llevaba días sin correr:**

```
select event_type, count(*) from subscription_event group by 1;
  created 5 · extended 3 · expired 0      ← cero vencimientos automáticos en toda la historia
```

Y el contrato #8 de Empresa Demo Front estaba en `active` con 51 días de mora, mientras su gemelo #9 (un día de diferencia, mismo snapshot) sí estaba `in_arrears`. El #8 se corrigió solo al leerlo.

**La consecuencia, demostrada con un caso reproducible.** Contrato con 5 meses de mora y la prórroga vencida hace dos, con el `status` sin tocar:

```
— antes de que alguien abra el contrato —
Lista de contratos     estado mostrado: active
Listos para remate     0 contratos · ¿está el nuestro? NO
Dashboard              active:1  in_extension:0  ready_for_auction:0

— alguien abre GET /contracts/{id} —
                       estado: in_extension · prórroga venció 2026-07-08

— después —
Listos para remate     1 contrato · SÍ
Dashboard              active:0  in_extension:1  ready_for_auction:1
```

`get_contract` recalcula al leer (`service.py:424`), pero **`list_contracts` no**, y `list_ready_for_auction` filtra por `status = 'in_extension'` persistido. Sin el job, el estado solo avanza si un humano abre ese contrato — y un contrato abandonado es el que nadie abre. **Las prendas rematables son invisibles precisamente porque nadie las mira.**

Segundo efecto: una empresa con la suscripción vencida hace 38 días entraba con normalidad.

**Arreglado y verificado.** Máquina `nightly-job` recreada en `sjc` con `--schedule daily`. Para probar que hace su trabajo, se desarmó el estado a propósito:

```
job_nocturno_completado: 1 contrato(s) recalculado(s), 1 suscripción(es) vencida(s)
contrato → in_extension · suscripción → expired · evento expired (la primera de la base)
```

**El comando que documentaba el proyecto no funcionaba:** usaba `registry.fly.io/…:latest`, y ese tag no existe en el registry de Fly (las imágenes se publican como `deployment-<id>`). Corregido en `fly.dev.toml` y `fly.prod.toml`.

**Dos cosas que conviene recordar de esta máquina** (ya en `ARCHITECTURE.md` §11):

1. Queda clavada a la imagen con la que se creó. `fly deploy` **no** la actualiza, porque no pertenece a su fleet — hay que recrearla tras un cambio que la afecte.
2. **Su ausencia es silenciosa.** No hay health check ni alerta. Para comprobar que vive: `fly machines list -a compraventa-backend-dev` debe mostrar `nightly-job`, o buscar `job_nocturno_completado` en los logs del último día.

**Queda como recomendación, no hecho:** recalcular también en `list_contracts`, para que la lista no pueda mentir aunque el job vuelva a fallar. Cambia el costo de una consulta que corre en cada carga de la pantalla de contratos — decisión de Mateo.

### H-14 · Una suscripción vencida no se podía renovar — ALTA, resuelto

**Lo destapó H-01: un bug estaba escondido detrás del otro.** Con el job arreglado, la empresa de pruebas pasó a `expired` como debe. Al intentar devolverle el acceso:

```
POST /platform/companies/{id}/subscription/extend  → 404 "no tiene una suscripción activa"
POST .../activate                                  → 200, pero la suscripción sigue expired
GET  .../companies/{id}                            → plan_code: null, expires_at: null
```

**No quedaba ningún camino en la API** para reactivarla: el único arreglo era entrar a la base a mano. Es el flujo comercial más normal del producto — el cliente paga tarde y se le renueva. Nunca se detectó porque para llegar hasta él hace falta una suscripción `expired`, y el job que las produce no estaba corriendo.

**Causa:** `extend_subscription` buscaba con `get_active_subscription`, que filtra `status = 'active'` — justo el estado que una vencida ya no tiene. Y aunque la encontrara, el `UPDATE` solo movía `expires_at` sin tocar `status`: el acceso habría seguido bloqueado.

**Arreglado:** `get_subscription_for_renewal` la encuentra esté o no vigente, y el `UPDATE` la vuelve a poner `active`. Con test que falla sin el fix. Verificado en vivo: `plan_code: null → "full"`, `vence: null → 2027-12-31`, y la empresa volvió a entrar.

**Abierto, decisión de producto:** una empresa vencida se muestra en el panel con `plan_code: null`, indistinguible de una que nunca tuvo plan — el super-admin renueva sin ver a qué fecha ni con qué plan. El front ya tiene la lógica para pintar un vencimiento pasado en rojo (`CompanyDetailDialog.tsx:166`) **y nunca puede verse**, porque el dato llega en `null`. Cambiarlo toca el contrato documentado de `CompanyOut`.

### H-02 · `GET /accounts/transfers` devolvía 500 desde su creación — ALTA, resuelto

```
GET /api/v1/accounts/transfers  → 500 "Internal Server Error"   (texto plano, sin envelope)
```

Fallaba con la lista vacía y con datos, para todo rol con `accounts.view`. Causa reproducida contra la base:

```
asyncpg.exceptions.AmbiguousParameterError: could not determine data type of parameter $2
```

La cláusula `(:cursor is null or t.id > :cursor)` en `accounts/repository.py:238`: el parámetro aparece primero en `is null`, sin contexto de tipo. Era el **único** sitio del backend con ese patrón; los demás arman el `WHERE` dinámicamente.

**Por qué nadie lo vio:** el endpoint aparecía 9 veces en `tests/integration/test_accounts.py` y **las 9 eran POST**. Ningún test hacía GET al listado, así que 325 tests estaban en verde con un endpoint roto al 100%. En el front, `useTransfersList()` existe pero no tiene consumidores — la pantalla de histórico de traslados nunca se construyó, así que estaba roto y latente.

**Arreglado**, con el test GET que faltaba (cubre con y sin cursor, y falla sin el fix con el error exacto). Verificado en vivo con un traslado real.

### H-03 · Contraste por debajo de WCAG AA — MEDIA, abierto

Medido con `getComputedStyle` sobre la app en vivo:

| Texto | Ratio | Mínimo | Origen |
|---|---|---|---|
| «Caja cerrada — no se pueden registrar operaciones de dinero» | **1.97** | 4.5 | `--warning` sobre `--warning-soft` |
| «Tu rol no incluye el resumen del inicio…» | **2.77** | 4.5 | `--text-muted` sobre `--bg-app` |
| Nombre del rol bajo el avatar | **2.97** | 4.5 | `--text-muted` sobre `--bg-surface` |

`DESIGN_SYSTEM.md` §4.10 exige AA 4.5:1 y advierte específicamente sobre el teal; ese cuidado no se aplicó al ámbar ni al gris. El peor caso es el mensaje operativo más importante del producto — el mismo que costó once días a LA GRAN LEGAL. Y `--text-muted` no es un caso suelto: es el token de labels de KPI, hints y placeholders, así que recorre la app entera. Se corrige en `tokens.css`, el mismo mecanismo que ya sostuvo el rediseño.

**Recomendación:** verlo en la Fase 6, con capturas del antes y el después.

### H-04 · El descuento sobre intereses existe en el backend y no tiene pantalla — MEDIA, en definición

Cruzando el catálogo de 36 permisos contra los que el front menciona sobran dos, y los dos son **especiales**: `payments.apply_discount` y `sales.return_override_time_limit`.

El backend acepta `discount_amount` en un abono, lo audita y tiene el permiso en la matriz de roles; `PaymentOptionsPanel.tsx` nunca lo envía. El módulo puede **mostrar** descuentos que ninguna pantalla puede crear. Y `MIGRACION_CONTRATOS.md` §5 define que el interés parcial ya pagado en el sistema viejo se reconoce «usando el descuento existente» — un paso que hoy no se puede dar por pantalla.

**Necesita definición de negocio.** Documentado con sus cinco preguntas y tres opciones en `frontend-starter/docs/DECISIONES_PENDIENTES.md`.

### H-05 · El inicio del Asesor es una pantalla vacía — MEDIA, abierto

Sin `reports.view`, `/` muestra un párrafo y unos 700 px de vacío. El texto está bien escrito (nombra el permiso y a quién pedírselo), pero deja al rol de mostrador —el que más usa la app— abriendo en una pantalla que no le sirve. Es una oportunidad: ese espacio es el sitio natural para nuevo contrato, nueva venta, buscar cliente, contratos que vencen hoy.

### H-06 … H-13 · Desajustes entre documentación y código — BAJA, los ocho corregidos

Ninguno rompía nada, pero en este proyecto la documentación *es* la especificación.

| # | Decía | Hace |
|---|---|---|
| H-06 | `GET /accounts/{id}/statement` con rango opcional, «últimos 30 días» por defecto | Lo **exige**: `422` con `missing` en ambos |
| H-07 | Letras reservadas `R`, `P`, `T` | Son cuatro — también `D` (devolución, 00044) |
| H-08 | Catálogo de errores de `API_GUIDE` §15 | Faltaban `CANNOT_DEACTIVATE_SELF`, `USER_ALREADY_EXISTS`, `USER_ALREADY_INVITED`, `EMAIL_ALREADY_REGISTERED`, `AUTH_ACCOUNT_MISSING`, `TEMPLATE_IS_ACTIVE`, `INVITE_RATE_LIMITED`, `AUTH_ADMIN_ERROR` |
| H-09 | `CASH_SESSION_NOT_OPEN` es 409 | Es 409 salvo en `/cashbox/sessions/current`, donde es 404 a propósito |
| H-10 | «38 permisos» (`ESTADO.md`) / «37» (`README.md`) | Son **36** |
| H-11 | Exclusiones del Moderador en `seed.sql` | El código excluye 5 más: `accounts.manage/settle/transfer`, `inventory.pay_purchase`, `inventory.transform` |
| H-12 | «Paginación por cursor en toda lista» | **Trece** endpoints devuelven array plano, sin cursor ni tope |
| H-13 | `PATCH /me` ignora `role_id`/`status`/`email` | Los ignora **y responde 200**, así que quien los manda cree que funcionaron (sin riesgo de escalada — verificado) |

Más un noveno que apareció al arreglar H-01: el comando del job en los `.toml` usaba un tag `:latest` inexistente.

### Lo que se probó y está bien

Vale tanto como la lista de arriba: son los sitios donde no hay que buscar. Varios nunca se habían verificado en vivo.

| Comprobación | Resultado |
|---|---|
| 105 endpoints × 4 roles, con el permiso y sin él | **420/420**; los 167 negados dieron `403 PERMISSION_DENIED` |
| Endpoints sin `Depends(require_permission)` | Ninguno, en los 109 del AST |
| Salvaguarda del último admin: desactivar, bajar de rol, quitar el permiso al rol | Los tres caminos → `409 LAST_ADMIN_SAFEGUARD` |
| Auto-desactivación por API, no solo por UI | `409 CANNOT_DEACTIVATE_SELF` |
| Escalada vía `PATCH /me` (rol, estado, correo, empresa) | Ninguna: el schema descarta los campos |
| Aislamiento entre empresas: leer, y meter ids ajenos en cliente, categoría, rol, usuario, cuenta | Todo `404`; nunca confirma que exista en otra empresa |
| Guard de `/platform` sin el claim *(pendiente desde el 19/08)* | Cerrado incluso para un Admin con los 36 permisos |
| Activación `invited → active` solo con `amr: password` | Correcta en los 4 usuarios nuevos |
| Errores del alta: reinvitar, correo ya registrado, enlace de un inactivo | 409 con código propio y mensaje que nombra la salida |
| Alta de empresa devuelve `admin_invite_link` (fix del 04/09) | Confirmado creando dos empresas |
| Gates de UI: menú y ruta directa, en Admin / Asesor / Bodega | Coinciden exactamente con los permisos, en las dos capas |
| Un 403 no se lee como falla | Nombra el permiso y a quién pedírselo |
| Banner de caja cerrada con y sin `cashbox.open_close` (fix del 03/09) | Correcto; Bodega, sin `cashbox.view`, no ve el banner en vez de afirmar un estado |
| Desborde horizontal a 360 px | Ninguno |
| Ventana tras desactivar a alguien con sesión abierta | **32 s** — coincide con el cache de 30 s ya anotado como conocido |

### Pendiente de la Fase 1, para hacer al abrir la Fase 2

Dos comprobaciones que necesitan historia de caja, que la empresa espejo todavía no tenía:

1. Que el histórico de sesiones de días anteriores no se alcance sin `cashbox.view_history` por **ninguna** de sus puertas (`/cashbox/sessions`, `/cashbox/sessions/{id}` de otro día, `/reports/closings`, `/reports/closings-breakdown`). Requiere insertar una sesión de ayer en la base.
2. Que una cuenta de otra empresa se rechace **con la caja abierta**: hoy el `409 CASH_SESSION_NOT_OPEN` se adelanta y tapa la validación del `account_id` ajeno.

---

## El laboratorio (cómo retomarlo)

Todo vive en el proyecto Supabase de **dev** (`driyubkodnsqxbtxcmaz`). Las empresas reales (*La Legal*, *LA GRAN LEGAL*, *Empresa Demo Front*) **no se tocan** salvo autorización explícita.

### Empresas y usuarios de prueba

| Empresa | Para qué |
|---|---|
| `ZZ QA — auditoria 08/09` | La empresa espejo principal: catálogo, cuentas, clientes, contratos |
| `ZZ QA-B — aislamiento 08/09` | La segunda empresa, para probar que A no ve nada de B |

Seis usuarios, todos con contraseña `QaLab2026!`:

| Correo | Rol | Permisos |
|---|---|---|
| `qa.admin@qalab.com` | Admin | 36 |
| `qa.moderador@qalab.com` | Moderador | 19 |
| `qa.asesor@qalab.com` | Asesor | 11 |
| `qa.bodega@qalab.com` | Bodega | 5 |
| `qa.gestor@qalab.com` | Gestor Usuarios QA (rol creado a medida) | 1 — `identity.manage_users`, para probar la salvaguarda del último admin sin ser admin |
| `qa.b.admin@qalab.com` | Admin de la empresa B | 36 |

El super-admin de plataforma es la cuenta de Mateo (claim `app_metadata.platform_role`). Para crear usuarios nuevos sin gastar cuota de correo: invitar con `send_email: false` y luego fijar la contraseña con el `SUPABASE_SERVICE_ROLE_KEY` (`PUT /auth/v1/admin/users/{id}`).

### Datos sembrados en la empresa QA

- **Categorías con herencia repartida a propósito:** *Joyería* (nivel 1) define plazo/ventana/LTV y sus hijas *Oro* → *Cadena*/*Anillo* no definen nada (prueba que la herencia sube dos niveles); *Tecnología* define solo la ventana y su hija *Celulares* solo el plazo (prueba que la herencia es **por campo**, no por categoría).
- **Cuentas de los tres tipos:** `Caja principal` (cash), `Bancolombia QA` (bank), `Sistecrédito QA` (settlement).
- **Contrato `QA-JOB-TEST-1`** con fechas manipuladas en la base a propósito, para la demostración de H-01.

### Cómo se probó

- **Matriz de permisos:** `require_permission` es un `Depends`, así que se evalúa **antes** del body. Un request con body vacío y un UUID inexistente devuelve `403` si falta el permiso y `422`/`404` si lo tiene — así se barre el catálogo entero sin crear ni modificar nada.
- **Mapa de endpoints:** los paths salen de `/openapi.json` (la verdad), y el permiso de cada uno del AST de los `router.py` cruzando por el nombre de la función. Ojo: varios routers declaran **más de un `APIRouter`** en el mismo archivo, así que tomar el último `prefix` asignado da rutas equivocadas.
- **UI:** Playwright vía el caché de npx, con login real de cada rol contra Vercel.
- **Contraste:** `getComputedStyle` recorriendo los nodos de texto y calculando el ratio WCAG contra el primer ancestro con fondo opaco.

Los scripts viven en [`scripts/qa/`](../scripts/qa/) — ver su README para levantar el laboratorio y correr la matriz de permisos completa.
