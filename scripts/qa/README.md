# Arsenal de QA

Los scripts que produjeron la auditoría de [`docs/QA_AUDITORIA.md`](../../docs/QA_AUDITORIA.md). **No son tests de pytest** y por eso viven acá y no en `tests/`: pegan contra el backend **desplegado en dev** con usuarios reales, así que recogerlos en la suite haría que `pytest -q` saliera a la red y modificara datos.

Lo que sí quedó automatizado en CI —guards de endpoint, catálogo de errores, smoke de listados, contraste de tokens— está en `tests/` y en `frontend-starter/tests/`. Acá vive lo que **no debe** correr en cada PR: barridos de cinco minutos contra un entorno real.

## Por qué existen

La matriz de permisos completa son 109 endpoints × cada rol. Hacerla por pantalla serían días; por API son cinco minutos y no deja nada sin cubrir. Lo mismo con el resto: comprobar 36 permisos contra 13 módulos a mano es donde se cuelan los huecos.

## Preparar

```bash
cd backend-starter
pip install httpx                        # ya está en el entorno del proyecto
export QA_PASSWORD='...'                 # opcional; default: la del laboratorio
```

Las credenciales salen solas de los `.env` de los dos repos (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL`). **Nada de esto se hardcodea acá.**

El laboratorio (empresas espejo, usuarios por rol, datos sembrados) está descrito en `docs/QA_AUDITORIA.md` §"El laboratorio". Con el `SUPABASE_SERVICE_ROLE_KEY` se pueden crear usuarios y fijarles contraseña sin gastar cuota de correo, así que no hace falta la cuenta de nadie.

## Qué hay

**Python — API contra el backend desplegado**

| Script | Qué hace | Qué encontró |
|---|---|---|
| `qa.py` | El arsenal. Login contra Supabase Auth, cliente HTTP por actor, y `check()` para registrar comprobaciones. **Todo error se asevera por `code`, nunca por status solo** — un test que mira el status y no el código no cubre nada. | — (es la base de los demás) |
| `map_endpoints.py` | Mapa canónico ruta → permiso. Los paths salen de `/openapi.json` (la verdad) y el permiso del AST de los `router.py`. Detecta el «bug de revisión» de `CLAUDE.md`: un endpoint sin `Depends(require_permission(...))`. | Cero endpoints sin guard |
| `matrix.py` | La matriz completa: cada endpoint × cada rol, con el permiso y sin él. | 420/420 correctas |
| `analyze_matrix.py` | Lee el resultado y saca las discrepancias agrupadas por endpoint. | — |
| `refresh_sessions.py` | Renueva los JWT del laboratorio cuando expiran a mitad de un barrido. | — |
| `concurrencia.py` | Lanza N peticiones **en el mismo instante** (todas esperando un evento común, no en fila): ventas de la última unidad, misma clave de idempotencia, aperturas de caja. | **F10-01** — el 500 bajo carrera |
| `seed_contratos.py` | **Siembra**, no prueba: 22 contratos que cubren los seis estados en LA GRAN LEGAL, vía `POST /contracts/import` (sin caja, sin `cash_movement`). Las fechas se derivan con el `rules.add_months` del backend, así que este archivo no puede discrepar del servidor. `--verificar` cuenta, `--limpiar` borra. | — (herramienta; el registro está en `QA_AUDITORIA.md` → "Datos de prueba en LA GRAN LEGAL") |
| `verificar_sedes.py` | **Vigila la premisa de la que cuelga aplazar multi-sucursal**: que cada empresa opere en un solo lugar físico (una registradora activa, un cajón activo y ligado). Sale con código **1** si encuentra algo, así que sirve en un cron. Es un script y no un test porque **un test de CI corre contra una base efímera y nunca vería que una empresa real creció una segunda caja**. | Las 7 empresas sin ligar, antes de `00052` · Ver [`SUCURSALES.md`](../../docs/SUCURSALES.md) §5 y §7 |
| `verificar_despliegue_11_09.js` | Los cinco puntos que trajo Mateo de probar con el cliente, contra el backend **desplegado** y con login real: el buscador desde tres letras (y que un `&` suelto no lo reviente), `keep_anchor` en los contratos vivos y `forgive` intacto en los cerrados, y el módulo de capital entero — incluido que **un aporte no mueva la utilidad y un retiro no mueva los gastos**, que es la regla de fondo. Necesita `QA_ANON_KEY`. | 25 OK · 0 MAL (11/09/2026) |
| `verificar_recargo_ancla.js` | Ejerce el recargo sobre un contrato con fecha **pasada**, que es la única forma de distinguir el comportamiento nuevo del viejo (con un contrato de hoy, heredar la fecha y ponerla en hoy dan lo mismo). Siembra por `/contracts/import`. | 11 OK · 0 MAL — contrato del 22/08 ampliado el 11/09 conserva el 22/08 |
| `ui_caja_cerrada.js` | El punto 5 tal como lo reportó el cliente: *"no muestra un mensaje"*. Va por navegador porque lo único que prueba el arreglo es **ver** el mensaje. Comprueba el aviso preventivo (*"puedes ampliar por transferencia"*), el modal `Caja cerrada` con su CTA, y de paso el piso de tres letras del buscador de clientes. Necesita una empresa con la caja cerrada (`ZZ QA-B`). | 9 OK · 0 MAL |
| `verificar_regresion_caja.py` | Regresión de los flujos que toca `_resolve_active_register`, contra el backend **desplegado** y con login real del laboratorio. Comprueba los 4 endpoints que cambiaron, que `AccountOut` **no** expone `register_id` (el contrato de la API no cambió) y que contratos/ventas/inventario siguen intactos — esos resuelven la sesión por otro camino (`integration.get_open_session`). | Todo en verde tras `00052` |
| `verificar_cadenas.py` | **Vigila las invariantes de las cadenas de contratos** (el recargo, `00051`) **sobre los datos vivos**: (1) todo contrato con sucesor está en `superseded` —la columna es `parent_contract_id`, no `root_contract_id`, que es la raíz de la cadena—, (2) ningún `contract_item` en `transferred` cuelga de un contrato que no lo esté, y (3) ningún contrato **terminal** conserva `extension_ends_at`. Los estados terminales salen de `rules.TERMINAL_STATUSES`, **no de una lista escrita a mano** — escribirla a mano es exactamente el error de F21-10. Va por SQL directo (`DATABASE_URL`) en una transacción **`SET TRANSACTION READ ONLY`**, y no imprime ningún dato personal: solo id, número, empresa y estado. Sale con código **1** si algo está roto, así que sirve en un cron. `QA_DATABASE_URL` apunta a otra base (la local de tests) para ejercer la detección. | **F21-10** — los 4 contratos que el job nocturno resucitó (Empresa Demo Front Nº 1 y Nº 20, LA GRAN LEGAL Nº 28, ZZ QA Nº 9), y la prórroga viva del Nº 1. Reparados el 21/09/2026; el script sale en verde desde entonces |
| `verificar_job_nocturno.py` | **Vigila la Machine programada del job nocturno en Fly**, que es infraestructura viva y ningún test puede ver: (1) que `nightly-job` **exista**, (2) que conserve su **`schedule`** —si se pierde, el job deja de correr y **su ausencia es silenciosa**: no hay health check ni alerta—, y (3) que su **imagen coincida con el release actual de la app**, que es exactamente lo que F21-10 rompió y lo que nadie estaba mirando. Solo lectura (`flyctl ... --json`). Sale con **1** si algo está roto y con **2** si no pudo verificar (sin `flyctl`, sin auth, timeout): *"no se pudo verificar" no es lo mismo que "está sano"*, y confundirlos sería repetir el error que el script existe para evitar. `FLY_APP` y `FLY_NIGHTLY_MACHINE` permiten apuntarlo a otra app o ejercer la detección. **Imprime un aviso** de que la Machine no tiene process group: es deliberado (ponerle uno puede hacer que `fly deploy` la borre o la recree sin `schedule`), y por eso se vigila en vez de arreglarse. | **Las dos causas de dos incidentes:** el borrado del 27/08/2026 por "máquina huérfana" (ninguna suscripción llegaba a `expired`) y **F21-10**, la imagen del 08/09 sin la guarda de `compute_status`. Detección de las tres rutas ejercida el 21/09/2026 (machine inexistente → exit 1; sin `schedule` → exit 1; comparación de imágenes verificada aparte). Hoy sale en verde |

**Playwright — la app en vivo, con login real**

Resuelven Playwright desde el caché de npx (no es dependencia del proyecto, ver `ESTADO.md` → "Trampas del entorno"); se puede apuntar a otra copia con `QA_PLAYWRIGHT`.

> **El navegador puede no estar, aunque Playwright sí.** El 11/09/2026 `~/Library/Caches/ms-playwright` tenía solo `ffmpeg`: el Chromium se había ido, y `launch()` falla pidiendo `npx playwright install`. `ui_ltv.js` cae solo al **Chrome del sistema** (`channel: 'chrome'`), que no requiere descargar nada; los demás scripts todavía no. Si uno falla con *"Executable doesn't exist"*, es esto — no hace falta reinstalar nada si hay Chrome.

| Script | Qué hace | Qué encontró |
|---|---|---|
| `ui_test.js` | Login por rol y comprobación de que el menú se filtra y las rutas redirigen. | Guards de UI correctos en los 4 roles |
| `ui_a11y.js` | Contraste WCAG de todo texto visible (`getComputedStyle`) y desbordes horizontales a 360 px. | **H-03** |
| `ui_sweep.js` | El mismo barrido de contraste sobre 12 pantallas × 2 temas. | **F6-02** — 12 combinaciones bajo AA en claro, 0 en oscuro |
| `ui_responsive.js` | 12 pantallas × 3 anchos (360 / 768 / 1280), separando el desborde del **documento** del contenido que scrollea dentro de su propio contenedor. | **F6-03** — y desmintió el primer intento de arreglarlo |
| `ui_forms.js` | Envía incompletos los cuatro formularios largos y mide **dónde queda** el primer error respecto de la ventana. | **F6-01** |
| `ui_alta.js` | El alta de usuario completa en navegador: enlace → los cuatro crawlers → crear contraseña → entrar. | Confirma que el fix del `token_hash` (03/09) aguanta |
| `ui_rec.js` | Recuperación de contraseña, recibiendo el enlace por argumento. | El enlace consumido tiene pantalla propia |
| `ui_perfil.js` | Cambio de la propia contraseña: exige la actual, y la vieja deja de servir. | Correcto |
| `ui_plataforma.js` | El panel de super-admin por UI (se había probado solo por API). | Empresas sin plan y vencidas se ven igual (cola de H-14) |
| `ui_print.js` | Impresión de paz y salvo y comprobante de venta, interceptando `window.print`. | Correctas |
| `ui_acta.js` | El acta de cierre de caja, que exige una sesión ya cerrada. | Completa, con desglose y justificación |
| `ui_ltv.js` | El aviso de cupo del LTV en el formulario de contrato. Elige categoría, escribe monto y avalúo, y comprueba las DOS ramas del texto según `contracts.override_ltv`. Cae al Chrome del sistema si el Chromium de Playwright no está descargado. | **El cupo calculado 100× por encima** — los tests no lo vieron porque usaban el texto enmascarado |
| `ui_recargo.js` | La pantalla de ampliar préstamo sobre la cadena real (viejo → sucesor), incluido el desborde a 360 px. Existe porque **buscar los textos en el JS servido prueba que se desplegó, no que se ve**: el panel está detrás de un permiso, de un cupo y de un motivo de bloqueo. | Correcta |

## Correr

```bash
python scripts/qa/map_endpoints.py     # primero: genera el mapa
python scripts/qa/matrix.py            # ~5 min, 400+ requests contra dev
python scripts/qa/analyze_matrix.py
python scripts/qa/concurrencia.py
python scripts/qa/verificar_sedes.py     # invariante de datos vivos; exit 1 si falla
python scripts/qa/verificar_cadenas.py   # invariante de datos vivos; exit 1 si falla
python scripts/qa/verificar_job_nocturno.py  # la Machine del job en Fly; exit 1 si falla, 2 si no pudo verificar

### Los dos guardianes en automático

`verificar_job_nocturno.py` ya corre solo: **`.github/workflows/guardianes.yml`**, todos los días a las
13:00 UTC (8 a.m. en Bogotá, o sea *después* de la corrida del job, así que un problema se sabe al empezar
el día y no al terminarlo). Necesita **un solo secret**, `FLY_API_TOKEN`, y hasta que exista **falla a
propósito** con un mensaje que dice qué agregar — saltearse en silencio por falta de configuración sería el
mismo modo de falla que vino a evitar. Si no se va a configurar ya, **comentar el `schedule`** en vez de
dejarlo fallando cada noche: acá ya está aprendido que *una CI que siempre falla no dice nada*.

**Tiene que correr desde AFUERA de Fly**, y eso no es un detalle de implementación: si la Machine se borra
o pierde su `schedule`, un vigilante que viviera dentro de Fly sería justamente lo que no corre.

🔴 **`verificar_cadenas.py` todavía NO corre solo, y se decidió NO ponerlo en GitHub Actions.** Necesitaría
`DATABASE_URL` de la dev remota como secret de un tercero, y esa base tiene **datos personales reales de
clientes** (cédulas y fotos de documento, Ley 1581): exportar esa credencial para leer tres invariantes
amplía el radio de exposición mucho más de lo que aporta. Su lugar es **dentro del perímetro que ya tiene
acceso a la base**. Dos opciones, ninguna implementada:

1. **Dentro del job nocturno** (`app/jobs/nightly.py`), que ya corre a diario con la base a mano. Es la más
   barata. Contra: si el job es el que está roto —que es el caso que originó todo esto—, el guardián no
   corre. Mitigado en parte porque `verificar_job_nocturno.py` vigila al job desde afuera.
2. **Una Machine programada aparte** en Fly, con su propio `schedule`. Independiente del job, pero agrega
   una segunda Machine sin process group — o sea el mismo problema que ya costó dos incidentes.

La opción 1 con el guardián de Fly encima cubre más por menos. Mientras no esté, **el script se corre a
mano** y su resultado vale solo para el momento en que se corrió.

node scripts/qa/ui_test.js             # gates de menú y ruta, por rol
node scripts/qa/ui_sweep.js            # contraste, 12 pantallas × 2 temas
node scripts/qa/ui_responsive.js       # 12 pantallas × 3 anchos
```

`matrix.py` **no crea ni modifica nada**: aprovecha que `require_permission` es un `Depends` y se evalúa antes del body, así que un request con cuerpo vacío y un UUID inexistente devuelve `403` si falta el permiso y `422`/`404` si lo tiene.

## Trampas que costaron tiempo

- **Varios routers declaran más de un `APIRouter` en el mismo archivo** (`identity` + `credit-notes`). Tomar el último `prefix` asignado produce rutas que no existen, y entonces el barrido «pasa» probando 404s. Por eso los paths salen del OpenAPI y no del AST.
- **`/reports/closings` y `/closings-breakdown` exigen DOS permisos** vía un helper (`_closings`), no un `Depends` directo — el mapa los corrige a mano.
- **Un desborde a 360 px no es lo mismo que contenido más ancho que la ventana.** Una tabla dentro de un contenedor con `overflow-x: auto` es el patrón *correcto*; lo que hay que medir es `documentElement.scrollWidth`. `ui_responsive.js` separa las dos cosas — sin eso, los falsos positivos de `/reportes` e `/inventario` esconden los reales.
- **Volver a medir después de desplegar el arreglo, siempre.** El primer fix de F6-03 fue al componente compartido y `/caja` siguió saliéndose los mismos 59 px: los botones no estaban ahí. Sin la segunda medición se habría reportado como arreglado sin estarlo.
- Los artefactos de cada corrida van a `_run/`, ignorado: son de un laboratorio concreto e incluyen tokens de sesión. **No versionarlos** — y tampoco las capturas ni los PDFs de una corrida (también ignorados): lo que prueban se transcribe al registro.
