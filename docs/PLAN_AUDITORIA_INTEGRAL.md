# Auditoría integral — plan (27/09/2026)

> **Qué es.** El plan de la auditoría completa pedida por Mateo el 27/09/2026: probar toda la aplicación,
> consolidar la documentación, revisar la guía de usuario, escribir el runbook de producción y proponer
> mejoras. Es un documento de trabajo: cuando la auditoría cierre, lo que siga vigente se funde en la
> documentación consolidada y este archivo se archiva.
>
> **Continuidad.** Retoma las fases 0–10 de `QA_AUDITORIA.md` (08–09/09/2026; hoy en la historia de git, método vigente en [`QA.md`](QA.md)) y los
> defectos F20/F21. No las repite: las usa como regresión y va sobre lo que nació después (notificaciones,
> ampliaciones, capital del dueño, sucursales, notas crédito, landing, plantillas nuevas).

## Decisiones de Mateo (27/09/2026)

| Tema | Decisión |
|---|---|
| Ambiente | Empresas nuevas `ZZ AI — <frente>` en la Supabase dev; LA GRAN LEGAL no se toca. Local solo para pytest y fechas manipuladas. |
| Arreglos | Se arreglan en la tanda los **críticos y los altos**; medios y bajos quedan reportados. |
| Bugs | **GitHub Issues** en los dos repos, con etiquetas de severidad y módulo. |
| Docs sobrantes | Se **borran** (queda en git). Los de la raíz, que no están versionados, se mueven primero a un repo. |
| Diseño visual | Se agrega una fase de **rediseño visual** después de los arreglos: primero propuesta para aprobar, después código. |
| Avalúo (F4-05) | Si la categoría define LTV, el avalúo es **obligatorio**; sin él solo presta quien tenga `contracts.override_ltv`. |
| Precio de venta (F6-05) | Vender **por debajo** del precio publicado es un descuento: exige `sales.apply_discount`, motivo y auditoría. Por encima, libre. |
| Saldar en el primer mes (F4-11) | Todo contrato causa **al menos un mes** de interés. |

## Principios (no negociables)

1. **El código es la fuente de verdad**, no los docs. Toda afirmación —de un test, de un doc, de la guía— se
   cita contra el módulo que la ejecuta.
2. **Toda aserción de error va contra el `code`**, nunca contra el status solo.
3. **Cada permiso se prueba dos veces:** en la UI (¿oculta/deshabilita?) y en la API pelada con el JWT de ese
   rol (¿403 `PERMISSION_DENIED`?). La UI oculta, no protege.
4. **Todo hallazgo lleva reproducción, causa (archivo:línea) y severidad.** Un arreglo propuesto es una
   hipótesis: se mide antes de implementarlo.
5. **Reportar todo, arreglar en el momento solo lo crítico** (dinero, fuga entre empresas, escalada de
   privilegios). Lo demás espera decisión de Mateo. Lo que requiere definición de negocio va a
   decisiones pendientes, no se implementa por criterio propio.
6. **Un test nuevo se ve fallar sin el fix** antes de darlo por bueno.
7. **Datos reales no se tocan.** LA GRAN LEGAL vive en la misma Supabase dev (Ley 1581). Los agentes de
   medición contra la remota van con `BEGIN TRANSACTION READ ONLY` explícito (PGOPTIONS no protege).

## Severidades

| Nivel | Criterio | Qué se hace |
|---|---|---|
| 🔴 CRÍTICO | Dinero mal contado, fuga entre empresas, escalada de privilegios, pérdida de datos | Se arregla en la tanda, con test visto fallar |
| 🟠 ALTO | Flujo principal roto o bloqueado, reporte engañoso, error sin mensaje | Se reporta; se arregla con visto bueno |
| 🟡 MEDIO | Flujo secundario roto, UX que induce a error, validación faltante | Se reporta |
| ⚪ BAJO | Cosmético, texto, consistencia | Se reporta |

## Ambiente de pruebas

- **Empresas nuevas `ZZ AI — <frente>`** en la Supabase dev, **una por frente de prueba** para que dos agentes
  no compartan caja ni stock (una caja abierta es estado global de la empresa).
- **Usuarios por rol** en cada empresa: Admin, Moderador, Asesor, Bodega, uno por rol a medida con un solo
  permiso (para barrer los 43), y usuarios restringidos por sede donde aplique.
- **Una empresa B** por frente de identidad para probar aislamiento cruzado.
- **Super-admin de plataforma**: la cuenta de Mateo (la usa el orquestador, no los agentes).
- **Front**: `dev.prendo.com.co` con Playwright (`channel: 'chrome'`). **API**: `api-dev.prendo.com.co`.
- **Local** (Postgres de `supabase start`): solo para `pytest` y para pruebas que exigen manipular fechas.

## Fases

| # | Fase | Qué entrega | Quién |
|---|---|---|---|
| **1** | Inventario (solo lectura) | Mapa backend identidad · mapa backend dinero + **oráculo de efectos** · mapa front · clasificación de docs · inventario de infra | 5 agentes en paralelo |
| **2** | Laboratorio | Empresas `ZZ AI — *`, usuarios por rol, catálogo, cuentas, clientes, scripts reutilizables | Orquestador (escrituras) + 1 agente de scripts |
| **3** | Identidad y permisos | Matriz 43 permisos × endpoints × UI × roles semilla + roles a medida; ciclo de vida de usuario, invitación, último admin, caché, sedes, suscripción vencida/suspendida, plataforma, aislamiento A↔B, IDOR | 2 agentes (API / UI) |
| **4** | Contratos | Crear, abonos (meses completos), capital, paz y salvo, prórroga, ampliación, remate, import, snapshot/herencia, job nocturno, impresión | 1 agente |
| **5** | Caja, cuentas y capital | Apertura heredada, arqueo, cierre, reapertura, traslados, gastos, aportes/retiros, caja fuerte, idempotencia | 1 agente |
| **6** | Inventario y tienda | Compras/ingresos, códigos producto+lote, transformaciones, egresos, ventas (descuento, mixta, nota crédito, settlement), anulación, devolución, kardex | 1 agente |
| **7** | El círculo completo (reportes) | Un **libro paralelo** escrito desde el oráculo que recalcula cada KPI, cada reporte y cada Excel y los compara con lo que muestra la app, operación por operación | 1 agente + orquestador |
| **8** | Documentos y notificaciones | Plantillas, impresión, fotos/storage, correos (comprobantes, recordatorios, alertas, baja), límites Ley 2300 | 1 agente |
| **9** | UI/UX pantalla por pantalla | Cada input, botón, validación, estado vacío/carga/error, doble clic, back, responsive 360 px, tema oscuro, teclado, contraste | 2 agentes (mitad de pantallas cada uno) |
| **10** | Seguridad y robustez | RLS por tabla, endpoints públicos, rate limits, cabeceras, dependencias (`npm audit`, `pip-audit`), concurrencia | 1 agente |
| **11** | Consolidación de documentación | Nueva arquitectura documental, contenidos reescritos contra el código, archivo histórico | 3 agentes (back / front / raíz) + orquestador |
| **12** | Guía de usuario | Revisión de `marca/GUIA_USUARIO.html` contra el código, parte 6, funciones nuevas; republicar | 1 agente |
| **13** | Runbook de producción | Paso a paso completo: Supabase, migraciones, Auth, Storage, Fly (app + job), Vercel, DNS, correo, verificación, backups, rollback | 1 agente + orquestador |
| **14** | Recomendaciones | Flujos, UI/UX, patrones, buenas prácticas, comparado con apps profesionales del rubro | 1 agente |
| **15** | Gestión de bugs y regresión | GitHub Issues con plantillas y etiquetas; cada hallazgo abierto como issue; los críticos y altos convertidos en tests; suite E2E de Playwright versionada | Orquestador |
| **16** | Rediseño visual | Auditoría visual pantalla por pantalla → propuesta en lienzo para aprobar → aplicación sobre tokens y componentes compartidos primero, features después | 1 agente de propuesta, luego 2–3 de implementación |

Las fases 3–10 corren en paralelo por olas (máx. 4–5 agentes a la vez: los subagentes gastan el límite de
la cuenta). Cada agente escribe su informe en un archivo propio y **no toca** `QA_AUDITORIA.md` ni los docs:
la consolidación la hace el orquestador.

## Estado

| # | Estado |
|---|---|
| 1 | ✅ 27/09 — cinco informes; ~95 sospechas. Confirmados en código por el orquestador: **P0-1** (CRÍTICO, seguridad — detalle fuera del repo), **B-01** (abono ignora la cuenta elegida), **B-04** (liquidación con caja cerrada no registra nada), **multiplyMoney** con cantidades fraccionarias; y los permisos base viven solo en `seed.sql` (prod) |
| 2 | ✅ 27/09 — `scripts/qa/lab_zzai.py` (`9f463e3`): 8 empresas `ZZ AI — *` (Identidad A/B, Contratos, Caja, Inventario, Reportes, Documentos, UI), 83 usuarios activos (en Identidad A, un rol por cada uno de los 43 permisos), catálogo con herencia, 5 cuentas (cash, 2 bank, settlement, vault) y 3 clientes ficticios por empresa. `--verificar` en verde. Credenciales fuera del workspace (el repo es público). Contraseña vieja de QA retirada y rotada |
| 3–6 | ✅ 27/09 — ola 2 en paralelo, una empresa ZZ AI por frente. Identidad: matriz 48 actores × 127 endpoints = 6096 checks sin discrepancias, 0 fugas por id entre empresas. Contratos, caja e inventario: el patrón sistémico es la **concurrencia** (solo `sales` y `notifications` usan `FOR UPDATE`): doble cobro, dos sucesores, cuentas sobregiradas, doble pago de factura, idempotencia exigida e ignorada. Hallazgos con reproducción en los informes de la ola |
| — | ✅ Tanda de arreglos (commits locales, 21 back + 18 front): A concurrencia e idempotencia (+00061), B permisos/Storage (+00062)/referencias entre empresas/decisiones de Mateo/reportes/errores 500, D y E front. Back 867 tests, front 495 |
| 12 | ✅ guía revisada (54 errores corregidos); se publica tras desplegar |
| 13 | ✅ `PRODUCCION.md` |
| 7 | ✅ 27–28/09 — libro paralelo en ZZ AI — Reportes: 136/142 comprobaciones; mermas, comisiones y descuadres faltaban en el estado de resultados |
| 8 | ✅ 28–29/09 — 14 hallazgos (plantilla activa vaciable, acta, Ley 2300 sin piso, comprobantes) |
| 10 | ✅ 28/09 — RLS, JWT, CSP y CORS sanos; defensa en profundidad aplicada en 00064 |
| — | ✅ 29/09 Tandas F1 (reportes y ventas), F2 (seguridad) y G (front) desplegadas y verificadas en navegador |
| 9, 11, 14–16 | pendiente |

## Hallazgos confirmados en la fase 1

- **P0-1 · CRÍTICO (seguridad).** Detalle fuera del repo, que es público: ver `SEGURIDAD_PRIVADO.md` en la raíz
  del workspace. Se publica aquí cuando esté mitigado.
- **B-01 · CRÍTICO.** `contracts/service.py:851` resuelve la cuenta elegida, pero los `record_movement` de
  las líneas ~895–921 no reciben `account_id`: cae en la cuenta por defecto del medio de pago.
- **B-04 · CRÍTICO.** `accounts/service.py:~240`: si el destino no es efectivo y la caja está cerrada, la
  liquidación no emite movimientos pero audita y responde 200.
- **multiplyMoney · ALTO.** `frontend-starter/src/lib/money.ts:131` multiplica centavos por una cantidad
  fraccionaria sin redondear → importe corrupto → `formatCOP` lanza y cae la pantalla.
