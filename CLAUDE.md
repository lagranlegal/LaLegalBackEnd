# CLAUDE.md — Backend de Prendo

Reglas obligatorias para escribir código en este repo. Leer completo antes de tocar nada.
**Documentación:** empieza en `docs/README.md` (mapa) y `docs/ESTADO.md` (estado del día). Las reglas de negocio
con su porqué: `docs/DOMINIO.md`. Cómo está construido: `docs/ARQUITECTURA.md`. Contrato de API y catálogo de
errores: `docs/API_GUIDE.md`. Deploy y trampas: `docs/OPERACION.md`. **La fuente de verdad es el código**: si un
documento lo contradice, gana el código y se corrige el documento en el mismo commit.

## Qué es

Backend (FastAPI) de **Prendo**, SaaS **multi-tenant** para compraventas colombianas (empeño + tienda). Cada
compraventa es una empresa con datos aislados por **RLS** en una sola base Postgres (Supabase). Dos dominios con
contabilidad separada —**contratos de empeño** e **inventario/tienda**— unidos por una caja diaria con desglose por
módulo.

- Stack: Python 3.12+, FastAPI, SQLAlchemy 2.0 async (Core), Pydantic v2, Supabase (Postgres + Auth + Storage), pytest.
- Deploy: Fly.io (API + Machine programada del job nocturno), Vercel (front, repo aparte). **Hoy existe un solo
  ambiente (dev)**; producción: `docs/PRODUCCION.md`.
- Migraciones: `supabase/migrations/*.sql`, aplicadas con `supabase db push`. **Nunca se edita una migración
  aplicada**: se crea una nueva. Permisos base y planes viven en `supabase/seed.sql` (no lo aplica `db push`).

## Reglas de arquitectura (obligatorias)

1. **Multi-tenancy:** toda tabla de negocio tiene `company_id`, RLS activo y forzado, y al menos una policy de
   SELECT. Los claims se fijan **por transacción** (`SET LOCAL ROLE authenticated` +
   `set_config('request.jwt.claims', …, true)`), jamás por sesión: Supavisor en modo transacción reusa conexiones.
2. **Capas:** `router.py` (HTTP) → `service.py` (reglas; un método = una transacción) → `repository.py` (SQL, sin
   decisiones). `schemas.py` para Pydantic. Reglas puras en `rules.py`. **Un módulo no importa el service de
   otro**: usa su `integration.py`.
3. **Permisos:** todo endpoint lleva `Depends(require_permission("modulo.accion"))`. Deny-by-default; las
   excepciones a propósito se escriben en `tests/unit/test_endpoint_guards.py` con su porqué. **Un módulo nuevo
   trae sus propios permisos** (`view`/`manage` + uno especial por acción que mueva plata o sea irreversible), y
   la migración que los agrega los otorga a los roles que tenían los equivalentes.
4. **Dinero:** `Decimal`/`NUMERIC(14,2)` (`Money`, `PositiveMoney`); cantidades `NUMERIC(14,3)` (`Quantity`).
   Prohibido `float`. Una operación de negocio = **una** transacción (documento + movimientos + contadores +
   auditoría). `Idempotency-Key` persistida con `UNIQUE(company_id, idempotency_key)` y buscada **después** del
   bloqueo.
5. **Concurrencia:** toda operación que modifica un documento o valida un saldo toma la fila con `FOR UPDATE`
   (contrato, cuentas, registradora, venta, nota crédito, compra) y revalida después; sin fila propia, advisory
   lock de transacción. Detalle: `docs/ARQUITECTURA.md` §6.
6. **Nada se edita a mano:** estados, stock y saldos salen de documentos. El estado del contrato lo calcula el
   servicio (+ job nocturno); las únicas acciones manuales son Rematar y Ampliar el préstamo. El saldo de toda
   cuenta, incluido el cajón, se **deriva** de sus movimientos. Se corrige con contra-documentos.
7. **Auditoría:** toda acción sensible **y** la operación diaria (venta, abono, apertura de caja, ingreso) escriben
   en `audit_log` (inmutable) en la misma transacción; el catálogo de acciones está fijado en
   `tests/unit/test_audit_actions.py`, que el front usa para sus etiquetas.
8. **Errores:** `{code, message, details}` con código de negocio estable. **Todo código nuevo va a la tabla de
   `docs/API_GUIDE.md` §15 en el mismo commit** (`tests/unit/test_error_catalog.py` lo exige en las dos
   direcciones). Lo que rechaza la base (UNIQUE, CHECK, NOT NULL) sale como 409/422 con envelope, nunca 500. Un
   error nombra la acción que falta, no solo niega.
9. **"Hoy" es la fecha de la EMPRESA:** `platform.integration.get_company_today` / `get_company_timezone`; nunca
   `date.today()` ni `current_date`, tampoco en fixtures de tests.
10. **API:** REST `/api/v1`, recursos en plural, paginación por cursor (por fecha donde el orden importa),
    OpenAPI al día (el front genera sus tipos de ahí). Endpoints públicos solo bajo `/api/v1/public/` con token
    firmado que dice a quién, GET que nunca escribe y límite de tasa.
11. **Trabajo post-commit** (correos): el servicio registra la entrega como último paso de su transacción y el
    router llama `notifications.dispatcher.send_after_commit` como última acción. Un aviso nunca tumba la operación.

## Reglas de negocio críticas (resumen normativo; porqué y detalle en `docs/DOMINIO.md`)

- **Interés mensual = tasa del contrato × saldo de capital.** Solo **meses completos**: el parcial se rechaza
  (`PAYMENT_PARTIAL_INTEREST_REJECTED`); el capital solo se abona con los intereses al día; `payment-options`
  devuelve los montos exactos. **Saldar causa mínimo un mes** (`rules.minimum_payoff_months`).
- **Estados:** `active` (0 meses adeudados) → `in_arrears` (1…N−1) → `in_extension` (al llegar a N =
  `arrears_window_months` del snapshot; fin = ancla + N + `extension_months`). Terminales: `paid`, `auctioned`
  (solo Rematar), `superseded` (ampliado), todos en `rules.TERMINAL_STATUSES`. "Listo para remate" = `in_extension`
  vencida, no es un estado.
- **SNAPSHOT legal:** tasa, plazo, ventana, prórroga y ventana de ampliación se copian al contrato; cambiar la
  configuración no toca contratos firmados.
- **LTV:** con LTV en la categoría el avalúo es obligatorio; prestar sin avalúo o sobre el techo exige
  `contracts.override_ltv`.
- **Ampliar el préstamo:** no es un UPDATE del capital; el contrato se sucede (`superseded` → sucesor con
  `parent_contract_id`/`root_contract_id`). Ventana medida desde la raíz; a la caja sale solo el delta; el interés
  vencido nunca se capitaliza; el sucesor hereda inicio de la raíz y ancla del padre, y guarda `extended_on`.
- **Remate:** contrato y prendas `auctioned`, artículo en `draft` con costo = capital + interés pendiente y
  `capitalized_interest` aparte (la base de costo en el resultado es el capital).
- **Inventario:** producto + lote; costo por identificación específica, nunca promedio. Código
  `JOC0007` / `JOC0007-01I`, emitido al publicar e inmutable; letra de origen derivada de punteros excluyentes;
  `R`, `P`, `T`, `D` reservadas (`inventory/rules.py`).
- **Caja:** una cuenta `cash` activa por empresa; quien exige turno abierto es el **tipo de cuenta**, no la
  operación; abrir hereda el saldo, contar emite un `adjustment` (`session_id = NULL`); cierre sin tolerancia con
  justificación; reabrir revierte el ajuste del cierre. `vault` solo por traslado; `settlement` no financia
  salidas; la comisión de un convenio se deriva.
- **Ventas:** vender bajo el precio publicado **es un descuento** (`sales.apply_discount`, motivo, auditoría);
  bajo el costo también exige ese permiso. Anular devuelve por la misma cuenta. Devolver devuelve lo pagado, en la
  misma proporción de nota crédito y plata.
- **Capital del dueño:** ni aporte es ingreso ni retiro es gasto; el estado de resultados lee documentos, no
  movimientos. Retirar sobre la utilidad solo se advierte.
- **Avisos:** los del cliente nacen apagados; Ley 2300 es un piso que la empresa no afloja; los comprobantes no
  son cobranza.
- **Suscripciones:** manuales; el job marca `expired` y eso bloquea (`402`). Suspender o vencer nunca borra datos.
- **Roles:** RBAC dinámico por empresa, roles semilla clonables; siempre ≥1 admin activo; nadie asigna más
  permisos de los que tiene; caché de permisos 60 s.

## Autenticación

Supabase Auth, **signups cerrados**: alta solo por invitación. JWT verificado por JWKS (firma, exp, aud, iss).
Claims `company_id`/`role_id` del Custom Access Token Hook (para `active` e `invited`). `active` = entró con su
propia contraseña (claim `amr`). Los enlaces de invitación/recuperación apuntan a la app con `token_hash` y se
canjean por POST; **nunca** se escriben en logs ni en `audit_log`. La `service_role` solo en secretos del backend.

## Estructura

```
app/
  core/      settings, db (claims por TX, NullPool), security (JWKS, permisos), errors, logging, security_headers, observability
  common/    money, idempotency, pagination, tenant_time, search, rate_limit, cors, co_holidays
  modules/   platform identity company customers catalogs contracts cashbox accounts capital
             inventory sales audit reports notifications      (14; cada uno router/service/repository/schemas)
  jobs/      nightly.py — estados, suscripciones, resúmenes, recordatorios, despacho de correos
tests/       unit/ (reglas puras y contratos) · integration/ (HTTP contra Postgres local) · rls/ (aislamiento)
supabase/    migrations/ (fuente de verdad del esquema) · seed.sql (permisos y planes)
scripts/     deploy_dev.sh · export_openapi.py · qa/ (laboratorio, matrices, guardianes)
```

## Definición de Hecho por commit

- Migración nueva: RLS + policy de SELECT + test de aislamiento; aplicada también en la base local de tests.
- Endpoint: permiso + test de integración; regla de negocio: test unitario **visto fallar sin el fix**.
- Aserciones de error contra el `code`, no solo el status. Fixtures copiados de respuestas reales.
- Acción sensible: auditoría verificada en test.
- OpenAPI al día; código de error en `API_GUIDE.md` §15; `ruff check`, `ruff format --check` y `mypy app` limpios;
  sin `float` en dinero; sin secretos (el repo es **público**: ni llaves, ni contraseñas, ni datos de clientes).
- Documentación en el mismo commit: la regla en `docs/DOMINIO.md`, el endpoint en `docs/API_GUIDE.md`, lo
  operativo en `docs/OPERACION.md`, el bug en `docs/QA.md` §4, y `docs/ESTADO.md` al cerrar la sesión.

## Variables de entorno

Ver `.env.example` (comentado variable por variable): base por Supavisor (6543), Supabase, CORS, `FRONTEND_URL`,
Resend, firma de los enlaces de baja, `PUBLIC_API_URL`, Sentry.

## Comandos

```bash
supabase start && supabase db reset             # local, con Docker (sin él casi todo se salta y "pasa")
.venv/bin/python -m pytest -q tests/unit tests/rls
.venv/bin/python -m pytest -q tests/integration # por tramos si la herramienta tiene tope de tiempo
ruff check . && ruff format --check . && mypy app
./scripts/deploy_dev.sh                         # deploy de dev: lo corre Mateo (docs/OPERACION.md §2)
```
