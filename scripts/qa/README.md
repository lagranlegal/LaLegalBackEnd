# Arsenal de QA

Los scripts que produjeron la auditoría de [`docs/QA_AUDITORIA.md`](../../docs/QA_AUDITORIA.md). **No son tests de pytest** y por eso viven acá y no en `tests/`: pegan contra el backend **desplegado en dev** con usuarios reales, así que recogerlos en la suite haría que `pytest -q` saliera a la red y modificara datos.

## Por qué existen

La matriz de permisos completa son 105 endpoints × cada rol. Hacerla por pantalla serían días; por API son cinco minutos y no deja nada sin cubrir. Lo mismo con el resto: comprobar 36 permisos contra 13 módulos a mano es donde se cuelan los huecos.

## Preparar

```bash
cd backend-starter
pip install httpx                        # ya está en el entorno del proyecto
export QA_PASSWORD='...'                 # opcional; default: la del laboratorio
```

Las credenciales salen solas de los `.env` de los dos repos (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL`). **Nada de esto se hardcodea acá.**

El laboratorio (empresas espejo, usuarios por rol, datos sembrados) está descrito en `docs/QA_AUDITORIA.md` §"El laboratorio". Con el `SUPABASE_SERVICE_ROLE_KEY` se pueden crear usuarios y fijarles contraseña sin gastar cuota de correo, así que no hace falta la cuenta de nadie.

## Qué hay

| Script | Qué hace |
|---|---|
| `qa.py` | El arsenal. Login contra Supabase Auth, cliente HTTP por actor, y `check()` para registrar comprobaciones. **Todo error se asevera por `code`, nunca por status solo** — un test que mira el status y no el código no cubre nada. |
| `map_endpoints.py` | Mapa canónico ruta → permiso. Los paths salen de `/openapi.json` (la verdad) y el permiso del AST de los `router.py`. Detecta el «bug de revisión» de `CLAUDE.md`: un endpoint sin `Depends(require_permission(...))`. |
| `matrix.py` | La matriz completa: cada endpoint × cada rol, con el permiso y sin él. |
| `analyze_matrix.py` | Lee el resultado y saca las discrepancias agrupadas por endpoint. |
| `ui_test.js` | Playwright: login real por rol y comprobación de que el menú se filtra y las rutas redirigen. |
| `ui_a11y.js` | Contraste WCAG de todo texto visible (`getComputedStyle`) y desbordes horizontales a 360 px. |

Los `.js` resuelven Playwright desde el caché de npx (no es dependencia del proyecto, ver `ESTADO.md` → "Trampas del entorno"); se puede apuntar a otra copia con `QA_PLAYWRIGHT`.

## Correr

```bash
python scripts/qa/map_endpoints.py     # primero: genera el mapa
python scripts/qa/matrix.py            # ~5 min, 400+ requests contra dev
python scripts/qa/analyze_matrix.py

node scripts/qa/ui_test.js             # gates de menú y ruta, por rol
node scripts/qa/ui_a11y.js             # contraste y responsive
```

`matrix.py` **no crea ni modifica nada**: aprovecha que `require_permission` es un `Depends` y se evalúa antes del body, así que un request con cuerpo vacío y un UUID inexistente devuelve `403` si falta el permiso y `422`/`404` si lo tiene.

## Trampas que costaron tiempo

- **Varios routers declaran más de un `APIRouter` en el mismo archivo** (`identity` + `credit-notes`). Tomar el último `prefix` asignado produce rutas que no existen, y entonces el barrido «pasa» probando 404s. Por eso los paths salen del OpenAPI y no del AST.
- **`/reports/closings` y `/closings-breakdown` exigen DOS permisos** vía un helper (`_closings`), no un `Depends` directo — el mapa los corrige a mano.
- Los artefactos de cada corrida van a `_run/`, que está ignorado: son de un laboratorio concreto e incluyen tokens de sesión. **No versionarlos.**
