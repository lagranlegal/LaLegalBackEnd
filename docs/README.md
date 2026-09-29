# Prendo — puerta de entrada

> **Empieza aquí.** Qué es Prendo, cómo están armadas sus piezas y qué documento leer según lo que vayas a tocar.
> Es el único mapa de documentos del proyecto; los demás enlazan a este. El estado del día (qué falta, qué
> espera a quién) está en [`ESTADO.md`](ESTADO.md).

## 1. Qué es

**Prendo** es un SaaS **multi-tenant** para **compraventas colombianas** (casa de empeño + tienda), vendido por
suscripción. Cada compraventa es una **empresa** con sus datos aislados. Prendo es la plataforma; cada empresa es
un cliente (el primero opera hoy en el ambiente de dev con datos reales). En la app, el menú lateral muestra el
nombre de la empresa; el login y la landing muestran la marca Prendo.

El negocio tiene dos motores que se miden distinto —**empeño** (gana intereses sobre lo prestado) y **tienda**
(gana margen sobre el costo)— unidos por **una caja diaria**. Mezclarlos produce números falsos, y este proyecto
ya pagó ese error varias veces. La vida de un contrato: préstamo contra una prenda → interés mes a mes → mora →
prórroga → remate → la prenda pasa al inventario y se vende. Reglas completas: [`DOMINIO.md`](DOMINIO.md).

## 2. Las piezas

| Pieza | Stack | Dónde corre |
|---|---|---|
| Backend (este repo) | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2 | Fly.io → `api-dev.prendo.com.co` |
| Frontend (`frontend-starter`) | Vite, React 19, TypeScript estricto, TanStack Query/Router/Table, Tailwind v4 + shadcn/ui | Vercel → `dev.prendo.com.co` (landing en `/`, panel en `/inicio`) |
| Base de datos, Auth, Storage | Supabase (Postgres con RLS forzado, Auth con Custom Access Token Hook, bucket privado) | un proyecto (hoy solo dev) |
| Job nocturno | el mismo código del backend, `python -m app.jobs.nightly` | una Fly Machine programada |
| Correo | Resend sobre `prendo.com.co` | invitaciones, recuperación, avisos |
| Marca y guía de usuario | `.html` autocontenidos publicados como artifacts | carpeta `marca/` del workspace |

### Cómo se hablan

```
Navegador ──email + contraseña──► Supabase Auth ──► JWT con company_id y role_id
    │
    ├── cada request ──Bearer JWT──► API FastAPI ──claims por transacción──► Postgres (RLS aísla la empresa)
    │                                   └── correo post-commit ──► Resend
    └── fotos ──supabase-js con su sesión──► Storage (RLS por empresa y por sección)

Fly Machine diaria ──► recalcula estados · vence suscripciones · resúmenes · recordatorios · despacha correos
```

**El backend no tiene login propio**: verifica el JWT de Supabase y confía en sus claims. **El backend es la
autoridad**: intereses, estados, stock, códigos y saldos los calcula él; el front muestra, guía y valida forma,
nunca reimplementa una regla. El front genera sus tipos del `/openapi.json` en vivo.

## 3. Las reglas que no se negocian

1. **Multi-tenancy con RLS**, claims fijados **por transacción** (nunca por sesión: el pooler reusa conexiones).
2. **Capas por módulo**: router → service → repository; un módulo no importa el service de otro.
3. **Permisos**: el backend protege (deny-by-default); la UI solo oculta. Van siempre los dos.
4. **Dinero en `Decimal`/`NUMERIC(14,2)`, jamás `float`**; en el front, string decimal y aritmética en centavos.
5. **Una operación de dinero = una transacción**, con `Idempotency-Key` por acción del usuario y auditoría.
6. **Nada se edita a mano**: estados, stock y saldos salen de documentos; se corrige con contra-documentos.
7. **"Hoy" es la fecha de la empresa** (Bogotá), no la del servidor.
8. **Los errores son un contrato**: `{code, message, details}`; el front decide por `code`.
9. **Todo color, radio y sombra sale de `tokens.css`** en el front.

Detalle y porqué: [`ARQUITECTURA.md`](ARQUITECTURA.md), `../CLAUDE.md` y `frontend-starter/CLAUDE.md`.

## 4. Mapa de documentos

| Documento | Para qué |
|---|---|
| [`ESTADO.md`](ESTADO.md) | el estado de hoy, corto: qué falta, qué espera a Mateo, decisiones abiertas |
| [`DOMINIO.md`](DOMINIO.md) | las reglas de negocio vigentes y su porqué, citadas contra el código |
| [`ARQUITECTURA.md`](ARQUITECTURA.md) | cómo está construido el backend: RLS, capas, auth, bloqueos, idempotencia, errores, job |
| [`API_GUIDE.md`](API_GUIDE.md) | endpoints por módulo con su permiso y el **catálogo de códigos de error** (§15, lo vigila un test) |
| [`OPERACION.md`](OPERACION.md) | ambientes, deploy de dev, trampas del entorno, runbooks (usuarios, caja, alta de cliente), laboratorio |
| [`PRODUCCION.md`](PRODUCCION.md) | el paso a paso para montar y operar producción |
| [`QA.md`](QA.md) | método de QA, la suite, el arsenal de scripts y la **lista única de bugs abiertos** |
| [`diseno/SUCURSALES.md`](diseno/SUCURSALES.md) | diseño de multi-caja y multi-sucursal, aplazado hasta el primer cliente con dos locales |
| [`PLAN_AUDITORIA_INTEGRAL.md`](PLAN_AUDITORIA_INTEGRAL.md) | plan de la auditoría en curso; se borra al cerrarla |
| `../CLAUDE.md` | reglas obligatorias para escribir código del backend (se carga solo en cada sesión del agente) |
| `../scripts/qa/README.md` | qué hace cada script de QA y cómo correrlo |
| `frontend-starter/CLAUDE.md` y `frontend-starter/docs/` | reglas del front, su arquitectura y el sistema de diseño |

**Cómo se mantiene** (cada tipo de cambio toca un solo lugar):

| Al terminar… | Se toca |
|---|---|
| cualquier sesión | `ESTADO.md` (reemplazar, no apilar) |
| una regla de negocio nueva o cambiada | `DOMINIO.md` |
| un endpoint, permiso o código de error | `API_GUIDE.md` (y `DOMINIO.md` §11 si es un permiso) |
| una decisión estructural | `ARQUITECTURA.md` |
| algo operativo o un incidente | `OPERACION.md` |
| un bug encontrado o cerrado | la tabla de `QA.md` §4 (y su issue) |

Lo canónico describe el presente, sin bitácora: el porqué se queda en una o dos líneas; el relato largo vive en
los mensajes de commit.

## 5. Retomar en una sesión nueva

Se cargan solos: `../CLAUDE.md`, `frontend-starter/CLAUDE.md` y la memoria del agente. **No** se carga el
historial de la conversación: lo que no está escrito aquí o en un commit se perdió. Para arrancar:

> Lee `backend-starter/docs/README.md` y `backend-starter/docs/ESTADO.md`. Antes de tocar reglas de plata, lee la
> sección de `DOMINIO.md` que corresponda; antes de desplegar, `OPERACION.md` §2 y §4.

## 6. Comandos

```bash
# Backend (backend-starter/)
supabase start                                  # Postgres local para tests (Docker; sin él casi todo se salta)
.venv/bin/python -m pytest -q tests/unit tests/rls
.venv/bin/python -m pytest -q tests/integration # por tramos: OPERACION.md §5
ruff check . && ruff format --check . && mypy app
./scripts/deploy_dev.sh                         # deploy de dev completo (lo corre Mateo)

# Frontend (frontend-starter/)
npm run dev
npm run gen:api                                 # tipos desde el /openapi.json del backend desplegado
npm run lint && npm run typecheck && npm run test -- --run && npm run build
git push origin dev                             # Vercel despliega solo desde dev
```
