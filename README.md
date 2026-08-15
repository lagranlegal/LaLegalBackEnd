# Backend Starter — Plataforma SaaS para Compraventas

Paquete inicial para arrancar el backend en VS Code con Claude Code.

## Contenido

| Archivo | Propósito |
|---|---|
| `CLAUDE.md` | Guía que Claude Code lee automáticamente: arquitectura, reglas de negocio exactas, convenciones, orden de implementación y DoD. |
| `docs/CONTEXTO.md` | Contexto completo del proyecto y registro de decisiones con el cliente. |
| `docs/ARCHITECTURE.md` | Cómo está armado el backend: tipo de arquitectura, multi-tenancy vía RLS, capas por módulo, diagramas. Léelo antes de tocar código. |
| `docs/API_GUIDE.md` | Qué endpoints existen, qué hacen, con qué permiso, ejemplos — se actualiza en cada paso. Para tipos exactos: `/openapi.json` del servidor corriendo. |
| `supabase/migrations/*.sql` | Esquema completo documentado: 8 migraciones (helpers, plataforma, identidad, clientes/catálogos, contratos, inventario/ventas, caja, auditoría) con RLS, triggers e índices. |
| `supabase/seed.sql` | Catálogo global de permisos y planes + matriz inicial de roles semilla. |

## Cómo empezar

```bash
# 1. Crear el repo e iniciar Supabase local
git init compraventa-backend && cd compraventa-backend
# copiar el contenido de este paquete en la raíz
supabase init          # respetar la carpeta supabase/ existente
supabase start
supabase db reset      # aplica migraciones + seed

# 2. Abrir VS Code y lanzar Claude Code
code .
claude                 # leerá CLAUDE.md automáticamente
```

Primer prompt sugerido para Claude Code:

> Lee CLAUDE.md y docs/CONTEXTO.md. Las migraciones de supabase/migrations son la fuente de verdad del esquema. Implementa el paso 1 y 2 del orden de implementación: esqueleto FastAPI (core/, main.py), settings, conexión async con claims por transacción, verificación JWT por JWKS, get_current_user y require_permission, con sus tests. No avances a los módulos de negocio todavía.

## Reglas de oro (resumen — detalle en CLAUDE.md)

- Toda tabla nueva nace con RLS + test de aislamiento en la misma PR.
- Dinero en `Decimal`/`NUMERIC`; operaciones de dinero con `Idempotency-Key`; una operación = una transacción.
- Estados y stock jamás editables a mano; acciones sensibles siempre auditadas.
- Migraciones aplicadas ya no se editan: crear una nueva.

> `test_migrations.mjs` valida el esquema completo contra PGlite (Postgres WASM): `npm i @electric-sql/pglite && node test_migrations.mjs` — ya ejecutado con éxito.

## Ramas y despliegue

`main` = solo código ya probado en `dev` (deploy a `compraventa-backend-prod` en Fly.io). `dev` = todo el trabajo en curso (deploy a `compraventa-backend-dev`). Nunca se trabaja directo en `main`; se mergea desde `dev` una vez probado. Detalle completo (2 ambientes, costos de Fly, Supabase por ambiente) en `docs/ARCHITECTURE.md` §8.
