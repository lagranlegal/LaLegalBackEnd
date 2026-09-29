# Compraventa — mapa completo del proyecto

> **Para qué sirve este archivo.** Es la puerta de entrada: qué es el producto, cómo están armadas sus piezas, dónde vive cada cosa y qué documento leer según lo que vayas a tocar. Si solo vas a leer un archivo antes de meter mano, que sea este.
>
> **Qué NO es.** No es el estado del día (eso es [`ESTADO.md`](ESTADO.md)) ni el traspaso de la última sesión de trabajo (eso es [`CONTINUAR.md`](CONTINUAR.md)). Este archivo cambia poco; esos dos cambian seguido.
>
> Ojo: la carpeta raíz `compraventa_app/` **no es un repositorio git**. Los repos son las dos carpetas de adentro, así que este archivo, `ESTADO.md` y `CONTINUAR.md` **no están versionados** — viven solo en esta máquina.

---

## 1. Qué es el producto

**Prendo** — SaaS **multi-tenant** para compraventas colombianas (casas de empeño + tienda), vendido por suscripción. Cada compraventa es una **empresa** (tenant) con sus datos aislados.

> **La marca está aplicada al código desde el 20/09/2026.** Nombre **Prendo**, paleta **Oro Moderno** (`--brand-500: #c99a3d`, con texto **carbón** encima — blanco daba 2.57:1), logo de **etiqueta** y la regla de dónde aparece cada marca (el sidebar es del tenant, el login es de Prendo): `frontend-starter/docs/DESIGN_SYSTEM.md` §1-bis. El kit visual, en [`marca/`](marca/). Plan de lo que sigue (guía, dominio, correo): `frontend-starter/docs/PLAN_MARCA.md`.
>
> **Ojo con las dos marcas.** Prendo es la plataforma; **LA GRAN LEGAL es un cliente**, no el producto. El sidebar muestra `me.company.name` — el nombre del inquilino.

El negocio tiene **dos motores que se miden distinto** y una caja que los une:

| | **Empeño** | **Tienda** |
|---|---|---|
| Qué hace | Presta plata contra una prenda | Compra y revende mercancía |
| Cómo gana | **Intereses** sobre el capital prestado | **Margen** sobre el costo |
| Qué NO es ganancia | El capital que el cliente devuelve | La plata de una venta, hasta restarle el costo |
| Se mide con | Rendimiento sobre la cartera | Utilidad bruta y margen |

Los dos desembocan en **una caja diaria única**, con desglose contable por módulo. Esa separación no es cosmética: mezclarlos produce números falsos, y este proyecto ya pagó ese error tres veces (ver §7).

**Flujo de vida de un contrato de empeño:** se presta contra una prenda → el cliente paga interés mes a mes → si deja de pagar entra en mora → agotada la ventana de mora entra en prórroga → si vence la prórroga, queda listo para remate → al rematar, la prenda se convierte en artículo de inventario y pasa a venderse en la tienda. Esa cadena tiene que poder recorrerse **hacia atrás** (del artículo en vitrina al contrato del cliente que lo dejó).

---

## 2. Las piezas y dónde viven

```
compraventa_app/                  ← NO es un repo git
├── README.md                     ← este archivo
├── ESTADO.md                     ← estado permanente: qué falta hoy
├── CONTINUAR.md                  ← traspaso de la última sesión de trabajo
├── marca/                        ← identidad + guía de usuario (los dos .html y los logos)
├── backend-starter/              ← repo git (rama dev)
└── frontend-starter/             ← repo git (rama dev)
```

`marca/` son los dos entregables que no pertenecen a ninguno de los dos repos: el **kit de identidad** (para Mateo) y la **guía de usuario** (para los clientes). Cada uno es un `.html` autocontenido que se edita ahí y se republica a un enlace fijo. Tampoco están versionados — ver el aviso de arriba.

| Pieza | Stack | Dónde corre |
|---|---|---|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2 | Fly.io → `compraventa-backend-dev.fly.dev` |
| **Frontend** | Vite, React 19, TypeScript estricto, TanStack (Query/Router/Table), Tailwind v4 + shadcn/ui | Vercel |
| **Base de datos + Auth + Storage** | Supabase (Postgres con RLS) | proyecto `driyubkodnsqxbtxcmaz` |

**Tamaño actual:** 57 migraciones · 13 módulos backend · 14 features frontend · **41 permisos** · **122 endpoints** · backend 422 tests / frontend **193** tests, todo en verde. (Backend y permisos contados el 11/09/2026 contra el catálogo en base y el `/openapi.json` desplegado; el conteo del frontend es del 20/09. Este renglón ya se desincronizó dos veces — si lo vas a citar, contá de nuevo.)

### Cómo se hablan

```
Navegador ──login (email+clave)──► Supabase Auth ──► JWT (con company_id y role_id)
    │
    └── cada request ──Bearer JWT──► Backend FastAPI ──► Postgres
                                          │
                                          └── fija los claims del tenant POR TRANSACCIÓN → RLS aísla la empresa
```

**El backend no tiene login propio.** Supabase Auth emite el JWT; el backend lo verifica por JWKS y confía en sus claims. El frontend habla con Supabase **solo** para auth y storage; todo lo demás pasa por el backend.

---

## 3. Las reglas que no se negocian

Están en los `CLAUDE.md` de cada repo (léelos completos antes de escribir código). El resumen de por qué existen:

1. **Multi-tenancy con RLS.** Toda tabla de negocio tiene `company_id`, RLS activo y forzado. Los claims se fijan por transacción, nunca por sesión — la conexión va por Supavisor en modo transacción y una fuga aquí es una fuga de datos entre empresas.
2. **Capas por módulo:** `router` (HTTP) → `service` (negocio) → `repository` (SQL). Un módulo no importa el service de otro; expone funciones de integración.
3. **El backend es la autoridad.** Intereses, estados, stock y códigos los calcula siempre él. El frontend muestra, guía y valida forma — nunca reimplementa una regla.
4. **Dinero en `Decimal`/`NUMERIC(14,2)`, jamás `float`.** En el frontend el dinero es un string decimal que nunca pasa por `parseFloat` para aritmética: se suma en centavos enteros (`sumMoney`, `multiplyMoney`).
5. **Fechas en la zona de la EMPRESA**, no en UTC. Un abono de las 7pm en Bogotá es de ese día, no del siguiente. El backend ya sufrió ese bug (una ventana de 5 horas cada noche); ahora todo compara con `at time zone`.
6. **Permisos:** el backend protege (`require_permission` en cada endpoint, deny-by-default), la UI solo **oculta**. Ocultar el botón no es protección: van siempre los dos.
7. **Idempotencia** obligatoria en toda operación de dinero (un UUID por acción del usuario, no por request).
8. **Auditoría** en la misma transacción para toda acción sensible. `audit_log` es inmutable.
9. **Diseño centralizado:** todo color/radio/sombra/espaciado sale de `tokens.css`. Cambiar la marca completa = editar un archivo.

---

## 4. Ambientes, URLs y accesos

| Qué | Valor |
|---|---|
| App que usa el cliente | **https://prendo.com.co** → redirige (308) a `https://dev.prendo.com.co` |
| Backend | **https://api-dev.prendo.com.co** (la app de Fly se sigue llamando `compraventa-backend-dev`; su `.fly.dev` vive pero el front ya no lo alcanza: el CSP lo bloquea) |
| Correo | **Resend** sobre `prendo.com.co`, conectado a Supabase Auth |
| Supabase | proyecto `driyubkodnsqxbtxcmaz` (*lagranlegal's Dev*) |
| Rama de producción en Vercel | **`dev`** (sí, la rama se llama `dev` y es la que sirve la URL "real") |
| Rama **por defecto** del repo | **`dev`** — cambiada el 22/09: los workflows programados de GitHub **solo corren desde ahí** |
| URLs viejas, todavía vivas | `la-legal-front-end.vercel.app` y `compraventa-backend-dev.fly.dev` — no se apagaron, pero **no son la dirección del producto** |

> ⚠️ **Hoy no existe un ambiente de producción de verdad.** Todo lo anterior es *dev*, incluida la URL que el cliente abre. Montar producción (proyecto Supabase prod + app Fly `compraventa-backend-prod`) es **el único bloqueante real para vender esto**. Pasos en `frontend-starter/docs/DEPLOY.md`.

### Trampas del entorno — leer antes de tocar nada

Cada una costó tiempo real:

- **"Pusheado" no significa "el cliente lo ve".** Verifica el bundle servido, no el commit:
  ```bash
  JS=$(curl -s https://la-legal-front-end.vercel.app/ | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1)
  curl -s "https://la-legal-front-end.vercel.app$JS" | grep -c "TextoQueAcabasDeAgregar"
  ```
- **Hay dos bases de datos.** Los tests corren contra Postgres local (`supabase start`); `.env` y `psql` apuntan a la Supabase dev remota. Una migración nueva va en **las dos**.
- **Hay dos cuentas de Supabase.** El CLI de esta máquina está autenticado con **otra** cuenta. El ref correcto sale siempre de `SUPABASE_URL` en `.env`, nunca de `supabase projects list`.
- **Nunca `supabase config push`.** Empuja `enable_signup = true` y reabre los registros públicos. Para tocar auth: `PATCH` a la Management API.
- **Orden de deploy.** Migración aditiva → antes del deploy. Migración que contrae (NOT NULL, DROP COLUMN) → **después**. Y `supabase db push` aplica **todas** las pendientes de golpe.
- **Los cambios de permisos tardan hasta un minuto** en verse (cache de 60s en ambos lados, deliberado y alineado).
- **CORS:** el backend dev solo acepta el origen de Vercel. Un `vite preview` local **no** puede pegarle — hay que desplegar para probar en vivo.
- **Playwright sí está disponible** en esta máquina, vía el caché de npx (`~/.npm/_npx/<hash>/node_modules/playwright`, con Chromium ya descargado). Sirve para verificar en vivo con login real.

- 🔴 **«Guardar» casi nunca es «aplicar», y ninguna capa avisa.** `git push` despliega en Vercel pero **no en Fly**. `fly deploy` **no** actualiza la Machine del job nocturno — ni `fly secrets set`; ya dejó el job corriendo código viejo **tres veces en un día**. Republicar un artifact **no** mueve el pin si quedó clavado. Guardar una plantilla de correo en Supabase **no** la aplica: la cachea unos minutos. Cambiar una `VITE_*` en Vercel **no** hace nada sin redeploy (se hornean en el bundle). **Verificar siempre el efecto sobre lo servido, nunca la pantalla de configuración.**
- **Un workflow programado solo corre desde la RAMA POR DEFECTO.** `schedule` y `workflow_dispatch` de GitHub Actions ignoran la rama donde está el archivo. Por eso la rama por defecto es `dev`. Si alguien la cambia, los guardianes dejan de correr **y nada lo avisa** (F21-30). Y hay que **correr un workflow nuevo a mano una vez** antes de confiar en su horario.
- **Correr los dos guardianes después de cada deploy.** `scripts/qa/verificar_cadenas.py` (invariantes de datos vivos) y `scripts/qa/verificar_job_nocturno.py` (que la Machine exista, tenga `schedule` y corra la imagen desplegada). Los dos distinguen **0 sano · 1 roto · 2 no se pudo verificar** — y ese tercer código existe porque *"no se pudo verificar" no es "está sano"*.
- **Los reportes DMARC no llegan a un Gmail cualquiera.** Si el buzón del `rua` está en otro dominio, ese dominio tiene que autorizarlo publicando un registro; Gmail no lo hace. Se usa un agregador, o los reportes **no se envían y nadie se entera**.
- **Al diagnosticar un correo, el `iat` del token es cuándo se CANJEÓ, no cuándo se envió.** Un enlace vive hasta una hora, así que un `iat` reciente no prueba que el correo lo sea. **Borrar los correos viejos de la bandeja antes de probar** — medir el correo equivocado ya costó un diagnóstico entero.

---

## 5. Autenticación y alta de usuarios (donde más duele)

**No hay registro público.** El alta es solo por invitación. Ver el runbook completo y el diagnóstico de fallas en **[`RUNBOOK_USUARIOS.md`](RUNBOOK_USUARIOS.md)** — es el documento que hay que abrir cuando "no se puede crear un usuario".

Resumen del flujo:

1. Un admin invita (`POST /identity/invitations`). El backend crea el usuario en Supabase Auth y la fila en `app_user` con estado `invited`. El alta de una **empresa** nueva hace lo mismo con su primer administrador, y también devuelve el enlace.
2. Se entrega un **enlace de un solo uso**, normalmente copiándolo (`send_email: false`): apunta a la app con un `token_hash` que se canjea por POST, así que ninguna vista previa de WhatsApp puede quemarlo. El correo de Supabase sigue existiendo como fallback pero su plantilla no se puede editar en el plan actual, así que ese camino es el frágil.
3. La persona abre el enlace → Supabase valida el token, **deja la sesión activa** y redirige a `/auth/callback`.
4. Ahí elige su contraseña (`updateUser`).
5. Su primer request al backend lo pasa de `invited` a `active`.

**Los tres puntos donde esto se rompe** (los tres ya mordieron):

- El enlace es de **un solo uso**: si el admin lo "prueba" primero, la persona recibe uno muerto. La pantalla lo dice ("Este enlace ya se usó"), así que ya no es un callejón sin salida.
- **`active` significa "ya entró con su propia contraseña"**, no "hizo algún request". Antes no: alguien podía aparecer como Activo sin haber puesto clave nunca, y estar bloqueado para siempre.
- **El correo de Supabase es el único camino frágil que queda** y su plantilla no se puede editar en el plan actual. Todo lo demás —alta de empresa, invitar, recuperar, cambiar la propia contraseña— se resuelve con enlaces que entrega una persona.

---

## 6. Qué leer según lo que vayas a tocar

| Tema | Documento |
|---|---|
| **Empezar / estado de hoy** | [`ESTADO.md`](ESTADO.md) |
| **Retomar tras una pausa** | [`CONTINUAR.md`](CONTINUAR.md) |
| **No se puede crear un usuario** | [`RUNBOOK_USUARIOS.md`](RUNBOOK_USUARIOS.md) |
| **La marca, el logo, los colores, el dominio** | [`marca/README.md`](marca/README.md) → `marca/IDENTIDAD.html` |
| **Qué se le entrega al cliente** | `marca/GUIA_USUARIO.html` — la guía de usuario, **completa: las ocho partes**, publicada y en vivo (versión 6, 22/09/2026). Falta solo lo opcional: las **capturas**. Método para continuarla: `marca/README.md` |
| **Qué se probó y qué se encontró** | `backend-starter/docs/QA_AUDITORIA.md` — registro de la auditoría de calidad, una sección por fase (diez, cerradas el 09/09/2026) |
| Volver a correr esas pruebas | `backend-starter/scripts/qa/README.md` — qué prueba cada script, qué encontró y las trampas de medirlo |
| Lo que la app espera que alguien **decida** | `frontend-starter/docs/DECISIONES_PENDIENTES.md` — cuatro preguntas de negocio o producto, cada una con opciones y consecuencia |
| Reglas obligatorias del backend | `backend-starter/CLAUDE.md` |
| Reglas obligatorias del frontend | `frontend-starter/CLAUDE.md` |
| **Qué se construyó y por qué** (el más útil) | `frontend-starter/docs/IMPLEMENTATION.md` — un bloque por sesión, más reciente arriba |
| Contrato de la API | `backend-starter/docs/API_GUIDE.md` (el shape exacto sale siempre de `/openapi.json`) |
| Multi-tenancy, RLS, capas | `backend-starter/docs/ARCHITECTURE.md` |
| El negocio (intereses, estados, remate) | `backend-starter/docs/CONTEXTO.md` |
| Tokens, componentes, UX | `frontend-starter/docs/DESIGN_SYSTEM.md` |
| Deploy, Vercel, URLs de Supabase | `frontend-starter/docs/DEPLOY.md` |
| Backlog del backend | `backend-starter/docs/PENDIENTES_BACKEND_INFRA.md` |
| Migrar contratos del sistema viejo | `backend-starter/docs/MIGRACION_CONTRATOS.md` |
| **El modelo de efectivo** (por qué el saldo es de la cuenta y no del turno, la caja fuerte, qué falta de multi-caja) | `backend-starter/docs/CAJA_TRAZABILIDAD.md` |
| **Avisos por correo al cliente y a la empresa** (spec, sin código todavía) | `backend-starter/docs/NOTIFICACIONES.md` — catálogo de eventos, modelo de datos, idempotencia, Habeas Data y **siete preguntas de negocio sin contestar** |
| **Ampliar el préstamo** — el "recargo": por qué sucede el contrato en vez de modificarlo, y las decisiones ya tomadas | `backend-starter/docs/RECARGOS.md` |
| **Multi-caja y multi-sucursal (fase 2)** — aplazado; qué se toca el día que llegue, y las tres acciones que mantienen los datos de hoy utilizables | `backend-starter/docs/SUCURSALES.md` |

---

## 7. Principios que se ganaron a los golpes

Cada uno salió de un bug real y caro. No hay que re-derivarlos:

**Sobre la plata**
- **El interés es ingreso; el capital recuperado no.** Prestar no es un gasto, cobrar no es una ganancia.
- **Ingreso no es ganancia.** Una utilidad que no resta el costo de ventas sobreestima por todo lo que costó la mercancía.
- **Una cuenta por cobrar no es plata.** Una venta a crédito no es flujo hasta que el convenio consigna. Se filtra por **tipo de cuenta**, no por concepto.
- **Un traslado no es ingreso ni egreso.** Consignar el efectivo es la misma plata en otro bolsillo.
- **El costo nunca se promedia** (identificación específica, NIIF). El precio vive en el producto; el costo, en el lote.
- **Los saldos se derivan, nunca se guardan.** Un saldo almacenado se desincroniza; uno derivado no puede.

**Sobre el sistema**
- **Un módulo nuevo trae sus propios permisos** desde el día uno.
- **Si un permiso se puede rodear por otra URL, no es un permiso.**
- **Un vínculo que existe en los datos pero no en la aplicación no es trazabilidad.**
- **Un 403 no es una falla:** decir "no se pudo cargar" cuando falta un permiso manda a buscar un problema que no existe.

**Sobre cómo se rompen las cosas**
- **Si la app no muestra que está trabajando, para el usuario está rota.**
- **Un mensaje de error que sirve para todas las causas no sirve para ninguna.** "Intenta de nuevo" es el peor consejo cuando reintentar no puede funcionar.
- **Un documento de traspaso congela la fecha en que se escribió.** `backend-starter/docs/CONTEXTO.md` es del 14/08/2026 y describe la codificación de artículos como era entonces — pieza única, `JOC0001I`. El modelo se partió después en **producto + lote** (`JOC0007` + `JOC0007-01I`, cinco orígenes, cuatro letras reservadas) y el documento nunca lo dijo. Documentar desde ahí produjo una guía de usuario equivocada. **La fuente de una regla es el módulo que la ejecuta** (`inventory/rules.py`, `catalogs/schemas.py`, el schema de Zod del formulario), no el documento que la decidió.
- **Que el código referencie un plugin no significa que esté instalado.**
- **"El resto del código no cambió" ≠ "se ve igual":** un componente compartido puede refactorizarse sin tocar a sus usuarios y aun así cambiarle la cara a todos.
- **"No hay herramienta X en este entorno" es una afirmación con fecha de vencimiento.** Comprobar antes de repetirla.
- **Cambiar la firma de una función exportada exige buscar sus tests en TODO el repo** — acá los tests viven en `tests/`, no junto al código.
- **Una configuración que se ignora en silencio es peor que una que falla:** Supabase descarta un `redirect_to` no permitido sin decir nada, y el síntoma aparece a tres pasos de distancia.

---

## 8. Comandos

```bash
# Backend
cd backend-starter
supabase start                          # Postgres local para tests
pytest -q                               # 422 tests (con Docker levantado; sin él la mayoría se SALTA y pasa igual)
ruff check . && ruff format . && mypy app
fly deploy -c fly.dev.toml              # desplegar a dev

# Frontend
cd frontend-starter
npm run dev
npm run gen:api                         # regenera tipos desde el /openapi.json del backend
npm run lint && npm run typecheck
npm run test -- --run                   # 193 tests
npm run build
git push origin dev                     # Vercel despliega solo desde la rama dev
```
