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

**Playwright — la app en vivo, con login real**

Resuelven Playwright desde el caché de npx (no es dependencia del proyecto, ver `ESTADO.md` → "Trampas del entorno"); se puede apuntar a otra copia con `QA_PLAYWRIGHT`.

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

## Correr

```bash
python scripts/qa/map_endpoints.py     # primero: genera el mapa
python scripts/qa/matrix.py            # ~5 min, 400+ requests contra dev
python scripts/qa/analyze_matrix.py
python scripts/qa/concurrencia.py

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
