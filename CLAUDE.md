# CLAUDE.md — Backend Plataforma SaaS para Compraventas

Guía de implementación para Claude Code. Leer COMPLETO antes de escribir código.
Contexto ampliado del negocio: `docs/CONTEXTO.md`. Las migraciones ya diseñadas están en `supabase/migrations/` — son la fuente de verdad del esquema.

## Qué es este proyecto

Backend (FastAPI) de una plataforma SaaS **multi-tenant** para compraventas (casas de empeño + tienda). Cada compraventa es una empresa (tenant) con datos aislados por **RLS** en una única base PostgreSQL (Supabase). Dos dominios independientes con contabilidad separada: **Contratos de empeño** e **Inventario/Tienda**, unidos por una caja diaria única con desglose contable por módulo.

- Stack: Python 3.12+, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Supabase (Postgres + Auth + Storage), pytest.
- Deploy: Fly.io (backend), Vercel (front React — repo aparte), Supabase (3 proyectos: dev/staging/prod).
- Migraciones: Supabase CLI (`supabase/migrations/*.sql`), aplicadas solo por CI o `supabase db push`. NUNCA modificar una migración ya aplicada: crear una nueva.

## Reglas de arquitectura (obligatorias)

1. **Multi-tenancy:** toda tabla de negocio tiene `company_id`. RLS activo y forzado. El backend fija los claims del tenant POR TRANSACCIÓN (`set_config('request.jwt.claims', :claims, true)`) porque la conexión va por Supavisor en modo transacción — jamás por sesión.
2. **Capas por módulo:** `router.py` (HTTP) → `service.py` (reglas de negocio, puro y testeable) → `repository.py` (SQL). `schemas.py` para Pydantic in/out. Un módulo NO importa el service de otro; expone funciones de integración (ej. `cashbox.record_movement(tx, ...)`).
3. **Permisos:** todo endpoint lleva `Depends(require_permission("modulo.accion"))`. Deny-by-default: endpoint sin permiso explícito = error de revisión. El catálogo de permisos vive en BD (seed).
4. **Dinero:** `Decimal`/`NUMERIC(14,2)`. Prohibido float. Una operación de negocio = UNA transacción (documento + movimientos de caja + contadores + auditoría). Header `Idempotency-Key` obligatorio en operaciones de dinero (persistido con UNIQUE(company_id, idempotency_key)).
5. **Estados y stock:** nunca editables a mano. El stock solo cambia por ingreso/egreso/venta. El estado del contrato solo lo calcula el servicio (+ job nocturno); la única acción manual es "Rematar" (con permiso, auditada).
6. **Auditoría:** toda acción sensible (descuentos, remates, anulaciones, egresos, cierres/reaperturas, cambios de roles) inserta en `audit_log` en la misma transacción. `audit_log` es inmutable.
7. **Errores:** respuesta uniforme `{code, message, details}` con códigos de negocio: `PAYMENT_PARTIAL_INTEREST_REJECTED`, `CASH_SESSION_NOT_OPEN`, `PERMISSION_DENIED`, `SUBSCRIPTION_EXPIRED`, etc.
8. **API:** REST `/api/v1`, recursos en plural, paginación por cursor, OpenAPI actualizado (el front genera tipos TS de ahí).

## Reglas de negocio críticas (implementar EXACTO)

### Intereses y abonos
- Interés mensual = `tasa_contrato × saldo_capital_actual`. Ej.: 1.000.000 al 5% → 50.000/mes; tras abonar 200.000 a capital → 40.000/mes.
- **Solo se aceptan meses COMPLETOS de interés.** Un pago parcial de interés se RECHAZA (422). El capital solo recibe abono cuando los intereses quedan al día en ese mismo pago o ya lo estaban. El endpoint debe devolver los montos exactos aceptables para que la UI los muestre (1 mes, 2 meses, ..., todo + capital libre).
- Al pagar N meses: `interest_paid_until += N meses`, recalcular estado.

### Máquina de estados del contrato
`months_owed` = meses completos entre `interest_paid_until` y hoy (usando la ventana del SNAPSHOT del contrato, no la config actual).
- `active` (Vigente): 0 meses adeudados. Indefinido mientras pague el interés mensual.
- `in_arrears` (En mora): 1 a N-1 meses adeudados (N = `arrears_window_months` del contrato; metales 4, tecnología 1).
- `in_extension` (Prórroga): al llegar a N meses se dispara automáticamente; `extension_ends_at = fecha_disparo + extension_months` (default 1).
- Prórroga vencida sin pago → candidato a remate (aparece en `GET /contracts/ready-for-auction`). El estado `auctioned` SOLO lo pone la acción manual Rematar.
- `paid`: salda capital + intereses; los artículos se devuelven TODOS juntos; cierra.
- **SNAPSHOT legal:** al crear el contrato se copian tasa, plazo, `arrears_window_months` y `extension_months` desde la categoría/config. Cambios de configuración NO afectan contratos existentes.
- Job nocturno (pg_cron o worker): persistir estados, marcar suscripciones vencidas.

### Remate asistido
`POST /contracts/{id}/auction` (permiso `contracts.auction`): en una transacción — contrato→`auctioned`, items→`auctioned`, crear `inventory_item` en `draft` (cost = saldo capital + intereses pendientes, `origin='auction'`, `source_contract_id`, vínculo en `contract_item.inventory_item_id`), crear `inventory_entry`, auditar. Luego `POST /inventory/items/{id}/publish` valida precio/fotos y emite el código.

### Códigos de inventario
`[letra cat1][cat2][cat3][consecutivo 4 dígitos][letra proveedor | 'R' si remate]` → `JOC0001I` / `JOC0001R`. Consecutivo por (company_id, prefijo) vía `next_counter()` (ya en migraciones, atómico). El código se emite AL PUBLICAR y es inmutable. Costos por identificación específica: cada pieza/lote conserva su costo real; nunca promediar.

### Caja (acto único diario)
- Una sesión por día por caja (fase 1: una caja por empresa, base ÚNICA de efectivo). Sin sesión `open` → toda operación de dinero se rechaza.
- Movimientos SOLO generados por servicios desde documentos (abono, venta, compra, gasto), etiquetados `module` (pawn/store/general) + medio de pago + referencia. Manual: solo gastos/ajustes.
- Cierre: backend calcula `expected_cash` (base + efectivo in − efectivo out) y desglose module×concept×medio; usuario registra `counted_cash`; diferencia SIEMPRE con justificación (sin tolerancia); sesión cerrada = inmutable; acta PDF (secciones EMPEÑO / TIENDA / GASTOS / conciliación de otros medios). Reapertura: permiso `cashbox.reopen`, motivo, auditada.

### Ventas
Cliente opcional. Confirmar venta = transacción: validar stock/estado, emitir número, descontar stock, `cash_movement(module=store)`, comprobante interno (sin DIAN). Anular: permiso, motivo, repone stock, contra-movimiento, auditada. Descuentos (venta y abono): permiso especial + motivo + auditoría.

### Suscripciones (gestión manual)
Super-admin crea empresa (con roles semilla + caja principal + invitación del primer admin) y habilita módulos; renovación = ampliar `expires_at`. Job diario marca `expired` → bloqueo de acceso (login y API). Precios fuera del sistema. Suspender/expirar NUNCA borra datos.

### Roles y permisos
RBAC dinámico por empresa. Roles semilla (Admin, Moderador, Asesor, Bodega) clonables, no eliminables. Permisos solo vía rol. Salvaguardas: siempre ≥1 admin activo; un admin no puede quitarse `identity.manage_roles` ni auto-inactivarse siendo el último. Cache de permisos TTL 60s con invalidación al editar roles.

## Autenticación

Supabase Auth (email+password y Google), **signups públicos desactivados** — alta solo por invitación. JWT verificado por **JWKS** (validar firma, exp, aud, iss). Claims `company_id` y `role_id` vienen del Custom Access Token Hook (en migraciones). `get_current_user` verifica además usuario activo + empresa activa + suscripción vigente (cache corto). `service_role` key SOLO en secretos del backend, solo para operaciones de plataforma.

## Estructura del proyecto (crear así)

```
app/
  core/            # settings (pydantic-settings), db (async engine + claims por TX), security (JWKS, deps), errors, logging
  common/          # paginación cursor, idempotencia, tipos Money
  modules/
    platform/      # empresas, planes, suscripciones (solo super-admin)
    identity/      # usuarios, invitaciones, roles, permisos
    customers/
    catalogs/      # categorías (árbol 3 niveles), proveedores
    contracts/     # contratos, abonos, estados, remate
    inventory/     # artículos, ingresos, egresos, códigos
    sales/
    cashbox/       # sesiones, movimientos, gastos, cierre
    audit/
    reports/
  jobs/            # job nocturno (estados, suscripciones)
  main.py
tests/
  unit/            # reglas: intereses, estados, códigos, cierre  (coverage ≥90% en contracts y cashbox)
  integration/     # API con BD local
  rls/             # aislamiento: tenant A nunca ve datos de tenant B (por CADA tabla)
supabase/
  migrations/      # YA DISEÑADAS — aplicar, no reinventar
  seed.sql
```

## Orden de implementación (no saltarse pasos)

1. **Infra local:** `supabase init` + copiar migraciones + `supabase start` + `supabase db reset` (aplica migraciones + seed). Esqueleto FastAPI con core/ (settings, db, errors, logging) y CI (ruff, mypy, pytest).
2. **Seguridad base:** verificación JWKS, `get_current_user`, `require_permission`, claims por transacción, tests RLS del esqueleto.
3. **platform + identity:** crear empresa (con seeds por empresa), suspender, suscripción manual; invitaciones, roles, matriz de permisos, salvaguardas.
4. **customers + catalogs:** CRUD con validaciones de árbol y letras.
5. **contracts:** crear contrato (snapshot, consecutivo, PDF con firma), abonos (validación de meses completos), máquina de estados + job, migrados (legacy_code — implementado como `POST /contracts/import`, ver `docs/MIGRACION_CONTRATOS.md`).
6. **cashbox:** sesiones, movimientos automáticos, gastos, cierre con desglose + acta PDF, reapertura.
7. **inventory + sales:** códigos, ingresos, egresos, ventas, anulación, remate asistido (integra contracts+inventory+cashbox).
8. **audit + reports:** consulta de auditoría, KPIs, histórico de cierres.

## Definición de Hecho por PR

- Migración nueva incluye RLS + test de aislamiento de la tabla.
- Endpoint con permiso + test de integración + regla de negocio con test unitario.
- Acción sensible → auditoría verificada en test.
- OpenAPI actualizado; `ruff` + `mypy` limpios; sin `float` en dinero; sin secretos en código.

## Variables de entorno (.env.example — crearlo)

```
DATABASE_URL=postgresql+asyncpg://...   # Supavisor transaction mode (puerto 6543)
SUPABASE_URL=
SUPABASE_JWKS_URL=${SUPABASE_URL}/auth/v1/.well-known/jwks.json
SUPABASE_SERVICE_ROLE_KEY=              # solo backend, nunca en front
JWT_AUDIENCE=authenticated
ENVIRONMENT=dev
SENTRY_DSN=
```

## Comandos

```bash
supabase start                 # entorno local
supabase db reset              # aplica migraciones + seed
uvicorn app.main:app --reload
pytest -q                      # todo; pytest tests/rls para aislamiento
ruff check . && ruff format . && mypy app
```
