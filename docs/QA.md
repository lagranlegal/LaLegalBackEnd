# QA — método, suite, arsenal y bugs abiertos

> **Qué es.** Cómo se prueba este proyecto, con qué herramientas, y la **lista única** de defectos abiertos.
> La historia de las auditorías (fases 0–10 del 08–09/09/2026, la serie F20/F21 y la auditoría integral del
> 27/09/2026) no vive aquí: está en la historia de git de `docs/QA_AUDITORIA.md` y en los informes de la
> auditoría. Esta tabla es un **resumen**; el detalle de cada bug pasa a GitHub Issues.

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

## 4. Bugs abiertos (29/09/2026)

Lo cerrado en las tandas de la auditoría integral (concurrencia e idempotencia, cuentas en abonos y anulaciones,
LTV y avalúo, precio bajo el publicado, mínimo un mes, reportes de la fase 7, plantillas vaciables, piso de la Ley
2300, comprobantes y tope diario, Storage, errores 500) **no aparece aquí**. Cuando un bug se cierra, sale de la
tabla en el mismo commit que lo arregla.

| ID | Sev | Repo | Resumen | Estado |
|---|---|---|---|---|
| P0-1 | 🔴 | infra | Hallazgo de seguridad; el detalle vive fuera del repo, que es público | espera a Mateo |
| LAB-01 | 🟡 | lab | Los usuarios y clientes del laboratorio usan un dominio de correo real de un tercero: si una empresa de laboratorio enciende avisos, salen correos a ese dominio y los rebotes dañan la reputación de `prendo.com.co`. Mover el laboratorio a un subdominio propio sin MX | abierto; avisos del laboratorio apagados |
| VOID-sess | 🟡 | back | Anular una venta exige caja abierta aunque la venta entró por banco o convenio | abierto (cambia comportamiento) |
| SETTLE-code | 🟡 | back | Liquidar un convenio hacia efectivo con la caja cerrada responde un error genérico, no `CASH_SESSION_NOT_OPEN` (el front no abre el recuadro «Caja cerrada») | abierto |
| DOC-acct | 🟡 | back | `contract_payment`, `expense` e `inventory_entry` tienen `account_id` (00024) que nunca se escribe; la cuenta solo queda en el movimiento | abierto |
| F4-07…17 | 🟡/⚪ | back | Resto de la fase de contratos (validaciones y bordes menores) | abierto |
| F5-07…11 | 🟡 | back | Caja: la exige la operación y no siempre la cuenta, cuenta «Transferencias» automática, cuenta inactiva que opera, saldo inicial sin auditoría, liquidar a la caja fuerte | abierto |
| F6-07…22 | 🟡/⚪ | back/front | Inventario y tienda: egresos fraccionarios, saldos negativos, `payment_method` incoherente, clave de idempotencia reusada con otro cuerpo, motivos | abierto |
| F7-12/14/17 | 🟡/⚪ | back/front | Reportes: Excel Resumen con signos, compras a proveedor inconsistentes entre vistas, detalles del egreso | abierto |
| F1-pend | 🟡 | back | Una transformación de piezas rematadas no hereda el interés capitalizado; una devolución a proveedor no toca cuentas por pagar; `/reports/series` sin las líneas nuevas del estado de resultados; ventas viejas con `list_price` nulo | abierto |
| INV-round | ⚪ | back | El ingreso de inventario no redondea por línea, a diferencia de venta y transformación | abierto |
| F3-09/10/11 | ⚪ | back | Prórroga con fecha pasada, `limit` sin tope, 409 `CONFLICT` genérico, `open` acepta `{}` | abierto |
| TEST-flaky | ⚪ | back | `test_platform::test_get_and_list_companies_include_plan_and_subscription` falla en la suite completa y pasa sola | abierto |
| JOB-sched | 🟡 | infra | Hipótesis: cada `machine update` reinicia el reloj del `--schedule daily` ([`OPERACION.md`](OPERACION.md) §3) | medir |
| MAIL-dmarc | ⚪ | infra | DMARC sin publicar, prueba de spam pendiente, webhook de Resend (`delivered`/`bounced` → `email_invalid_at`) sin construir | abierto |
| F9-* | 🟠/🟡/⚪ | front | 64 hallazgos de UI/UX pantalla por pantalla (2 altos ya enviados); entre los medios: bloqueo previo con caja cerrada, confirmación del abono sin resumen, foco de inputs con contraste bajo, filas no abribles con teclado, Inicio vacío para roles sin reportes, bundle único de 1,9 MB sin code-splitting | abierto; van a la fase de rediseño |
| FE-misc | 🟡/⚪ | front | Coma decimal en los diálogos de egreso y devolución; firmas que saltan solas a la última hoja en plantillas largas; un rango sin cierres pero con banco muestra «No hay cierres»; `fetchAllPages` corta a 10.000 filas en silencio; Inter en pantallas internas a 360 px sin revisar | abierto |
| DB-contract | ⚪ | back | Contraer `customer.doc_photo_url` (00050 dejó las dos columnas sincronizadas) | abierto |

Decisiones de negocio pendientes (no son bugs): [`ESTADO.md`](ESTADO.md) §4.
