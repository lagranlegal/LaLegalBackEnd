# QA — método, suite, arsenal y bugs abiertos

> **Qué es.** Cómo se prueba este proyecto, con qué herramientas, y la **lista única** de defectos abiertos.
> La historia de las auditorías (fases 0–10 del 08–09/09/2026, la serie F20/F21 y la auditoría integral del
> 27/09/2026) no vive aquí: está en la historia de git de `docs/QA_AUDITORIA.md` y en los informes de la
> auditoría. Los bugs abiertos viven en GitHub Issues (§4).

## 1. Principios de método

Cada uno salió de un error real, y valen igual para escribir código, tests, docs o la guía de usuario.

1. **El código es la fuente de verdad.** Lo que un documento, un test o un informe afirma se verifica contra el
   módulo que lo ejecuta, no contra otro documento ni contra lo que ya estaba escrito (escribir la guía de usuario
   contra el código destapó veinte hallazgos en tres días). **Un documento de traspaso congela su fecha**, y **una
   cita con número de línea envejece sola**: se cita el archivo y la función.
2. **Toda aserción de error va contra el `code`**, nunca contra el status solo. Un test que mira el status no
   cubre nada: así pasó once días un `NOT_FOUND` donde el front esperaba `CASH_SESSION_NOT_OPEN`.
3. **Cada permiso se prueba dos veces**: en la pantalla (¿oculta o deshabilita?) y en la API pelada con el JWT de
   ese rol (¿403 `PERMISSION_DENIED`?). La UI oculta; el backend protege.
4. **Un test no prueba nada hasta verlo fallar sin el fix.** Un test que sigue verde tras invertir la regla no la
   cubría (los 26 del recargo pasaron con el comportamiento opuesto).
5. **Un fixture inventado no falla: bendice.** Los fixtures se copian de una respuesta real, no se escriben de
   memoria (`max_ltv_pct` llega como `"30.00"`, no como número; un campo de dinero guarda `"1000000.00"`, no lo que
   muestra). **Un fixture al que le falta un permiso deja un invariante sin probar.**
6. **Un arreglo propuesto es una hipótesis**, igual que una causa: se mide antes de implementarlo. Dos arreglos de
   informes anteriores resultaron imposibles o dañinos al medirlos.
7. **Todo hallazgo lleva reproducción, causa (archivo y función) y severidad.**
8. **Reportar todo, arreglar en el momento solo lo crítico** (dinero, fuga entre empresas, escalada de
   privilegios). Lo que requiere una definición de negocio va a decisiones, no se implementa por criterio propio.
9. **Una invariante sobre datos vivos va a un guardián** que sale con código 1, no a un test contra una base
   efímera; y **un guardián que lee código con regex de literales no ve el caso dinámico** (`action=direction`).
10. **Una CI que siempre falla no dice nada.**
11. **Datos reales no se tocan** (ver [`OPERACION.md`](OPERACION.md) §4.2) y **las lecturas sobre la remota van
    con `BEGIN TRANSACTION READ ONLY`**.
12. **"Pusheado" no es "servido"**: una verificación en vivo se hace contra el bundle y la API desplegados, en
    Chrome real con Playwright (`channel: 'chrome'`).

### Severidades

| Nivel | Criterio | Qué se hace |
|---|---|---|
| 🔴 CRÍTICO | dinero mal contado, fuga entre empresas, escalada de privilegios, pérdida de datos | se arregla ya, con test visto fallar |
| 🟠 ALTO | flujo principal roto, reporte engañoso, error sin mensaje | se arregla con visto bueno |
| 🟡 MEDIO | flujo secundario roto, UX que induce a error, validación faltante | se reporta |
| ⚪ BAJO | cosmético, texto, consistencia | se reporta |

## 2. La suite

- `tests/unit` (reglas puras, sin BD: intereses, estados, códigos, límites, catálogo de errores, guards de
  endpoints, etiquetas de auditoría), `tests/integration` (HTTP de punta a punta contra Postgres local),
  `tests/rls` (aislamiento tabla por tabla, privilegios de `anon`, Storage).
- Cómo correrla por tramos y con qué tope de tiempo: [`OPERACION.md`](OPERACION.md) §5. Sin Docker casi todo se
  salta y "pasa".
- **Tests que son contratos**: `test_error_catalog.py` (códigos del backend ↔ `API_GUIDE.md` §15, en las dos
  direcciones), `test_endpoint_guards.py` (todo endpoint con permiso, salvo excepciones escritas),
  `test_audit_actions.py` (toda acción auditada tiene etiqueta), el catálogo de avisos ↔ la tabla sembrada.
- Las cifras de la suite cambian cada día: viven en [`ESTADO.md`](ESTADO.md), con la fecha de medición.

## 3. El arsenal (`scripts/qa/`)

Manual completo: [`../scripts/qa/README.md`](../scripts/qa/README.md). Lo principal:

| Script | Para qué |
|---|---|
| `lab_zzai.py` | crea y verifica el laboratorio de ocho empresas `ZZ AI` ([`OPERACION.md`](OPERACION.md) §9) |
| `map_endpoints.py`, `matrix.py`, `analyze_matrix.py` | mapa endpoint → permiso desde `/openapi.json` y el AST de los routers; matriz rol × endpoint (`require_permission` se evalúa antes del body, así se barre todo sin escribir) |
| `concurrencia.py` | operaciones de dinero simultáneas (doble cobro, sobregiro, doble pago) |
| `seed_contratos.py` | siembra contratos en cualquier estado vía `POST /contracts/import` (`--limpiar` borra por id) |
| `verificar_job_nocturno.py`, `verificar_cadenas.py` | los guardianes (0 sano · 1 roto · 2 no se pudo verificar) |
| `verificar_sedes.py` | la premisa de una caja por empresa, al dar de alta una |
| `verificar_saldos.py`, `verificar_regresion_caja.py` | saldos derivados y arqueo |
| `ui_*.js` | recorridos de UI con Playwright: formularios, responsive a 360 px, accesibilidad y contraste, impresión, caja cerrada, recargo, alta |

## 4. Bugs abiertos

Los bugs abiertos viven en **GitHub Issues**, no en este documento: los de la auditoría integral llevan la etiqueta
`auditoría-2026-09` ([backend](https://github.com/lagranlegal/LaLegalBackEnd/issues?q=is%3Aissue+label%3Aaudito%C3%ADa-2026-09)
· [front](https://github.com/lagranlegal/LaLegalFrontEnd/issues?q=is%3Aissue+label%3Aaudito%C3%ADa-2026-09)).

Un bug nuevo se registra como issue en el repo donde empieza el arreglo (si toca los dos, se enlaza el otro), con
**Qué pasa**, **Cómo reproducirlo** (sin credenciales ni datos de clientes), **Qué se esperaba**, **Dónde está**
(archivo y función) y **Arreglo sugerido** marcado como hipótesis (principios 6 y 7), y con una etiqueta de
severidad (`sev:alta`, `sev:media`, `sev:baja`, según la tabla de §1) y una de área (`área:contratos`, `área:caja`,
`área:inventario`, `área:ventas`, `área:reportes`, `área:notificaciones`, `área:plantillas`, `área:identidad`,
`área:ui`, `área:infra`). El issue se cierra en el commit que lo arregla (`Closes #N`).

**Los hallazgos de seguridad nunca van a Issues**: los repos son públicos. Se registran fuera del repo y se tratan
directamente con Mateo.

Decisiones de negocio pendientes (no son bugs): [`ESTADO.md`](ESTADO.md) §4.

## 5. Mejoras propuestas (no son bugs)

Las mejoras propuestas viven en un solo lugar: [`RECOMENDACIONES.md`](RECOMENDACIONES.md) (fase 14, 30/09/2026), con prioridad, esfuerzo y porqué. Esta sección ya no las repite.
