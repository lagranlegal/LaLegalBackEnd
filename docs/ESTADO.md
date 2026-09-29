# Estado del proyecto — 25/09/2026

> **Dónde está todo, en una pantalla.** Lo de abajo de esta caja es el historial de avisos por fecha; el
> detalle de cada sesión vive en `CONTINUAR.md`.
>
> **Dev está al día:** backend y front desplegados el 25/09 por la noche, los dos guardianes en verde
> (`verificar_job_nocturno.py`, `verificar_cadenas.py`). Suites: backend **796 passed, 0 skipped**, front **344**.
>
> **Notificaciones por correo — las 7 fases construidas y desplegadas** (plan en `backend-starter/docs/NOTIFICACIONES.md` §11):
>
> | # | Fase | Estado |
> |---|---|---|
> | 1 | Resumen diario/semanal a la empresa | ✅ Apagado en las 7 empresas hasta que cada una lo encienda |
> | 2 | Invitación de usuario por nuestro correo (Resend) | ✅ Probado con correo real |
> | 3 | Base legal del cliente, baja por enlace, validar correo | ✅ |
> | 4 + 6 | Comprobantes al cliente (contrato, abono, paz y salvo, ampliación, nota crédito, venta, anulación) | ✅ Probado con correo real (venta en ZZ QA) |
> | 5 | Recordatorios R1–R4 (cuota, mora, prórroga) con límites de la Ley 2300 | ✅ Cuota **solo 3 días antes**; frenado por el tope → **se reprograma** (26/09) |
> | 7 | Alertas inmediatas A1–A4 a la empresa | ✅ Probado con correo real (26/09) |
> | 8 | WhatsApp | Fuera de alcance |
>
> Más: plantillas de correo con el estilo de `frontend-starter/docs/correo-invitacion.html`; **cláusula de
> autorización de avisos** insertable en el editor de contratos (y en el formato de fábrica); decisión legal
> de Mateo escrita en `NOTIFICACIONES.md` §12.3 (orientación, no concepto de abogado).
>
> **Cómo se enciende:** por empresa, en Configuración → Notificaciones (interruptor general + casilla por aviso).
> Hoy **ninguna empresa manda correos**; lo único que sale siempre es la invitación de usuario.
>
> **Lo que espera a Mateo (no es código):**
> 1. ~~Activar la cuenta de prueba~~ ✅ hecho; **alertas probadas con correo real el 26/09**.
> 2. Encender avisos por empresa; en LA GRAN LEGAL, después de agregar la cláusula a su plantilla de contrato
>    (hoy le aparece «pendiente») y, idealmente, de una revisión legal del texto.
> 3. Pedir el correo del cliente en el mostrador: hoy lo tienen **2 de 16**.
> 4. Decirle a LA GRAN LEGAL lo del cajón en −$1.108.000 (abrieron sin registrar el efectivo inicial).
> 5. ~~Verificar el paso de recordatorios~~ ✅ corrió el 26/09 (registró sin enviar, todo apagado). Queda medir si cada
>    deploy retrasa el job diario (`CONTINUAR.md`, punto 1).
> 6. ~~Deploy de R1 «solo 3 días antes»~~ ✅ desplegado el 26/09.
> 7. ~~Decidir el aviso de mora frenado~~ → se **reprograma**: hecho y pusheado (`44408b1`, 796 tests).
> 8. ~~Migración 00060 y deploy~~ ✅ hecho el 26/09 (guardianes en verde). **Todo dev al día.**
>
> **F21-33 medido (25/09):** daño histórico **cero** en dev (0 ventas con descuento). Cerrado del todo.
>
> **Operativo:** los deploys del backend los corre Mateo (`./scripts/deploy_dev.sh`): el clasificador de
> permisos me bloquea deploy, `secrets set` y `machine update`. El front sale solo al pushear (Vercel).

---

## Historial de avisos (más nuevo arriba)

> ### 26/09 — la landing pública de venta en `/`: ✅ PUBLICADA
>
> `/` es ahora la página de venta de Prendo (pública) y el **panel se mudó a `/inicio`**. Front `2b5df96` →
> `b7c579a`, pusheado a `dev`; 357 tests. Diseño en el lienzo <https://claude.ai/artifact/MbHqXJJBoKf1zjVjqqmaX5>
> (no hay conector de Figma). Decisiones de Mateo aplicadas: la demostración se pide por **correo a
> `contacto@prendo.com.co`** y **Inter arreglado** (la app nunca la había cargado: `'Inter'` vs `'Inter Variable'`).
> 🔴 **Espera a Mateo: crear o redirigir el buzón `contacto@prendo.com.co`** — el dominio hoy solo envía; sin
> buzón, las solicitudes rebotan sin que nadie se entere. Corrección de cifras: son **43 permisos** y **60
> migraciones**, no 41 y 57 como dice la tabla de abajo. Detalle en `CONTINUAR.md`.

> ### 25/09, noche — impresión + contratos (F21-38) + mejoras chicas: ✅ DESPLEGADO todo, guardianes en verde
>
> Backend 781 tests, front 344. Detalle en `CONTINUAR.md`.

> ### 25/09, noche — Fase 5 (recordatorios) ✅ desplegada: las fases 1–7 de notificaciones están construidas y en dev · cláusula de avisos ✅ desplegada · Fase 7 ✅ desplegada
>
> Backend 760 tests, front 312. Detalle en `CONTINUAR.md`.
>
> Backend 730 tests, front 289. Detalle en `CONTINUAR.md`.

> ### 25/09, tarde — plantillas nuevas + fases 4 y 6 pusheadas, SIN DESPLEGAR. F21-36 y F21-37 cerrados y DESPLEGADOS (backend + front `2282103` servido), guardianes en verde
>
> Detalle en `CONTINUAR.md`. Backend 656 tests.

> ### 25/09 — Fase 3 + F21-34/35: ✅ DESPLEGADO todo (backend, front, 00059), guardianes en verde. Falta la invitación real de prueba
>
> Orden pendiente (Mateo): secret `NOTIFICATIONS_LINK_SECRET` → `./scripts/deploy_dev.sh` → push del front →
> invitación de prueba en `ZZ`. Backend 585 tests, front 275. Detalle y comandos en `CONTINUAR.md`.

> ### 24/09, noche — Fase 2: la invitación sale por nuestro correo (pusheado, SIN desplegar el backend)
>
> Se acaba el `INVITE_RATE_LIMITED`: la invitación sale por Resend con un enlace que se canjea por POST y tras
> un clic. Backend `fbf7b8a`/`3c45142` (545 tests), front `cf1285a` (255). **Falta que Mateo corra
> `./scripts/deploy_dev.sh`** y una invitación real de prueba en una empresa `ZZ`. Detalle en `CONTINUAR.md`.

> ### 24/09, noche — pantalla de Notificaciones en el front
>
> `/configuracion/notificaciones` (front `5146ee1`, pusheado): interruptor general, eventos, umbrales,
> límites de la Ley 2300 e historial de entregas. Encender los correos de una empresa ya es una casilla, no
> un `PATCH` a mano. Front 251 tests. **Sigue:** alertas A1–A4. Detalle en `CONTINUAR.md` punto 3.

> ### 24/09 — todo pusheado y desplegado
>
> F21-32 **verificado en comportamiento** sobre lo servido. Cerrados F21-14, F21-17, la columna vacía de
> «Nota crédito redimida» y **F21-33** (nuevo, de plata: una devolución sobre una venta con descuento le
> pagaba al cliente el precio de lista; ahora se devuelve lo pagado). Backend 452 tests, front 238.
> **Pendiente:** medir las devoluciones históricas pagadas de más (consulta de solo lectura, la corre o
> autoriza Mateo), y las preguntas 2 y 4 de `NOTIFICACIONES.md` §12.1 para arrancar la Fase 5b.
> Detalle en `CONTINUAR.md`.

> ### ✅ El fix de plata (F21-32) está DESPLEGADO — 23/09, tarde
>
> `backend-starter`, commit **`a0f55c8`**: reabrir una caja y volver a cerrarla descuadraba el cajón. Medido
> antes del fix: un acta de −20.000 sobre un cajón desviado **+$2.700.100**, sin un solo movimiento de por
> medio. Desplegado en Fly, **los dos guardianes en verde**, y la Machine del job nocturno actualizada a
> mano —el guardián la cazó desactualizada otra vez, que ya es la quinta— con el `schedule` verificado
> después.
>
> ⚠️ **Lo que NO se verificó:** el **comportamiento** del fix sobre lo servido. Probarlo exige abrir, cerrar
> y reabrir una caja, y en dev hay datos reales bajo Ley 1581. Se verificó que el deploy llegó (imagen
> nueva, `title: Prendo API`, 96 rutas), no que la app servida ya no descuadre. *El deploy no es la prueba.*
>
> ⚠️ **El front tiene un commit SIN PUSHEAR** (`938a3aa`): el clasificador bloqueó el `git push`. Son los
> nueve defectos de UI — ninguno de plata, pero hasta que no se pushee, Vercel no los tiene.
>
> **Y algo que espera a Mateo, que no es código:** el cajón de **LA GRAN LEGAL reporta −$1.108.000**. Un
> cajón no puede estar en negativo. No es un bug — su `opening_balance` es **0** y se desembolsaron
> $1.600.000 en cuatro préstamos: **nunca registraron el efectivo con el que abrieron**. Se arregla
> contándolo, no tocando la base.

> **¿Retomando después de una pausa? Lee primero [`CONTINUAR.md`](CONTINUAR.md)** — es el traspaso de la última sesión: qué se hizo, qué trampas evitar y qué sigue con sus preguntas abiertas. Este archivo es el estado permanente; aquel es el de la sesión.
>
> **Empieza por acá.** Este archivo dice dónde está el proyecto hoy y qué falta.
> El *cómo* y el *por qué* de cada decisión vive en los `docs/` de cada repo — abajo está el mapa de qué leer según lo que vayas a tocar.
>
> Ojo: la raíz `compraventa_app/` **no** es un repositorio git; los repos son las dos carpetas de adentro. Este archivo no está versionado.
>
> **Contexto general del proyecto (producto, piezas, cómo se hablan, mapa de docs): [`README.md`](README.md).** Problemas de alta de usuarios: [`RUNBOOK_USUARIOS.md`](RUNBOOK_USUARIOS.md).

## Qué es

SaaS multi-tenant para **compraventas colombianas** (casas de empeño + tienda), que se vende por suscripción. Dos dominios con contabilidad separada —contratos de empeño e inventario/tienda— unidos por una caja diaria única.

| | |
|---|---|
| Backend | `backend-starter/` → FastAPI + SQLAlchemy async + Supabase. Fly.io. **URL: https://api-dev.prendo.com.co** (la app de Fly se sigue llamando `compraventa-backend-dev`; su `.fly.dev` sigue vivo pero el front ya no lo alcanza) |
| Frontend | `frontend-starter/` → Vite + React 19 + TanStack. Vercel, rama `dev`. **URL: https://prendo.com.co** → `dev.prendo.com.co` (la URL vieja de Vercel sigue funcionando) |
| Base de datos | Supabase **`driyubkodnsqxbtxcmaz`** (*lagranlegal's Dev*) |
| Estado | **57 migraciones** (todas aplicadas en dev) · **41 permisos** · **96 rutas / 122 operaciones** en el `/openapi.json` servido · 13 módulos backend · 15 features front |
| Tests | backend **447** (con Docker arriba y **sin skips**) · front **225** · `ruff`, `format` y `mypy` limpios |
| | ⚠️ **Sin Docker, `pytest` pasa igual con casi todo SALTADO.** Un «95 passed» no es la suite. |

> **La URL del front es fija desde el 23/08/2026.** Hasta entonces Vercel tenía `main` como rama de producción y las variables de entorno solo en Preview, así que **cada push generaba una dirección aleatoria nueva** y `la-legal-front-end.vercel.app` servía un build congelado de tres días atrás. Se veía como "la función no está desplegada" cuando en realidad estaba en otra URL. Ya está: rama de producción `dev`, variables en Production, y cada push actualiza esa misma dirección.

Ambos repos están **limpios y pusheados** en la rama `dev`.

## Lo que bloquea entregarle esto a un cliente

Ninguno es de código. **Ojo: una versión anterior de este documento decía que el dominio propio desbloqueaba tres cosas a la vez. Es falso y mandaba a resolver el problema equivocado** — se verificó el 22/08/2026 y quedó así:

### 1. ~~El candado de Vercel~~ — RESUELTO (23/08/2026)

**Deployment Protection está apagado.** Verificado de dos formas el 23/08: la API del proyecto devuelve `ssoProtection: null` y `passwordProtection: null`, y una petición anónima (sin cookies ni sesión de Vercel) a `la-legal-front-end.vercel.app` devuelve la app real, no el login de Vercel.

Queda anotado porque este documento afirmaba lo contrario y mandaba a resolver un problema que ya no existía.

### 2. El ambiente de producción — el único bloqueante, y Mateo lo dejó DE ÚLTIMO (23/09/2026)
> **Decisión de Mateo (23/09/2026): va de último.** Sigue siendo el único bloqueante real para venderle
> esto a un cliente, pero **no es urgente hasta que haya un cliente**. Antes van las notificaciones de
> negocio y los defectos abiertos.
>
> **Tres cosas ya decididas para cuando llegue, y hay que respetar el orden:**
> 1. La app de Fly se crea como **`prendo-api-prod`** — `fly.prod.toml` todavía dice
>    `compraventa-backend-prod` y hay que cambiarlo **antes** del `fly apps create`, porque **Fly no permite
>    renombrar** una app.
> 2. Las variables de prod van en Vercel **antes** de mover la Production Branch a `main`. En ese instante
>    los dominios **se mudan solos de build, sin avisar**.
> 3. El apex **deja de redirigir** y pasa a servir prod. **Nada de dev se mueve** — por eso se reservó.
>
> Y ojo: hoy **todo corre en dev**, con los datos de prueba mezclados con los reales de LA GRAN LEGAL en la
> misma base.


No hay proyecto Supabase de prod ni app de Fly `compraventa-backend-prod`. Los pasos están en `frontend-starter/docs/DEPLOY.md` y **funcionan sobre `.fly.dev` y la URL de producción de Vercel**. El dominio solo cambia cómo se ve la dirección final; no habilita nada.

### 3. El correo — ✅ RESUELTO (23/09/2026)

**Resend está verificado sobre `prendo.com.co` y conectado a Supabase Auth.** Los correos de autenticación
—invitación y recuperación— salen del dominio propio, con plantillas propias, y el enlace **sobrevive a los
crawlers de vista previa** (se canjea por POST con `token_hash`, no por el GET de un solo uso de GoTrue).
Se acabó el techo de "unos pocos envíos por hora" del SMTP compartido: **3.000/mes**.

**Lo que ya no depende del correo, y sigue igual de cierto:** el producto se diseñó para no necesitarlo. Los
cuatro caminos de alta y rescate funcionan con **"Generar enlace"** pasado por WhatsApp. El único camino que
sí lo exige es "¿Olvidaste tu contraseña?" del login — y ahora funciona bien.

**Falta, y no bloquea nada:** publicar el **DMARC** (`p=none` primero, y ojo que un Gmail cualquiera **no
recibe reportes DMARC**: hace falta un agregador) y la **prueba de spam** en Gmail, Outlook y un corporativo.

🔴 **Y lo que NO está hecho, que es otra cosa:** las **notificaciones de negocio**. Crear un contrato, una
venta o un abono **no le avisa a nadie**. El backend **no tiene módulo de correo** — cero código, cero
tablas, cero cola. El diseño completo está en `backend-starter/docs/NOTIFICACIONES.md` y empieza con siete
preguntas de negocio sin contestar. **Restricción medida que manda sobre ese diseño: de 16 clientes, 2
tienen correo** — en una compraventa colombiana el cliente da el celular. La empresa, en cambio, siempre
tiene correo, así que los avisos al negocio se pueden construir sin depender de nada.

### 4. Lo que el dominio sí resuelve, y nada más — ✅ RESUELTO (21/09/2026)

**La cara del producto.** Un cliente vería una URL de preview de Vercel. Para un piloto que sabe que es piloto se aguanta; para vender, no.

**El mapa de nombres quedó decidido y ejecutado el 21/09: un hostname por ambiente.**

| Hostname | Hoy | Cuando exista prod |
|---|---|---|
| `dev.prendo.com.co` | el front de dev | **dev, intacto — no se mueve** |
| `api-dev.prendo.com.co` | el backend de dev (Fly) | **dev, intacto — no se mueve** |
| `prendo.com.co` (apex) | redirect 308 → `dev.prendo.com.co` | **prod** (deja de redirigir) |
| `www.prendo.com.co` | redirect 308 → `dev.prendo.com.co` | redirect → apex |

**Por qué el apex no se usa para dev** (y por qué esto reemplaza la propuesta `app.`/`api.` de
`PLAN_MARCA.md`): la URL de la app queda **embebida** en las Redirect URLs de Supabase, en los enlaces de
invitación y recuperación ya enviados, en CORS, en el CSP y en los marcadores del cliente. Un hostname que
cambia de ambiente hace que todo eso caiga, el día del corte, **en otra base con datos reales de clientes**,
y **sin ningún error**: la app abre y son otros datos. Con este mapa, el día del corte a prod **no se mueve
nada de dev**.

**Hecho y verificado en navegador real** (Chrome vía Playwright), que es lo que `curl` no puede probar:
los cuatro hostnames con DNS propagado y certificado emitido; los redirects 308 del apex y `www` (vía la API
de Vercel, porque **su CLI no soporta redirects**); `FRONTEND_URL=https://dev.prendo.com.co` y
`CORS_ALLOW_ORIGINS` en los secrets de Fly, leídos del proceso en vivo; la Redirect URL en Supabase Auth.
Carga inicial con **0 mensajes de consola**; `GET /api/v1/me` con `Authorization` inventado devuelve **401**
legible con `type: "cors"`, o sea que el **preflight `OPTIONS` pasó**; el tema persiste entre recargas —el
hash SHA-256 del script anti-parpadeo sigue coincidiendo bajo el origen nuevo, y su fallo **no dejaría error
de JS**—; y un `fetch` al host viejo queda **bloqueado por CSP en modo `enforce`**.

**El backend también salió del nombre viejo**, pero sin renombrar nada: **Fly no tiene comando de rename**
(solo `create`, `destroy`, `move`). Se le puso el dominio `api-dev.prendo.com.co`; la app sigue llamándose
`compraventa-backend-dev` internamente, cosa que no ve nadie fuera de `flyctl`. 🔴 **Cuando se cree
producción, la app se llama `prendo-api-prod`** — `fly.prod.toml` todavía dice `compraventa-backend-prod` y
hay que cambiarlo **antes** del `fly apps create`, porque después no se puede.

**Ya nada visible dice "compraventa"** salvo dos usos de la palabra común en español (el `meta description`
y el hint de "Nota de encabezado"), que se dejan a propósito: son el tipo de negocio, no el nombre viejo.

⚠️ **Único pendiente, menor:** el HSTS de `dev.prendo.com.co` va **sin `includeSubDomains; preload`**,
mientras la URL vieja de Vercel sí los tiene. Se endurece en `frontend-starter/vercel.json`, y conviene
hacerlo **antes** de que haya datos reales de clientes ahí.

Detalle, comandos y verificación: **`frontend-starter/docs/PLAN_MARCA.md` §Fase 4** y
`frontend-starter/docs/DEPLOY.md`; el registro histórico, en `docs/IMPLEMENTATION.md`.

### 5. Sin PDFs

**PDFs** (contrato firmado, acta de cierre de caja): fuera de alcance por decisión explícita. El front los imprime con CSS mientras tanto, que cubre la necesidad real.

## Trabajo de desarrollo pendiente

- **La serie de defectos abiertos F20-xx / F21-xx quedó casi vacía (23/09/2026).** Once cerrados en una
  tanda: los seis de códigos de error (F20-01..03, F21-02, 03, 06), tres de etiquetas y UX (F21-04, 07, 08)
  y F21-09. **Y salió uno nuevo que no estaba en ninguna lista y era de plata: F21-32** — reabrir una caja y
  volver a cerrarla descuadraba el cajón, porque `reopen_session` limpiaba el acta sin revertir el ajuste
  que el cierre había emitido. Cerrado con tres tests vistos fallar; **falta desplegar**.
  **Lo que queda abierto, y ninguno es de plata:** F21-13, 14, 15 y 17 (medidos, con la propuesta escrita y
  el número que la sostiene), F21-05 —que resultó ser una **feature** que falta, no un defecto— y el bug de
  paso de la columna «Nota crédito redimida» del Excel de Ventas, siempre vacía. **F21-18 se cerró como «no
  es defecto»**, y de F21-13 y F21-18 hay que saber que los arreglos que proponían eran **imposibles o
  dañinos** — el detalle está en `backend-starter/docs/QA_AUDITORIA.md`.

- **La marca existe, está en el código y DESPLEGADA (20/09/2026).** Commiteada y pusheada a `dev` en los dos repos; Vercel despliega solo. **El backend quedó desplegado el 21/09/2026** y verificado sobre lo servido (`title: Prendo API`). ✅ **Y en ese despliegue apareció F21-10, ya cerrado del todo (21/09):** la Machine del job nocturno no se actualiza con `fly deploy`, quedó en su imagen del 08/09, y desde el 10/09 estuvo recalculando contratos `superseded` —los reemplazados por una ampliación— como si siguieran vivos. **Se midió el daño y hubo: 4 contratos, el 100 % de las ampliaciones que existen** (no hubo ni una sana — la función y el bug nacieron el mismo día). Uno solo de un cliente real, el Nº 28 de LA GRAN LEGAL. **Reparados y verificados** (`scripts/qa/reparar_f21_10.sql`, con auditoría), incluida la bomba con fecha: el Nº 1 de Empresa Demo Front entraba solo a «Listos para remate» el 17/10. Cartera inflada 5.000.000 COP, contada doble, ya corregida. **El daño nunca llegó a plata** — ni un abono sobre los cuatro padres. **El hallazgo de diseño también se cerró**: la consulta del job y `rules.TERMINAL_STATUSES` son ahora la misma fuente, con un test que se vio fallar con la lista vieja *y* con una lista a mano hoy completa. **Y quedó guardián**: `scripts/qa/verificar_cadenas.py`, exit 1 si una cadena se rompe. ⚠️ **Dos cosas abiertas:** poner el guardián en un cron, y que la Machine `nightly-job` **sigue sin process group** — la misma característica por la que el 27/08 alguien la borró creyéndola huérfana. Ver `backend-starter/docs/QA_AUDITORIA.md` §F21-10.

- **La guía de usuario tiene las OCHO partes escritas (21/09/2026).** Escritas las partes 1 a 5, la 7 y la 8 de
  `marca/GUIA_USUARIO.html`, todas **verificadas contra el código** por tandas de QA aparte. Falta solo la
  parte 6 (cierre contable de fin de mes), que quedó en gran parte cubierta por la pantalla de Reportes.
  Publicada en la versión 5. ✅ **Compartida el 21/09** y en modo «los visitantes ven los cambios al instante»,
  así que republicar basta — a diferencia del kit, que quedó con la versión clavada y sí exige mover el pin.

- **El QA de la guía encontró nueve defectos del front (F21-01..09 en `QA_AUDITORIA.md`), y cuatro errores
  heredados en la propia guía.** Ninguno salió de leer código a secas: **salieron de escribir la guía y
  después verificar cada afirmación**. Documentar el producto resultó ser una forma de auditarlo — la guía
  obliga a decir qué pasa exactamente, y ahí se ve que el front y el backend no dicen lo mismo.
  Los cuatro heredados ya venían escritos desde el 12/09 y se habían propagado sin que nadie los midiera:
  «pieza única = una joya» (falso: solo el remate crea piezas únicas), «Al día + capital» (no existe como
  botón), el rol «Administrador» (se llama **Admin**) y «el buscador de la barra no funciona» (no está
  deshabilitado: **se quitó**).
  **Regla que queda:** lo que la guía afirme se verifica contra el código, no contra un informe intermedio
  ni contra lo que ya estaba escrito.

- **El kit de marca está republicado, pero el enlace del cliente NO se actualizó solo (20/09/2026).** Un artifact compartido sirve una versión **clavada**: republicar actualiza lo que ve el dueño, no lo que ve quien abre el link. Hay que **mover el pin a mano desde el menú Share**. `marca/README.md` afirmaba lo contrario y ya está corregido.

- **Detalle de la marca:** La plataforma se llama _Prendo_ (nombre 12/09). El 20/09 se aplicó al código con la paleta **Oro Moderno** que definió Mateo (`--brand-500: #c99a3d`) y un **logo nuevo**: la *etiqueta* — rombo con perforación, el objeto que la app imprime para cada lote —, que reemplaza al monograma **P** del 12/09 por no distinguir. Wordmark en **Archivo**; la interfaz sigue en Inter. **Dos cosas medidas que cambiaron el plan:** (1) blanco sobre el oro da **2.57:1**, peor que el teal 2.70 que se abandonó por eso mismo → el texto sobre el oro es **carbón** (6.24:1) y `#c99a3d` queda intacto; (2) el mismo oro como **texto** sobre fondo claro da 2.42:1, así que se separó `text-brand` (`--brand-700`) de `bg-primary` — eran la misma variable de Tailwind y ahí viven los enlaces y las cifras de dinero. A diferencia del rebranding anterior, este **no fueron 6 líneas**: la paleta de oro trae su propio mundo cálido y también cambiaron los neutrales y el sidebar. `tests/token-contrast.test.ts` ya mide el **relleno** del botón primario, en los dos temas, y se verificó que falla sin el fix. Detalle y valores: **`frontend-starter/docs/DESIGN_SYSTEM.md` §1-bis**. Plan de las fases que siguen (kit, guía, dominio, correo): **`frontend-starter/docs/PLAN_MARCA.md`**. El kit `marca/IDENTIDAD.html` **todavía muestra el esmeralda y la P** — rehacerlo es la fase 2.
  **De paso cierra `DECISIONES_PENDIENTES.md` §4 por una vía que esa sección no contemplaba:** daba por fijo el teal y preguntaba qué sacrificar, pero el teal nunca fue la marca — era el placeholder. Blanco sobre el relleno primario pasa de **2.70 a 5.31**; las 10 combinaciones, claro y oscuro, cumplen AA. **Al aplicarlo hay que extender `tests/token-contrast.test.ts` para que mida el RELLENO del botón**, no solo los tokens de texto: ese agujero es la razón de que el 2.70 viviera meses sin que nada fallara.
  **Y hay un recado con fecha para Mateo:** registrar `prendo.com.co` (**comprado el 20/09/2026 — es el dominio de la marca; `prendo.co` se descartó por presupuesto el 21/09**) y poner un backorder de `prendo.co`, que el 12/09 estaba en `pendingDelete` y caía **alrededor del 16/09**. Verificar siempre con `whois -h whois.registry.co` — el `whois` del sistema, para `.co`, cae a IANA y devuelve datos del TLD, no del dominio (parece "tomado" todo).
- **Guía de usuario para clientes — 7 de 8 partes (21/09/2026).** No existía ninguna documentación de usuario final, y el onboarding dependía de que Mateo explicara la app en persona. Fuente en **`marca/GUIA_USUARIO.html`**, publicada como centro de ayuda en <https://claude.ai/code/artifact/e10cdc49-4eea-49c6-8c2f-7e43b87ff742> (buscador interno, índice lateral, e imprime a PDF con su propio `@media print`). ✅ **Compartida el 21/09**, y en modo «los visitantes ven los cambios al instante»: republicar basta. (Ojo: **el kit sí quedó con la versión clavada** y ese sí exige mover el pin a mano desde el menú Share. Son dos modos distintos y el real se lee en la cabecera del artifact.) **Escritas:** las partes 1 (primeros pasos), 2 (cómo piensa la app), 3 (las 14 tareas del día a día), 4 (las 14 pantallas), 5 (roles y permisos), 7 (28 problemas frecuentes) y 8 (glosario y límites). **Falta solo la parte 6** (cierre contable de fin de mes), que quedó en gran parte cubierta por la pantalla de Reportes. **Todo verificado contra el código** por tandas de QA aparte — ver el bloque del 21/09 en `CONTINUAR.md`. Método para continuarla: `marca/README.md` y `frontend-starter/docs/GUIA_INSUMOS.md`.
  **Método que no se debe aflojar:** cada tabla de campos se escribió **leyendo el schema de Zod del formulario**, no de memoria — obligatorio/opcional sale del schema, no del label. Y las capturas, cuando se agreguen, van contra una **empresa espejo sembrada**: la dev remota tiene clientes reales con cédulas y fotos de documento (Ley 1581).
  **Y una corrección que vale como regla:** la sección de códigos del borrador salió MAL por escribirla desde `CONTEXTO.md` §3 en vez de desde `inventory/rules.py` — describía el esquema de **pieza única** (`JOC0001I`), superado cuando el modelo se partió en **producto + lote** (`JAO0007` + `JAO0007-01I`, cinco orígenes y cuatro letras reservadas). Mateo lo cazó al leerlo. Ya está corregida la guía y `CONTEXTO.md` lleva un aviso encima de ese párrafo. **`CONTEXTO.md` congela decisiones del 14/08 y el código evolucionó encima: para documentar una regla, la fuente es el módulo, no el documento de traspaso.**
- **Rediseño visual — tres pases hechos (28-30/08/2026), no cerrado del todo.** Mateo dio feedback directo tras días de uso: "se siente muy vacía (muy IA)", botones invisibles sobre el fondo, poca animación, el `#` de los documentos sin estilo, quería más contraste en el sidebar y un footer profesional. Causa raíz de casi todo: `--color-sidebar` y `--color-muted` apuntaban al mismo blanco/gris que el resto de la app — dos alias mal puestos en `tokens.css`. Arreglado 100% en tokens + shell (`AppShell`/`AppFooter`/`Button`), sin tocar features una por una — mismo mecanismo que ya sostiene el rebranding con 6 líneas. Segundo pase cerró los pendientes explícitos: `RecordNumber` (componente nuevo) en el resto de lugares de tráfico medio, `enter-up`/estados `active:` en `DataTable` y cards del dashboard, la card "Documento firmado" del detalle de contrato plegada en la grilla superior. **Tercer pase (30/08): el footer del primer intento —bloque oscuro de 3 columnas— se sintió invasivo en el uso real; se volvió una sola línea discreta**, mismo fondo que las cards. Detalle completo en `frontend-starter/docs/IMPLEMENTATION.md`. **Sigue sin ser un rediseño pantalla por pantalla.**
- **Fix (30/08): crear una plantilla de documento (o abrir una con campos/tabla/firma) tiraba "No se pudo cargar la app".** Reportado en vivo, dos rondas — la primera no era la causa real. Ronda 1: `TemplateRenderer` (vista previa) pasaba un objeto sin memoizar al array de dependencias de `useEditor` (Tiptap) — arreglado (`useMemo` en `DocumentTemplatesPage.tsx`), pero Mateo reportó que el error seguía. Ronda 2, con el stack trace completo (no solo `pageerror` — el error boundary de React se lo traga antes de llegar a `window.onerror`): la causa real estaba en `TemplateEditor.tsx`, comparaba `JSON.stringify(editor.getJSON())` contra `JSON.stringify(value)` — sensible al orden de las claves, así que con cualquier nodo atómico (campo/tabla/firma) casi siempre daba "distinto" y disparaba un `setContent` de más justo al montar, mientras los NodeViews de React de esos nodos todavía estaban montando — la reconstrucción los dejaba con el editor ya nulo. 100% reproducible (5/5), no una condición de carrera. Fix: comparar por referencia (`useRef` del último valor que el editor ya refleja) en vez de por texto. Verificado en vivo: el mismo repro que daba 5/5 pasó a 0/5, más un flujo más amplio (escribir, insertar campo, guardar, reabrir en pestaña nueva) sin ningún error de consola.
- **Los diez frentes de inventario, compras y caja** — revisión completa en `frontend-starter/docs/propuesta-diez-frentes.html`. **Las cuatro tandas están hechas y desplegadas** (21–22/08/2026): los tres bugs iniciales (el precio de venta que se perdía, las fotos del remate que no se heredaban, Sistecrédito ofrecido como fuente de pago); las migraciones 00031–00033 (permiso de histórico de caja, traslados entre cuentas para consignar el efectivo, tipos `initial_stock`/`adjustment_in` y el egreso `loss`); el rediseño del ingreso (precio y fotos en la compra, publicación automática, carrito multi-artículo) con los filtros que faltaban; y los reportes contables (cuentas por pagar con antigüedad, valorización del inventario, mercancía sin rotación, ficha de proveedor, compras por producto).
  Esa revisión ya está **cerrada por completo**: kardex por producto (23/08) y devolución de cliente + nota crédito (27/08) fueron los dos últimos puntos abiertos. Ya estaban hechos desde el 22/08: estado de resultados, extracto por cuenta y filtros en la URL.
- **Transformación de inventario** — hecha (`00037`): fundir, despiezar y armar en una sola operación, con el costo viajando y la merma subiendo el costo unitario sola. Pantalla en Inventario → **Transformar** (hacer una) y pestaña **Transformaciones** (consultarlas).
  Su trazabilidad se cerró en `00039` (23/08): el lote producido guarda `source_transformation_id` y su código lleva **`T`**, así que desde el oro se puede volver a la fundición y de ahí al contrato del cliente. `R`, `P` y `T` quedaron reservadas para que ningún proveedor pueda tomarlas.
- El backlog largo vive en `backend-starter/docs/PENDIENTES_BACKEND_INFRA.md` — **termina en §19**, no en §24 como decía este documento; los puntos abiertos están marcados sin "✅ Resuelto".

### Lo que sigue abierto, por valor

1. ~~**Kardex por producto.**~~ Hecho (23/08, `00040`). Botón **Kardex** en cada fila de producto: la historia completa con saldo de unidades y de costo corriendo. La anulación de venta se **sintetiza** — repone stock sin escribir ninguna fila.
2. ~~**Devolución de cliente.**~~ Hecho y desplegado (27/08, `00041`-`00045`). Efectivo o nota crédito (redimible en una venta futura), parcial, motivo estructurado, reingreso opcional — reabre el mismo lote si sigue intacto o crea uno nuevo con letra `D` si no. Bloquea devolver en efectivo una venta cobrada por Sistecrédito sin liquidar. Plazo configurable por empresa que **advierte, no bloquea**. Verificado en vivo contra dev con datos reales (los dos caminos de reapertura, con login real). Detalle: `frontend-starter/docs/IMPLEMENTATION.md`.
3. **Ambiente de producción** (proyecto Supabase prod + app Fly `compraventa-backend-prod`). No necesita dominio. Es el único bloqueante real para venderle esto a un cliente — ver la sección de arriba. **Dos cosas que hay que hacer en el orden correcto cuando llegue:** la Production Branch de Vercel pasa de `dev` a `main` —y en ese instante los dominios de Production **se mudan solos de build, sin avisar**, así que las variables de prod van *antes*—, y el apex deja de redirigir a `dev.prendo.com.co`, que se queda con dev. Ver `frontend-starter/docs/DEPLOY.md`.
4. ~~**Agregación de caja por rango de fechas.**~~ Backend hecho (27/08): `GET /reports/closings-breakdown?from_date&to_date`, módulo×concepto×medio×cuenta sumado sobre todas las sesiones cerradas del rango en una sola consulta. **Front conectado (28/08)** — `useClosingsBreakdown` reemplaza el N+1 de `useRawSessions`; `aggregateFinancialSummary` cambió de firma (líneas ya planas + lista de fechas de sesión aparte) pero no de reglas de negocio. Sigue quedando un N+1 más chico y ya acotado (`GET /cashbox/expenses` por sesión, para la dimensión de categoría de gasto que el endpoint nuevo no cubre). Verificado en vivo: cero llamadas al endpoint viejo, filtro de módulo sigue sin refetch, números correctos al filtrar. Detalle en `frontend-starter/docs/IMPLEMENTATION.md`.
5. ~~**Buscador de contratos (`?q=` en `GET /contracts`).**~~ Hecho y conectado (27/08) — número, `legacy_code` y nombre/documento del cliente. Ya no es un parche de 200 registros.
6. ~~**`GET /platform/companies/{id}/audit-log`.**~~ Hecho (27/08) — un super-admin ya ve la auditoría de SEGURIDAD de cualquier empresa, mismo molde que el resto de `platform` (bypass de RLS + `company_id` explícito en el WHERE). Verificado que NO filtra auditoría de otra empresa (el punto entero del fix).
6b. ~~**Plantillas de documentos editables (Contrato + Paz y salvo).**~~ Backend y frontend hechos, testeados, commiteados, pusheados y desplegados (27-28/08) — editor Tiptap enriquecido, `/configuracion/documentos`, botón "Imprimir paz y salvo". Detalle completo en `frontend-starter/docs/IMPLEMENTATION.md`. Una empresa que nunca active una plantilla sigue imprimiendo el mismo JSX de siempre, carácter por carácter (fallback de código, no una plantilla sembrada en la base de datos) — **con una excepción real encontrada el 28/08 (ver 6f): el borde bajo el encabezado sí cambió de aspecto para todos, se necesita una decisión de Mateo.**
6c. ~~**3 formatos visuales por plantilla (Clásico/Moderno/Compacto).**~~ Backend y frontend hechos y testeados (28/08, migración `00047`) — cada plantilla elige su identidad visual (tipografía, encabezado, densidad) independiente del texto. De paso se corrigió que `@tailwindcss/typography` nunca estuvo instalado pese a que el editor ya asumía sus clases — los encabezados/listas de Tiptap no tenían NINGÚN estilo hasta ahora. **Confirmación VISUAL hecha (28/08, más tarde en la sesión)** con Playwright real (sí está disponible en este entorno, vía caché de npx — ver Trampas abajo) contra la plantilla activa real de Mateo: los 3 formatos se ven claramente distintos en pantalla, sin guardar cambios sobre su plantilla real.
6d. ~~**Fix: insertar un campo dinámico borraba el anterior.**~~ Reportado en vivo por Mateo el mismo 28/08 al usar el editor. Causa: `mergeField` es un nodo atómico — insertarlo solo deja una `NodeSelection` sin cursor visible, y el siguiente insert la reemplazaba en vez de agregarse al lado. Fix: insertar un espacio de texto después de cada campo para que el cursor quede colapsado y parado después. De paso se agregó estilo visible para `.ProseMirror-selectednode` (no existía — por eso tampoco era claro cómo se borra un campo). Desplegado y **confirmado visualmente (28/08, más tarde en la sesión)**: dos campos insertados uno justo después del otro quedaron uno al lado del otro, sin reemplazo.
6e. ~~**Fix: no era claro que "Guardar" ≠ "Activar".**~~ Mateo creó una plantilla, la guardó, imprimió un contrato y seguía saliendo el formato viejo — no era un bug (confirmado consultando `document_template` directo en la base: existía con `is_active=false`, nunca se le dio clic a Activar), pero nada en pantalla lo avisaba. Se agregó un banner (`bg-warning-soft`) en `DocumentTemplatesPage` para ambos casos (plantilla nueva sin guardar, plantilla guardada pero inactiva). Desplegado (`fb35393`).
6f. ~~**Fix: "Imprimir" podía imprimir el documento equivocado.**~~ Encontrado (no reportado por Mateo) probando el flujo completo de imprimir un contrato real con Playwright: `ContractDetailPage` habilitaba "Imprimir" desde el primer render, sin esperar a que la plantilla activa terminara de cargar — medido en vivo, esa carga tardaba hasta ~3.8s en una visita fría. Un click en esa ventana imprimía el documento de siempre en vez del configurado, sin ningún aviso. Fix: el botón ahora se deshabilita ("Cargando…") hasta que la plantilla activa resuelve — mismo patrón que ya usa el resto de la app. Desplegado (`cacfd7b`) y **confirmado en vivo con 3 corridas limpias**: el instante en que el botón se vuelve clickeable, el contenido de impresión ya es el correcto, siempre.
**Decidido por Mateo (28/08):** verificando lo anterior se encontró que `classic` (el formato que usa cualquier empresa que nunca toque esta feature) no imprime pixel-idéntico a como imprimía antes — el borde bajo el encabezado pasó de una línea simple (`border-black/20`) a una doble más oscura (`border-double border-black/30`), confirmado con `getComputedStyle` en vivo, no solo mirando una captura. El resto del documento es idéntico carácter por carácter. Mateo lo aceptó como mejora intencional, no como regresión — se corrigió el comentario de `PrintLayout.tsx` que prometía "cero regresión".
7. ~~**Conteo por denominación en el cierre de caja.**~~ Hecho (02/09) — ayuda opcional en el diálogo de cierre: se digita cuántos billetes/monedas hay de cada denominación y llena el mismo `counted_cash` de siempre. Backend sin cambios; aritmética en centavos enteros.
8. ~~**`PATCH /me` + pantalla de perfil.**~~ Hecho (02/09) — endpoint nuevo (solo `full_name`/`photo_url`; el schema no acepta `role_id`/`status`, que es lo que permite que no exija permiso) + `/perfil`, accesible desde el menú del avatar. `MeOut` ahora lee nombre/foto de la fila y no del `CurrentUser` cacheado, para que la respuesta no salga con el nombre viejo.
9. ~~**Latencia de `GET /catalogs/categories`.**~~ Cerrado (02/09) como **medición equivocada, sin cambio de código**: medido en serie, la 1ª llamada da 7.9s y las siguientes ~0.79s — y `/me`, `/accounts`, `/catalogs/suppliers` y `/reports/dashboard` dan todas ~0.75-0.88s. No hay nada específico de categorías: ~0.8s es el piso de la app y los 4s eran el **cold start** de Fly (`min_machines_running = 0`, decisión de costo ya documentada). Tampoco falta índice: los `unique (company_id, ...)` ya lo dan con `company_id` como columna líder.
10. ~~**Menor: la fila de pestañas de Inventario se cortaba en pantallas angostas.**~~ Hecho (02/09) — scroll horizontal en el contenedor de `TabsList` (verificado en 390px: 409px de contenido en 342px de ancho, scrollable).
11. **Nuevo (28/08, sin diagnosticar — se resolvió solo, vigilar): el login por contraseña de Supabase Auth se colgó unos minutos.** `POST {SUPABASE_URL}/auth/v1/token?grant_type=password` no respondió en 30s (confirmado con `curl` directo, no un problema de Playwright), mientras el backend en Fly, el REST API de Supabase y los endpoints livianos de Auth (`/health`, `/settings`) respondían normal — aislado al grant de contraseña específicamente. Se recuperó solo minutos después (200 OK en 1.6s, sin ninguna acción de nadie). Causa raíz desconocida — no es algo diagnosticable ni arreglable desde este repo. Anotado por si vuelve a pasar: no es un problema del front/backend de este proyecto, es del lado de Supabase.

12. ~~**`GET /reports/series?months=12`.**~~ Hecho (02/09) — serie mensual de ventas/intereses/gastos desde los DOCUMENTOS, con la misma semántica de ingreso que `/profit` y `/pawn-performance` (no una tercera definición). Gráfica de 12 meses en `/reportes`, deliberadamente independiente del rango del date picker. Los meses sin actividad vienen en cero para que la línea no una dos meses no consecutivos.
13. ~~**Filtros de fecha en `GET /sales`.**~~ Hecho (02/09) — `?from_date`/`?to_date`, comparando `sold_at` en la zona de la EMPRESA (una venta de las 7pm en Bogotá es de ese día, no del siguiente). Con eso, "prendas más vendidas"/"categorías más movidas" pasaron de ser el histórico completo a seguir el rango elegido, que era lo que faltaba.
14. ~~**Bug encontrado de paso (02/09): el buscador de contratos devolvía de más.**~~ `?q=` hacía match por PREFIJO contra el documento del cliente, así que buscar un número de contrato corto ("5") devolvía todo contrato cuyo cliente tuviera cédula empezada en 5. Ahora el documento solo se busca con 5+ caracteres. **El test que lo cubría ya estaba en rojo** pese a que este documento decía "307/307 en verde" — ahora son 314/314.

15. ~~**URGENTE (03/09): "no se pudo guardar la contraseña" al crear usuarios en la empresa La Legal.**~~ **Causa encontrada y arreglada.** El `action_link` de Supabase es un **GET de un solo uso**: basta con *pedir* la URL para quemarla. Comprobado en vivo — `curl -A "WhatsApp/2.23" "$LINK"` devuelve la sesión, y el siguiente GET ya da `otp_expired`. Eso es exactamente lo que hacen los generadores de vista previa de WhatsApp/Telegram/Slack y los escáneres de correo: el admin pegaba el enlace en un chat, el crawler lo quemaba al instante para armar la tarjetita, y la persona llegaba **sin sesión** — veía el formulario igual y al guardar recibía un error genérico que mandaba a reintentar algo imposible. Por eso nadie podía reproducirlo: quien probaba abría el enlace directo. En la base quedaba el rastro más confuso posible (`last_sign_in_at` puesto por el crawler, sin contraseña nunca).
    **Fix:** el enlace ya no es el de GoTrue sino uno a la app (`/auth/callback?token_hash=…&type=…`) que se canjea con `verifyOtp`, un **POST** — un crawler que haga GET solo se baja el HTML de la SPA. Y un enlace que llegue muerto ahora tiene pantalla propia ("Este enlace ya se usó") en vez del genérico. De paso desaparece la trampa del `redirect_to` (§3 del runbook): sin redirect de Supabase de por medio, ya no importa si la URL está en la lista de permitidas. **Verificado en vivo:** el mismo enlace, tras 4 GETs de crawler simulados, se abrió en un navegador real, guardó la contraseña y entró a la app. Detalle completo y árbol de decisión: [`RUNBOOK_USUARIOS.md`](RUNBOOK_USUARIOS.md).
16. ~~**Redirect URLs de Supabase.**~~ Mateo las agregó (03/09); verificado antes y después. **Y las plantillas de correo no se pueden editar en el plan actual del proyecto** (04/09), así que el enlace que manda Supabase conserva los dos problemas que el copiado a mano ya no tiene. **La salida fue dejar de depender del correo:** el alta de una empresa nueva era el único camino que lo exigía —invitaba al primer admin con `send_email=true` y tiraba el enlace— y desde el 04/09 devuelve el enlace para que lo entregue el super-admin. Con eso, los cuatro caminos de alta y rescate funcionan sin correo; el único que queda es "¿Olvidaste tu contraseña?" del login, como salida de emergencia, y su peor caso ya no es silencioso.

17. ~~**LA GRAN LEGAL: "no podemos crear contratos con ningún usuario".**~~ **Causa encontrada (03/09).** No era un bug de contratos: **nunca habían abierto una sesión de caja** desde que se creó la empresa el 23/08 — once días. El desembolso del préstamo sale en efectivo y el efectivo exige caja abierta, así que cada intento moría con `CASH_SESSION_NOT_OPEN`, para todos los usuarios. Reproducido creando una empresa espejo con su configuración exacta (mismo árbol de categorías, una sola cuenta de efectivo, mismo set de permisos del rol Asesor): con caja abierta el contrato se crea sin problema, tanto de Admin como de Asesor; con caja cerrada falla siempre.
    **Lo que lo volvió invisible fueron dos mensajes, ambos arreglados:** (a) `GET /cashbox/sessions/current` devolvía `NOT_FOUND` y el front esperaba `CASH_SESSION_NOT_OPEN`, así que la franja global mostraba **"No se pudo consultar el estado de la caja"** en vez de "Caja cerrada — no se pueden registrar operaciones de dinero" con su botón "Abrir caja". Toda esa rama del banner era **código muerto que ningún usuario había visto nunca**. (b) El diálogo de "Caja cerrada" ofrecía solo "Entendido" a quien no tiene `cashbox.open_close`, sin nombrar la acción ni a quién pedírsela — su propio docstring prometía ese aviso desde el día uno y nunca se implementó. Verificado en vivo tras el deploy: el banner dice "Caja cerrada" con el botón para el admin, y el asesor recibe "Pídele a un administrador… que la abra". Detalle y checklist de diagnóstico: [`RUNBOOK_USUARIOS.md`](RUNBOOK_USUARIOS.md) §7.
18. ~~**"Olvidaste tu contraseña" daba acceso directo a la plataforma.**~~ **Resuelto por configuración (Mateo, 03/09).** La URL de producción no estaba en las *Redirect URLs* de Supabase, así que descartaba el `redirect_to` en silencio y mandaba a la **Site URL** — la raíz de la app, sin `/auth/callback`: la persona entraba con sesión activa y nadie le pedía contraseña nueva. Verificado antes y después: ahora Supabase respeta ambas URLs. **Queda un pendiente** para que no pueda repetirse: cambiar las plantillas de correo a `{{ .TokenHash }}` (ver 16).
19. ~~**¿Tiene sentido generar el "enlace de activación" de un usuario ya activo?**~~ Sí, pero estaba mal nombrado: es el único rescate que no depende del correo (limitado a unos pocos envíos por hora). El botón decía "Generar enlace de recuperación" para todos, también para quien nunca ha entrado — a esa persona no se le recupera nada. Ahora el nombre y la explicación cambian según el estado: **activación** para `invited`, **cambiar la contraseña** para `active`.

20. ~~**El botón "Crear contrato" no daba ninguna señal cuando faltaba el cliente.**~~ Hecho (03/09). Reportado por Mateo al cerrar el punto 17: "no mostraba ningún error o mensaje informativo". Reproducido: con todo lleno menos el cliente, el clic pintaba "Selecciona un cliente" ~800px por encima del botón, sin scroll, sin foco y sin toast — medido, `visibles sin scroll: (NINGUNO)`. Dos huecos sumados: `MoneyInput` no reenvía `ref` (RHF no podía enfocar el monto) y el cliente no está en el schema de Zod, así que ni se evaluaba cuando además faltaba otro campo — había que enviar dos veces para enterarse. `lib/forms/revealFirstError.ts` lleva a la vista el problema que esté **más arriba en el documento**, mezclando errores de RHF con los de estado propio. Aplicado en crear e importar contratos. Verificado en vivo: la página sube sola y el foco cae en el buscador de cliente.

21. ~~**Todo 422 de la aplicación era invisible.**~~ Hecho (03/09). Mateo precisó el reporte: "aparecía cargando y luego volvía sin crear nada y sin mostrar ningún mensaje" — la petición sí salía y fallaba en silencio. `applyServerErrors` leía `details.errors` como `{campo: [mensajes]}` cuando el backend siempre mandó la lista de Pydantic (`[{loc, msg, type}]`): `Object.entries` sobre un array no marcaba ningún campo **y aun así devolvía `null`**, que significa "ya lo mostré". Ningún formulario de la app mostraba nunca un error de validación del servidor. Tres cosas lo taparon: el tipo `ApiErrorDetails.errors` declaraba la forma inventada, había un test en verde escrito contra esa misma suposición, y `return null` no exigía haber marcado nada. Arreglado el parseo (de `loc` sale `items.0.weight_grams`, el nombre real del input), la invariante (`null` solo si se marcó algo), la traducción de los mensajes de Pydantic al español, y los tres campos de prenda que no pintaban su error. **Causa de raíz del caso concreto:** el peso escrito con coma ("10,5", lo natural en Colombia) llegaba tal cual al backend; ahora se normaliza al armar el body. Verificado en vivo: con coma se crea el contrato; con un decimal inválido sale el mensaje junto al campo.

22. ~~**Auditoría completa de los flujos de identidad.**~~ Hecha (04/09), pedida por Mateo tras el incidente. Se recorrieron los ocho flujos contra dev con una empresa espejo: **seis defectos, los seis arreglados y verificados en vivo**. El más grave: `invited → active` ocurría con cualquier JWT válido, y abrir el enlace de invitación **ya produce uno** — así que alguien podía quedar `active` sin haber puesto contraseña nunca, aparecer como "Activo" en la lista del admin y estar bloqueado para siempre. Ahora se activa solo con `amr: password` (login de verdad), y el front entra con la contraseña recién creada para que la activación sea inmediata. Los otros cinco: reinvitar al mismo correo daba un **HTTP 500 en texto plano** (ahora 409 que dice usar "Generar enlace de activación"); invitar un correo ya registrado daba un 502 que se lee como falla del sistema (ahora 409); **no existía forma de cambiar la propia contraseña** (ahora en `/perfil`, verificando la actual); un usuario borrado desde el panel de Supabase seguía listado y su enlace moría con 502 (ahora 409 que explica cómo repararlo); y desactivarse a uno mismo lo impedía solo la UI. Comprobado que sí estaban bien: el empleado desactivado con sesión abierta, los tres caminos del último administrador, y el aislamiento entre empresas. Detalle completo: [`RUNBOOK_USUARIOS.md`](RUNBOOK_USUARIOS.md) §8.

23. ~~**El alta de una empresa dependía sí o sí del correo de Supabase.**~~ Hecho (04/09). Invitaba al primer administrador con `send_email=true` y **tiraba el enlace a la basura**. Si ese correo no llegaba, el cliente nuevo se quedaba con una empresa creada y sin forma de entrar — y no había rescate: para generarle otro enlace hay que estar dentro de esa empresa, y él era el único que iba a poder estarlo. Ahora el enlace vuelve en la respuesta y el diálogo del panel de plataforma lo muestra con su botón de copiar, sin cerrarse (mismo patrón que invitar). Verificado creando una empresa de punta a punta por la UI. Con esto, la app ya no depende del correo para ningún alta ni rescate.

24. ~~**La auditoría no mostraba el trabajo de los empleados.**~~ Hecho (08/09). Reportado por Mateo: invitó a alguien, hizo una venta con su usuario y en Auditoría no salía nada. Eran **tres** defectos encadenados. (a) **El trabajo diario no se auditaba** — solo las excepciones (descuentos, anulaciones, remates); en toda la base no había una sola fila `create_sale` habiendo ventas. Se agregaron `create_sale`, `create_payment`, `open_session`, `create_entry` y `create_customer` (este módulo no auditaba nada, con datos personales de por medio). (b) **Doce acciones salían en crudo** en pantalla (`auction_contract`, `generate_recovery_link`…) porque el mapa de etiquetas se había poblado "con los valores vistos el 18/08" — y al revés, `open_session` llevaba meses con etiqueta para algo que nunca se escribía. (c) **El log salía en orden ARBITRARIO**: `order by id` sobre UUID aleatorios, así que lo último que hizo alguien podía caer en cualquier página — el índice `ix_audit_company_date` existía desde la primera migración sin usarse. Un test nuevo lee los `action=` del código y falla si aparece uno sin registrar. Verificado en vivo actuando como el empleado real. Detalle en `frontend-starter/docs/IMPLEMENTATION.md`.

25. ~~**Cobertura completa de la auditoría.**~~ Hecha (08/09), pedida por Mateo al cerrar el punto 24 ("también debe cubrir la creación, abonos y todo lo relacionado a contratos"). Se cruzaron **los 47 endpoints que modifican datos** contra si auditaban: quedaban **doce sin registrar**. Se agregaron `update_contract` (con before/after — el avalúo), `pay_entry` (pagarle a un proveedor), `publish_item` (emite el código y pone el artículo en vitrina), `update_product` (el precio cambia para todos los lotes), `create/update_category` (de acá salen el plazo y la mora que se **congelan** en cada contrato al firmarlo), `create/update_supplier`, `update_customer` (Ley 1581), `create/update_account` y `create_expense_category`. Queda fuera `update_item` a propósito: solo cambia fotos. **48 acciones auditadas**, con el ciclo de contratos completo. El test del catálogo encontró las doce solo.

26. ~~**Auditoría de QA completa, por fases.**~~ Hecha (08–09/09), pedida por Mateo: probar la aplicación entera contra su propia arquitectura y sus reglas de negocio. **Diez fases cerradas**, registro completo y reproducible en [`backend-starter/docs/QA_AUDITORIA.md`](backend-starter/docs/QA_AUDITORIA.md); el arsenal de scripts, en `backend-starter/scripts/qa/`.

    **Lo que salió sólido:** matriz de permisos **420/420 correcta**, cero endpoints sin guard, **cero fugas entre empresas**, Storage impecable (una empresa no ve ni sabe que existe un archivo de otra), la aritmética de contratos exacta contra el ejemplo de `CLAUDE.md`, el arqueo cuadrando al peso, y la auditoría sin dejar nada fuera.

    **El hallazgo de más valor fueron dos bugs que se tapaban entre sí:** el job nocturno no estaba corriendo en Fly (borrado por accidente el 27/08 como "máquina huérfana"), así que ninguna suscripción llegaba nunca a `expired` — y por eso nadie había descubierto que **una suscripción vencida no se podía renovar por ninguna vía**: la empresa quedaba muerta para siempre. Los dos arreglados y verificados en vivo.

    **Trece hallazgos aplicados y verificados** contra el entorno desplegado, no solo commiteados: el descuento de interés ahora sí baja el ingreso (se sobreestimaba la utilidad); bajo concurrencia quien pierde la carrera recibe un error de negocio y no un 500, con `IDEMPOTENCY_IN_PROGRESS` estrenado para el reintento que llega mientras la original sigue en vuelo; no se puede activar una plantilla vacía —imprimía contratos sin cliente, sin prendas y sin firmas— y ahora hay camino de vuelta al documento de fábrica; contraste WCAG AA en los seis tokens semánticos; cero desborde a 360 px en las 12 pantallas; y los enlaces de invitación dejaron de llevar el nombre interno del proyecto, que se leía como phishing.

    **Quedan siete temas abiertos a propósito**, ninguno de dinero, fuga ni escalada de privilegios: cuatro necesitan definición de negocio o de producto ([`frontend-starter/docs/DECISIONES_PENDIENTES.md`](frontend-starter/docs/DECISIONES_PENDIENTES.md)) y tres son mejoras con su propia tanda — la mayor, que las exportaciones a Excel cortan a 10.000 filas **en silencio**.

    **De la auditoría quedaron cuatro tests de regresión** que vigilan lo que nadie vigilaba: que ningún endpoint quede sin permiso, que todo código de error esté en el catálogo, que ningún listado responda 5xx con una empresa vacía, y que los tokens de texto cumplan contraste.

27. ~~**LA GRAN LEGAL no tenía con qué probar contratos.**~~ Hecho (09/09), pedido por Mateo. Tenía cinco contratos, todos `active` y del mismo día: ni filtros por estado, ni cola de remate, ni paz y salvo se podían mirar. Se sembraron **22 contratos cubriendo los seis estados** (3–4 de cada uno) con `backend-starter/scripts/qa/seed_contratos.py`. Total: 27 contratos.

    **La llave fue `POST /contracts/import`, no `POST /contracts`.** La creación normal desembolsa (caja abierta + `cash_movement`) y fija `start_date = hoy`, así que **solo puede producir `active`**: el estado no se acepta en ningún body, lo deriva el backend de `interest_paid_until` contra hoy. El import acepta las dos fechas y no toca la caja — es el único camino para fabricar un estado.

    **Lo que hay que saber para leer la pantalla:** "listo para remate" no es un `status`, es `in_extension` con `extension_ends_at` pasado. Por eso hay 8 `in_extension` (4 en prórroga vigente + 4 vencidas) y 4 en la cola de remate. Y un contrato de Tecnología **no puede** estar `in_arrears` en esa empresa: su ventana de mora es 1 mes, así que el primer mes adeudado ya dispara la prórroga.

    Los 3 `paid` cobran **por transferencia a Bancolombia** a propósito — verificado que no hay ni un movimiento en efectivo, así que el arqueo del cajón no se movió. Los 3 `auctioned` dejaron sus tres artículos en `draft` sin publicar. Todo lleva `legacy_code` con prefijo `DEMO-`, y `--limpiar` lo borra. Detalle completo (incluido por qué el usuario `qa.datos.prueba@qalab.com` queda `inactive`): [`backend-starter/docs/QA_AUDITORIA.md`](backend-starter/docs/QA_AUDITORIA.md) § "Datos de prueba en LA GRAN LEGAL".

28. ~~**El saldo del efectivo era propiedad del turno, no del cajón.**~~ Paso 1 hecho (10/09, migración `00048`). Salió de que Mateo probara con el cliente y reportara un "límite de 300.000" al crear cuentas de efectivo. **No había ningún límite:** 300.000 era el saldo de apertura de su turno, y el saldo de una cuenta `cash` se derivaba de la sesión abierta en vez de sus propios movimientos. Tres defectos con la misma causa — sin turno abierto el cajón reportaba `0.00`; las tres cuentas de efectivo de la empresa mostraban el **mismo** número; y el saldo de apertura era el único dato de toda la app que aparecía **sin documento**, escrito a mano cada mañana sin comparar contra el cierre anterior.

    Ahora los tres tipos de cuenta se calculan igual (`opening_balance` + sus movimientos), abrir el turno **hereda** el saldo en vez de digitarlo, y los arqueos de apertura y cierre emiten un `adjustment` con motivo y responsable: después de cerrar, el cajón vale lo que se contó. La migración convierte la historia en movimientos y de paso reconstruye cada descuadre de apertura que nadie había mirado. **344 tests** (7 nuevos; los 4 que dependen del cálculo se vieron fallar con el código viejo antes de darlos por buenos). Migración aplicada en dev; **el backend todavía no está desplegado en Fly**. El modelo completo y los pasos que faltan —caja fuerte (`vault`), varias cuentas de efectivo— en [`backend-starter/docs/CAJA_TRAZABILIDAD.md`](backend-starter/docs/CAJA_TRAZABILIDAD.md).

29. **Dos specs de diseño listas, sin implementar:** [`RECARGOS.md`](backend-starter/docs/RECARGOS.md) (ampliar el préstamo sobre un contrato vivo — no modifica el contrato, lo **sucede**) y [`CAJA_TRAZABILIDAD.md`](backend-starter/docs/CAJA_TRAZABILIDAD.md). Las dos tienen preguntas de negocio pendientes al final.

30. ~~**El recargo: ampliar el préstamo sobre un contrato vivo.**~~ Hecho (10/09, migración `00051`), con el diseño acordado antes de escribir código en [`backend-starter/docs/RECARGOS.md`](backend-starter/docs/RECARGOS.md).

    **No modifica el contrato: lo sucede.** No es una preferencia — el interés se cobra en meses completos anclados a `interest_paid_until` y toda la máquina de estados cuelga de esa ancla; y el papel que el cliente firmó dice un capital, así que si cambia ya no describe la deuda. El viejo queda `superseded` con su firma intacta; el sucesor nace sin ella porque imprimirlo y firmarlo es su razón de ser.

    Tres invariantes que costaron pensarse y quedaron con test: **la ventana se mide desde la RAÍZ de la cadena** (si se midiera desde el contrato actual, un recargo de $1 el último día reiniciaría el reloj para siempre); **a la caja sale solo el delta** (el capital viejo ya salió el día del contrato original); y **el interés vencido nunca se suma al capital** (anatocismo). Las dos primeras se vieron fallar con la versión ingenua antes de darlas por buenas.

    **El cupo lo gobierna un permiso, no una casilla.** Mateo propuso un interruptor por empresa; se descartó porque nadie sabe responder eso al dar de alta una empresa y porque la misma regla se comportaría distinto en dos pantallas. `contracts.override_ltv` expresa el interruptor igual —dárselo a todos o a nadie— y encima cubre el caso que un booleano no puede: que el asesor no pueda y el dueño sí. Y **la ventana es política de EMPRESA** (`company.settings.extension_window_days`), no un 28 quemado.

    Verificado en vivo, no solo en tests: #28 → #29, capital 1.000.000 → 1.400.000, interés mensual 50.000 → 70.000, y la pantalla comprobada con navegador real (`scripts/qa/ui_recargo.js`).

31. ~~**El LTV estaba en 10 % y la alerta había dejado de significar algo.**~~ Corregido (10/09) a los valores que la propia migración `00004` recomendaba: Joyería 70 %, Plata 60 % (excepción propia), Tecnología 40 % — tres cambios en vez de siete, aprovechando la herencia por campo. Fue por la API, así que quedó auditado. **No se reescribió el `ltv_warning` de los contratos ya creados**: es la foto del criterio con el que se firmaron, igual que la tasa.

32. ~~**El documento del cliente tenía una sola foto.**~~ Hecho (10/09, `00050`). `doc_photos jsonb` —el patrón que el proyecto ya usa tres veces— en vez de una columna `doc_photo_back_url`: generaliza sin adivinar, y el orden ES la semántica (la primera es el frente). Expandir/contraer, con `doc_photo_url` todavía sincronizada.

33. **Multi-caja y multi-sucursal: aplazados a fase 2 (decisión de Mateo, 10/09).** No se construye nada por ahora. Lo que sí se verificó es que **los datos que se crean hoy van a servir el día que llegue**: las 7 empresas de dev tienen **una** registradora y **una** cuenta de efectivo activa cada una, ningún endpoint puede crear una segunda registradora, y los 18 movimientos sin `session_id` son los `adjustment` de `00048` (atribuibles por su referencia). Un backfill hecho hoy sería determinista y sin pérdida.

    **Las tres adecuaciones están HECHAS** ([`SUCURSALES.md`](backend-starter/docs/SUCURSALES.md) §5), y ninguna construye la función ni cambia comportamiento visible: (a) migración **`00052`** que liga cada cajón a su registradora —`insert_cash_register` e `insert_default_accounts` corrían seguidas y no se hablaban, así que ninguna cuenta de efectivo sabía a qué caja pertenecía—, aplicada en **las dos bases**; (b) `get_active_register` pasó a `list_active_registers` + un helper único `_resolve_active_register`, que **falla con `MULTIPLE_REGISTERS_NOT_SUPPORTED`** en vez de tomar la más antigua en silencio; (c) el guardián, que resultó ser **dos** cosas —un test de código y **`scripts/qa/verificar_sedes.py`** para los datos vivos, porque un test de CI corre contra una base efímera y nunca vería que una empresa real creció una segunda caja—. **372 tests backend · 169 front. Desplegado en Fly y Vercel, y verificado sobre lo servido** (11/09).

    **Verificado que NO rompe lo que ya existía** (`scripts/qa/verificar_regresion_caja.py`, contra el backend desplegado): los 4 endpoints que cambiaron se comportan igual con una sola registradora; **`AccountOut` no expone `register_id`**, así que el contrato de la API no se movió — `gen:api` lo confirmó: el único diff en `types/api.ts` fue un comentario, cero cambios de schema; y contratos, ventas, inventario, clientes, auditoría y dashboard siguen intactos porque resuelven la sesión por `integration.get_open_session`, que **no pasa por el helper**. Un gasto real de 1.000 bajó el efectivo esperado como debe. Y el error nuevo **existe en lo servido**: con una segunda registradora insertada a mano en el laboratorio, los cuatro caminos dieron `409 MULTIPLE_REGISTERS_NOT_SUPPORTED`; eliminada después, todo vuelve a verde.

    **Hallazgo incidental, previo a este trabajo** (comprobado con `git stash`): `test_abrir_sin_contar_hereda_el_saldo_del_cajon` **solo fallaba entre las 7pm y medianoche**. Envejecía una sesión con `current_date - 1`, y `current_date` en Postgres es UTC mientras la sesión se creó con el "hoy" de la empresa — a esa hora las dos fechas no coinciden y el envejecido no hacía nada. Es **la misma ventana de 5 horas** que el backend ya arregló con `tenant_time`, reaparecida dentro de un test. Corregido a `session_date - 1`. **La regla de "hoy es la fecha de la empresa" vale también en los tests.**

    **El riesgo principal no es técnico:** que el cliente abra un segundo local y se siga operando sobre un solo registro. Nada falla, nada avisa, y el dato de qué pasó en cada sede no se puede reconstruir después — el inventario en particular no tiene ningún vínculo con una caja. **El momento de avisar es antes de abrir el segundo local, no después.**

    **El diseño ya está decidido** (Parte II del documento), aunque no haya fecha: mismo NIT con la sede como **dimensión** (no una empresa por local); la sede **estampada** en cada documento y no derivada de por dónde pasó la plata; ubicación en el lote más un `branch_transfer` calcado de `account_transfer`; numeración con **prefijo visible** (`CHP-000045`) sin tocar `next_counter` ni los códigos de inventario; y el **alcance de acceso como atributo del usuario**, restrictivo por defecto pero hecho cumplir en el servicio, no en RLS — se puede endurecer después sin tocar una sola tabla.

34. ~~**El LTV en vivo en el formulario de contrato.**~~ Hecho (11/09). Era **lo único de "reportado y no hecho"** que seguía sin empezarse. La alerta vivía solo en el detalle del contrato ya creado: llegaba después de que la plata salió. Ahora, mientras se llena el formulario, dice *"Puede prestar hasta $600.000 — 30 % del avalúo. Va en el 50 %"*, y si se pasa, cuánto se pasa y qué hacer, con el texto cambiando según `contracts.override_ltv`. **El tope sale de la categoría de la PRIMERA prenda**, que es lo que hace el backend — espejar otro criterio mostraría un número y el servidor aplicaría otro. **No deshabilita el botón**: quien decide es el backend.

    **El bug que los tests no vieron.** La comprobación en navegador dijo que se pasaba en **$40.000.000** donde debía decir $400.000 — exactamente 100×. `evaluarLtv` pasaba los montos por `parseMoneyInput` asumiendo que el formulario guarda el texto **enmascarado**; no lo guarda, guarda el decimal canónico (`"1000000.00"`), como dice el propio docstring de `MoneyInput`. Los 14 tests estaban en verde sobre ese cálculo porque los fixtures usaban `"1.000.000"` — lo que el campo **muestra**, no lo que **guarda**. **Segunda vez en la misma sesión**: antes había sido `max_ltv_pct` como número cuando la API lo manda como string. Corregidos, 3 de los 14 se ponen rojos con el bug reintroducido.

    **Corrección al porqué que lo motivaba:** `CONTINUAR.md` decía que *"un asesor puede llenar el formulario entero y recibir el 403 al final"*. Comprobado contra dev: en **LA GRAN LEGAL todos los roles que crean contratos tienen `override_ltv`** (la migración `00051` se lo dio a todos para que nadie perdiera acceso), así que hoy no le pasa a nadie. El aviso sigue valiendo —el cupo era invisible antes de prestar— pero el 403 solo aparece el día que se le apriete el rol al Asesor.

### Auditoría de UX en vivo (27/08/2026)

Mateo probó la app y reportó 11 puntos de una sentada. Diagnóstico completo, con archivo/línea de cada uno, en `frontend-starter/docs/PENDIENTES_FRONTEND.md`.

**✅ Resueltos los 11 de los 11 + 3 de las 5 causas de lentitud, siete tandas:**
- Los cinco reportes de "pantalla en blanco mientras carga" (modal de Transformación, Kardex, Cuentas, Reportes/Contabilidad) tenían una sola causa — `--color-muted` era literalmente el mismo color que el fondo de la app — y el modal que "hace overflow" tenía una segunda causa única: el modal base no limitaba su altura. Dos fixes de bajo riesgo resolvieron los seis síntomas de una vez.
- El formulario de Transformación no tenía NINGÚN estado de carga en sus selects de categoría (no era de color — faltaba el condicional). Ahora se deshabilitan con "Cargando…".
- "Volver" y "Cancelar": `BackLink` nuevo (`components/shared/`) reemplaza las implementaciones a mano y se agregó a los 5 formularios de creación que no tenían nada; los 7 diálogos de creación sin botón "Cancelar" ganaron el mismo patrón que ya existía en `features/accounts/`. `SaleFormPage` y `TransformationFormPage` —los dos sin ningún resguardo— ganaron `useBlocker` con confirmación, igual que los otros tres formularios de página completa.
- **Lentitud — la causa que más se sentía:** `SaleReceiptDialog`, `ReturnFormDialog` y `ContractDetailPage` pedían un artículo por línea (N requests en paralelo por cada comprobante/devolución/contrato abierto). `GET /inventory/items?ids=` nuevo en el backend (aditivo) + `useItemsByIds()` en el front lo bajan a un solo request. De paso, `QueryClient` ganó un `staleTime` global de 15s — antes cualquier vuelta a la pestaña del navegador reejecutaba todo lo montado de una.
- Historial de proveedores → detalle de compra: `EntryDetailDialog`/`useEntry`/`usePayEntry` promovidos a `components/shared/`/`lib/inventory/entries.ts` (mismo movimiento que `SaleReceiptDialog`). Conectado en `SupplierDetailPage` y, de paso, en la pestaña "Compras" de cada producto (`ProductRow.tsx`, mismo hueco). Verificado en vivo con Playwright: clic en una fila abre el detalle real.
- `GET /contracts?customer_id=` nuevo en el backend (sin migración, mismo patrón que `?customer_id=` de `GET /sales`) — `useCustomerContracts` ya no trae 200 contratos para filtrar en el navegador.
- Exportar inventario a Excel: botón nuevo en Inventario → Lotes, trae TODOS los artículos que cumplen los filtros activos (no solo la página cargada) y genera un `.xlsx` real. Librería `xlsx` instalada desde el CDN oficial de SheetJS (la de npm tiene 2 CVEs sin parche) y cargada con `import()` dinámico para no engordar el bundle principal. Verificado en vivo contra dev real.

**Dos bugs reportados el mismo día DESPUÉS de dar por resueltos los puntos de arriba — ambos corregidos:**
- **Modal de Kardex "se ve raro, necesita scroll horizontal":** ya lo tenía — el problema real era que `AppDialog` solo llegaba a `size="lg"` (512px), insuficiente para una tabla de 7 columnas con montos y fechas. `AppDialog` gana `size="xl"` (768px), usado en `KardexDialog`.
- **Historial de proveedor "se queda cargando, y al rato se abre el modal":** `EntryDetailDialog` esperaba a que el fetch resolviera ANTES de renderizarse — sin ningún indicio visual entre el click y la respuesta. Ahora abre al instante con su propio skeleton (mismo patrón que `KardexDialog`). Mismo principio ya aprendido con el router: si la app no muestra que está trabajando, para el usuario está rota.

- **Infra de Fly dev (27/08/2026):** la máquina corría en `gru` (São Paulo) mientras la base (Supabase) vive en AWS `us-west-2` (Oregon) — cada consulta SQL cruzaba el continente, y esta app hace varias por request. Movida a `sjc` (San José, CA, la región de Fly más cercana a Oregon) + subida de 256MB a 512MB. De paso se limpió una máquina huérfana (fuera del process group, sin deploys desde el 17/08) y se corrigió que el relanzamiento en `sjc` había dejado 2 máquinas activas (alta disponibilidad no pedida para dev). `min_machines_running` se dejó en `0` a propósito — cold start aceptado, prioridad en costo mínimo. **Sin medir el efecto real todavía** (los tiempos end-to-end tras el cambio, 2.2-3.9s por página, mezclan Vercel+Supabase Auth+Fly+render — no aíslan la parte de red app↔base); toca ver cómo se siente con uso real.

- Tema oscuro/claro: Claro/Oscuro/Sistema, por dispositivo (`localStorage`, no backend — es una preferencia de pantalla, no un dato de negocio). Sin parpadeo (script inline en `index.html` antes de que React monte). ~25 variables redefinidas en `tokens.css` bajo `[data-theme='dark']`, cero componentes tocados (todo ya leía de tokens). Toggle nuevo en el topbar. Verificado en vivo con Playwright: Inicio y Reportes completos en oscuro, buen contraste, persiste tras recargar.

Los diez commits del día están desplegados (backend en Fly, frontend en Vercel) y verificados en vivo. **Los 11 puntos de la auditoría de UX del 27/08 quedaron resueltos** (9 completos, 2 parciales con lo que falta anotado abajo).

**Sigue abierto (backlog de antes de la auditoría UX, ya no hay puntos de la auditoría en sí):**
- **Exportar a Excel: completo (27/08)** — Inventario, Contratos, Ventas y Reportes. Contratos exporta por pestaña de estado activa, cliente resuelto a nombre (`fetchAllCustomers`, sin `?ids=` en `GET /customers` todavía — mismo hueco documentado). Ventas sin filtros, exporta todo (de paso se confirmó que `sale.status` `completed`/`voided` nunca estuvo en `STATUS_LABELS` — el badge en pantalla ya mostraba el código crudo; hallazgo documentado, no arreglado, fuera de alcance). Reportes es distinto a los otros tres — no es un listado, es un dashboard agregado: exporta 3 hojas (Resumen/Desglose/Rankings) directo de lo que ya está en memoria, sin fetch nuevo (`exportSheetsToExcel`, multi-hoja, nuevo en `lib/export/xlsx.ts`). Las cuatro verificadas en vivo contra dev real con Playwright.
- De paso (27/08): CSP de producción bloqueaba en silencio el script anti-parpadeo del tema oscuro — corregido con hash SHA-256 exacto en `vite.config.ts::cspPlugin` (ver detalle en `frontend-starter/docs/PENDIENTES_FRONTEND.md` #7).
- Lentitud, lo que falta: Reportes trae listados completos para agregación (`fetchAllPages` sobre ventas + artículos, hasta 5.000 de cada uno — problema distinto al de `?customer_id=`, ya resuelto), y el bundle de 1.7MB sin code-splitting por ruta (postergado a propósito — tocar cómo se definen las rutas tiene riesgo real de reintroducir pantallas en blanco si queda a medias).

## Trampas del entorno — leer antes de tocar nada

**Hay dos bases de datos.** Los tests corren contra **Postgres local** (`127.0.0.1:54322`); `.env`, `psql` a mano y `supabase db push` apuntan a la **Supabase dev remota**. Una migración nueva hay que aplicarla en **las dos**, o los tests fallan sin motivo aparente.

**Hay dos cuentas de Supabase.** El proyecto de la app es `driyubkodnsqxbtxcmaz`, pero el CLI de la máquina está autenticado con **otra cuenta** y `supabase projects list` muestra un proyecto ajeno. El ref correcto sale siempre de `SUPABASE_URL` en `.env`.

**Nunca `supabase config push`.** Empuja el `config.toml` completo, que es el de desarrollo local y trae `enable_signup = true` — reabriría los registros públicos que el proyecto tiene cerrados a propósito. Para tocar auth, `PATCH` a la Management API con solo los campos necesarios.

**Orden de deploy.** Migración aditiva → se puede aplicar antes. Migración que contrae (NOT NULL, DROP COLUMN) → **después** del `fly deploy`. Y `supabase db push` aplica **todas** las pendientes de golpe, así que una secuencia "aplicar A → deploy → aplicar B" necesita `psql` para el paso A.

**El deploy no es la prueba.** Un `git push` verde no dice que el bundle servido tenga el cambio, y un arreglo desplegado no dice que arregle lo que se midió. Durante la auditoría, el primer fix de un desborde a 360 px se aplicó al componente compartido y la pantalla siguió saliéndose **los mismos 59 px**: el problema estaba en otro contenedor. Volver a medir, siempre, sobre lo que está servido.

**Los cambios de permisos tardan hasta un minuto** en verse: `/me` se cachea 60s en el front y el backend cachea permisos por rol otro tanto. Es deliberado y está alineado entre ambos lados.

**Playwright SÍ está disponible en este entorno (corregido 28/08, sesión de la tarde).** No como dependencia del proyecto (`playwright` no está en `package.json` de ningún repo, ver `frontend-starter/docs/ARCHITECTURE.md` §10), pero `npx playwright` resuelve a una copia cacheada en `~/.npm/_npx/.../node_modules/playwright` con Chromium ya descargado (`~/Library/Caches/ms-playwright`) — usable con `require()` directo a esa ruta en un script Node suelto. Una sesión anterior el mismo día documentó lo contrario ("no hay Playwright ni ninguna herramienta de navegador en este entorno") tras confirmarlo vía subagente — no volver a asumirlo sin comprobar primero.

## Qué leer según lo que vayas a tocar

| Tema | Dónde |
|---|---|
| **La marca: nombre, logo, colores, dominio** | `marca/README.md` → `marca/IDENTIDAD.html`. Valores de token y la regla de las dos marcas: `frontend-starter/docs/DESIGN_SYSTEM.md` §1-bis |
| **Lo que se le entrega al cliente** | `marca/GUIA_USUARIO.html` — la guía de usuario, **completa: las ocho partes**, publicada y en vivo (versión 6, 22/09/2026). Falta solo lo opcional: las **capturas**, que van contra una empresa espejo sembrada (Ley 1581). Método para continuarla: `marca/README.md` |
| **Cómo se codifican productos y lotes** | `backend-starter/app/modules/inventory/rules.py` — **no `CONTEXTO.md` §3**, que describe el esquema de pieza única ya superado |
| Auditoría de QA: qué se probó y qué se encontró | `backend-starter/docs/QA_AUDITORIA.md` — diez fases, la más reciente arriba; al final, el laboratorio para retomarlo |
| Volver a correr esas pruebas | `backend-starter/scripts/qa/README.md` — qué prueba cada script y qué encontró |
| **Los dos guardianes** (correrlos después de cada deploy) | `backend-starter/scripts/qa/verificar_cadenas.py` (invariantes de datos vivos) y `verificar_job_nocturno.py` (la Machine de Fly). **0 sano · 1 roto · 2 no se pudo verificar** |
| **Avisos por correo** (spec, sin código) | `backend-starter/docs/NOTIFICACIONES.md` — siete preguntas de negocio al final |
| Decisiones de negocio/producto que la app está esperando | `frontend-starter/docs/DECISIONES_PENDIENTES.md` |
| Reglas del proyecto (obligatorias) | `CLAUDE.md` de cada repo |
| Registro vivo: qué se construyó y por qué | `frontend-starter/docs/IMPLEMENTATION.md` — **el más útil**, un bloque por sesión, más reciente arriba |
| Multi-tenancy, RLS, capas, permisos | `backend-starter/docs/ARCHITECTURE.md` |
| Contrato de la API | `backend-starter/docs/API_GUIDE.md` |
| Tokens, componentes, protocolos de UX | `frontend-starter/docs/DESIGN_SYSTEM.md` |
| Vercel, Supabase URL config, SMTP, producción | `frontend-starter/docs/DEPLOY.md` |
| Backlog priorizado | `backend-starter/docs/PENDIENTES_BACKEND_INFRA.md` |
| El capital del DUEÑO (aportes y retiros) | `backend-starter/docs/CAPITAL_DEL_DUENO.md` — por qué no es ingreso ni gasto, y por qué no hizo falta partida doble |
| Negocio (intereses, estados, remate) | `backend-starter/docs/CONTEXTO.md` — **ojo: su §3 afirma que multi-sucursal está "listo sin migración". No lo está**, ver `SUCURSALES.md` §2 |
| Multi-caja y multi-sucursal (fase 2) | `backend-starter/docs/SUCURSALES.md` — **aplazado** (10/09). Los datos de hoy están a salvo (verificado); quedan tres acciones para que siga siendo así, ver §5 |

## Principios que se ganaron a los golpes

Cada uno salió de un bug real y está documentado en detalle en su lugar:

- **El interés es ingreso; el capital recuperado no.** Prestar no es un gasto, cobrar no es una ganancia. Costó tres correcciones en reportes.
- **El costo nunca se promedia** (identificación específica, NIIF). El precio vive en el producto, el costo en el lote.
- **La cuenta es dónde está la plata; el medio es cómo se cobró.** Con Sistecrédito la diferencia es el negocio entero.
- **Los saldos se derivan, nunca se guardan.** Un saldo almacenado se desincroniza; uno derivado no puede.
- **Un 403 no es una falla.** Decir "no se pudo cargar" cuando falta un permiso manda al usuario a buscar un problema inexistente.
- **Un módulo nuevo trae sus propios permisos desde el día uno**, aunque parezcan redundantes. Reusar los de otro deja el módulo fuera de la matriz de roles.
- **Ocultar el ítem del menú no es protección.** Van siempre las dos: gate en el menú y guard en la ruta.
- **Ingreso no es ganancia.** Una utilidad que no resta el costo de ventas sobreestima por todo lo que costó la mercancía. El estado de resultados sale de los DOCUMENTOS, no de los movimientos de caja: una venta a crédito es ingreso aunque la plata no haya entrado.
- **Una cuenta por cobrar no es plata.** Una venta con Sistecrédito no es flujo de caja hasta que el convenio consigna. El filtro va por TIPO DE CUENTA, no por concepto — así vale también para los movimientos históricos.
- **Un traslado no es ingreso ni egreso.** Consignar el efectivo es la misma plata en otro bolsillo: no toca la utilidad, y sumarlo al flujo lo infla por los dos lados. Es el mismo principio del capital recuperado, aplicado a la caja.
- **Si un permiso se puede rodear por otra URL, no es un permiso.** El histórico de caja salía por dos puertas; cerrar solo una habría sido teatro.
- **Un vínculo que existe en los datos pero no en la aplicación no es trazabilidad.** La fundición enlazaba el egreso y el ingreso desde el día uno, pero llegar del lote de oro a su origen eran cuatro saltos sin endpoint. En una compraventa esa cadena termina en la prenda de un cliente: tiene que poder recorrerse **hacia atrás**, no solo hacia adelante.
- **Si la app no muestra que está trabajando, para el usuario está rota.** El router seguía pintando la pantalla anterior mientras resolvía la navegación, sin ningún indicador. Se reportó como un bug de la pantalla de contraseña; le pasaba a toda la app.
- **Que el código referencie un plugin no significa que esté instalado.** `TemplateEditor.tsx` usaba clases `prose` de `@tailwindcss/typography` desde el día que se escribió — el paquete nunca se agregó a `package.json`. Sin build ni tipos que lo detecten (son solo strings de clase), estuvo semanas sin hacer nada. Vale la pena grep-ear el `package.json` cuando algo "debería verse distinto y no se ve".
- **Un listado ordenado por un id aleatorio no está ordenado.** `order by id` sobre UUID pagina bien —no repite ni salta filas— y por eso nadie lo nota, pero el orden que produce no significa nada. Donde el orden ES la función (una auditoría, un histórico), la llave va por fecha.
- **Una auditoría que solo registra las excepciones no es una auditoría.** Si el descuento queda y la venta no, no se puede reconstruir qué pasó — y el dueño que abre la pantalla a preguntar "¿qué hizo esta persona?" recibe silencio.
- **Un estado que el sistema muestra tiene que ser el estado real.** `active` significaba "hizo un request", no "puede entrar" — y el badge verde tapaba a alguien bloqueado para siempre. Si un estado no responde la pregunta que el usuario tiene, no sirve para nada.
- **Un error tiene que nombrar la acción que falta, no solo negar la que se intentó.** Un 502 "no se pudo invitar" manda a reintentar en círculos; "ya invitaste a esta persona, genera el enlace desde su ficha" se resuelve en diez segundos.
- **Los comentarios que afirman algo del mundo exterior envejecen mal.** "Si llegó con un JWT válido ya puso su contraseña" era falso desde el día que se escribió, y nadie lo volvió a mirar porque sonaba razonable.
- **Un tipo de TypeScript escrito desde la suposición es una mentira que el compilador defiende.** `ApiErrorDetails.errors` declaraba `Record<string, string[]>` y el backend siempre mandó una lista; como nada valida en runtime, el error quedó bendecido por el tipado.
- **Un test escrito contra un payload inventado confirma el bug en vez de encontrarlo.** El de `applyServerErrors` llevaba meses en verde alimentando una forma que el backend nunca mandó. Los fixtures se copian de una respuesta real, no se escriben de memoria.
- **Devolver "ya lo mostré" es una promesa, y hay que poder cumplirla.** `applyServerErrors` retornaba `null` sin haber marcado un solo campo: el llamador confiaba y el usuario se quedaba mirando un formulario mudo.
- **Rechazar la coma decimal nunca fue una decisión, era un descuido.** En Colombia "10,5" es lo natural de escribir y es lo que ofrece el teclado del celular. Un campo numérico libre traduce; no corrige al usuario.
- **Una CI que siempre falla no dice nada.** `ruff check`/`ruff format` llevaban días en rojo en `dev` por archivos que nadie estaba tocando, así que todo PR salía rojo y la señal ya no significaba nada. Arreglarlo costó media hora; lo caro fue el tiempo en que dejó de servir. Y un archivo no se formatea porque sí: la tabla de `seed_contratos.py` está alineada a mano a propósito y va entre `# fmt: off`.
- **El stemmer del español normaliza las tildes pero NO la eñe.** Anoté "falta `unaccent` para las tildes" y al medirlo era al revés: `to_tsvector('spanish','José')` da `jos` —"jose" ya encontraba a José— pero `Muñoz` queda `muñoz`. Sobre apellidos colombianos corrientes fallaban 8 de 11, los 8 por la eñe. **Un pendiente anotado con una causa supuesta es una hipótesis, no un hallazgo:** medirlo antes de escribir la solución cambió qué había que arreglar.
- **Un buscador que exige la palabra completa no parece un buscador roto: parece un umbral.** `plainto_tsquery` compara lexemas ENTEROS, así que "Mate" no encontraba a Mateo. El cliente lo reportó como "solo filtra desde la quinta letra" — y tenía razón en el síntoma y no en la causa. Cuando alguien describe un comportamiento con un número, el número suele ser una coincidencia de sus datos.
- **Antedatar un documento que alguien firma hoy es un problema legal, no de UI.** Al hacer que el contrato sucesor heredara la fecha del original —que es lo correcto para el cobro de intereses— el impreso quedaba fechado semanas atrás sin explicación. La trazabilidad no fue un extra del cambio: fue su condición.
- **Ni un aporte del dueño es un ingreso, ni un retiro es un gasto.** Cuarta vez que aparece la misma familia de error ("prestar no es un gasto, cobrar no es una ganancia"). Lo que la salvó fue que el estado de resultados lee DOCUMENTOS y no movimientos de caja: un documento nuevo queda fuera del resultado por construcción, sin exclusiones que alguien pueda olvidar.
- **Un código de error es un contrato entre dos capas, y nadie lo compila.** El backend devolvía `NOT_FOUND` donde el front escuchaba `CASH_SESSION_NOT_OPEN`. Ni el tipado ni los tests lo vieron: el test que cubría ese endpoint verificaba el status y no el código, así que no cubría nada. Le costó once días de trabajo a una empresa.
- **Una rama de UI que nunca se ha visto no está escrita, está pendiente.** El banner tenía "Caja cerrada" con su botón y su aviso, bien redactados, desde hacía meses — y ningún usuario los vio jamás.
- **Un mensaje que dice "no puedes" sin decir "quién sí" es un callejón sin salida.** La persona no vuelve a intentarlo: deja de usar la función y reporta que la app no sirve.
- **Un token de un solo uso no puede viajar en una URL que alguien pueda pedir por GET.** Media internet abre los enlaces antes que el destinatario: las vistas previas de WhatsApp/Telegram/Slack y los escáneres de correo. Si el enlace tiene que sobrevivir a eso, el canje va por POST.
- **Un mensaje de error que sirve para todas las causas no sirve para ninguna.** "Intenta de nuevo" es el peor consejo posible cuando reintentar es imposible — y ese texto tapó durante días la causa real del bug de invitaciones.
- **Una configuración que se ignora en silencio es peor que una que falla.** Supabase descarta un `redirect_to` no permitido sin decir nada y sigue con otro destino; el síntoma aparece tres pasos después, en una pantalla que no tiene nada que ver.
- **Que el flujo funcione cuando lo pruebas TÚ no significa que funcione.** La diferencia estaba en cómo llegaba el enlace hasta la persona, no en el código — y ninguna cantidad de reproducciones limpias lo iba a mostrar.
- **Un nodo atómico insertado solo, sin nada después, deja una selección sin cursor visible** (ProseMirror `NodeSelection`) — y la siguiente inserción la reemplaza en vez de agregarse al lado. Cualquier "insertar X" sobre un nodo atómico (Tiptap) necesita un texto/nodo después para que el cursor quede colapsado y disponible para seguir escribiendo.
- **Un `limit 1` sobre un conjunto que puede tener más de un elemento es una suposición, no una consulta.** Ya costó tres veces: el índice de `00024` que "aseguraba" una sola cuenta de efectivo, el `GET /cashbox/sessions?limit=1` que devolvía la sesión más VIEJA creyendo que era la más nueva, y `get_active_register` tomando la registradora más antigua en silencio. Cuando el conjunto deba tener un solo elemento, la consulta los trae todos y **el servicio rechaza si hay más**: fallar fuerte convierte un dato silenciosamente equivocado en un mensaje.
- **La regla de "hoy es la fecha de la EMPRESA" vale también dentro de los tests.** Un `current_date` en un fixture es la misma ventana de 5 horas con otra ropa: un test que envejecía una sesión con `current_date - 1` pasaba de día y fallaba de noche, porque la sesión se había creado con el "hoy" de Bogotá y la resta se hacía contra el UTC del servidor.
- **Un campo no guarda lo que muestra.** `MoneyInput` enmascara `"1.000.000"` en pantalla y guarda `"1000000.00"`; un cálculo escrito contra lo que se ve salió 100× por encima, y los tests lo bendijeron porque sus fixtures copiaban la pantalla. Antes de usar el valor de un campo, leer qué emite el componente — su docstring lo decía.
- **Un fixture inventado no falla: bendice.** Dos veces en la misma sesión — `max_ltv_pct` como número cuando la API manda `"30.00"`, y montos enmascarados cuando el formulario guarda decimales. Las dos veces los tests pasaron en verde sobre un cálculo equivocado, y las dos veces lo cazó una comprobación contra lo real. **Los fixtures se copian de una respuesta real, no se escriben de memoria** — ya estaba escrito, y volvió a pasar.
- **Un permiso que se otorgó a todos no protege a nadie todavía.** `00051` dio `contracts.override_ltv` a todo rol que pudiera crear contratos, para que nadie perdiera acceso. Consecuencia: la rama de UI que dice "no puedes, pídeselo a alguien" **no la ve nadie** hasta que una empresa apriete el rol. Antes de construir sobre un permiso, comprobar quién lo tiene de verdad.
- **Una preparación se hace mientras el dato todavía es deducible, no cuando se necesita.** Ligar cada cajón a su registradora es un `update` de cuatro líneas mientras hay una de cada una; con dos de cualquiera, deja de tener respuesta correcta y se vuelve una decisión humana empresa por empresa. El costo de estas cosas no lo pone el volumen: lo pone el momento.
- **Un filtro por lista negra escrito a mano es un bug con fecha de vencimiento.** La consulta del job decía `not in ('paid','auctioned')` mientras la constante que la guarda usaba decía tres estados. El día que se agregó el tercero, la consulta siguió tomando lo que ya no debía y **nadie tenía que equivocarse para que fallara**: bastó con que alguien hiciera bien su trabajo en el otro archivo. Donde un criterio se aplica en dos capas, las dos leen la misma fuente. Y el test que lo cubre tiene que fallar también con una lista a mano **hoy completa** — si solo falla con la desactualizada, prueba los valores de este mes y no el invariante.
- **Un bug de datos rara vez tiene un solo vector.** F21-10 se escribió como "el job nocturno resucitaba contratos", y el job era apenas la mitad: `get_contract` también recalcula y **persiste** el status en cada lectura de detalle, así que un `GET` cualquiera hacía el mismo daño sin esperar a la medianoche. Arreglar la Machine y darlo por cerrado habría dejado la puerta abierta. Antes de cerrar un hallazgo, buscar **todos** los lugares que escriben el dato dañado, no solo el que se encontró primero.
- **Una invariante que nadie vigila sobre datos vivos es invisible por definición.** Once días de cartera inflada y un contrato sustituido a punto de salir a remate, sin una sola alerta — y la suite en verde todo el tiempo, porque un test contra base efímera no puede ver lo que le pasó a la producción. Cuando una regla vale sobre datos reales y no solo sobre código, su lugar es un script que sale con código 1, no un test.
- **Un job que no escribe en la auditoría no deja rastro forense.** No se pudo saber cuál de los dos vectores dañó cada fila porque `app/jobs/nightly.py` no audita nada. Un proceso automático que modifica datos de negocio necesita dejar dicho qué tocó, o el día del incidente solo quedan conjeturas.
- **Deshacer una operación es deshacer sus EFECTOS, no su registro.** Reabrir una caja borraba el acta y
  dejaba vivo el movimiento que el cierre había emitido sobre el saldo. Nadie lo notaba porque la pantalla
  que uno mira al reabrir es el acta, y el acta quedaba impecable. Antes de dar por hecho que una operación
  es reversible, listar **todo** lo que escribió, no solo la fila que la representa.
- **Una etiqueta que falta no solo se ve fea: esconde el filtro.** Los filtros de la auditoría se arman con
  las claves del mapa de etiquetas, así que dos módulos sin traducir eran dos módulos por los que no se
  podía filtrar. Un catálogo de presentación que además decide qué existe en la UI no es cosmético.
- **Un guardián escrito con un regex de literales no puede ver el caso dinámico.** El test que vigila que
  toda acción auditada tenga etiqueta busca `action="..."` en el código; el único lugar de todo el backend
  que escribe `action=direction` le fue invisible por construcción. Cuando un guardián lee código en vez de
  datos, hay que preguntarse qué forma de escribir lo mismo no está cubriendo.
- **Un arreglo propuesto en un informe es una hipótesis, igual que una causa.** «Netear las devoluciones en
  el agregador» sonaba obvio y era imposible: la mitad del valor devuelto no pasa por caja, así que habría
  producido una cuarta definición de ingreso. **Se mide antes de implementar, no solo antes de diagnosticar.**
- **Un fixture al que le falta un permiso es un invariante sin probar.** `test_cash_balance.py` existe para
  vigilar que el cajón valga lo que se contó, y su fixture no tenía `cashbox.reopen` — así que el camino por
  el que ese invariante se rompía era justo el único que el archivo no podía recorrer.
- **Una barrera de solo-lectura que el pooler ignora no es una barrera.** `PGOPTIONS` con
  `default_transaction_read_only` no llega a Supavisor en modo transacción: la variable dice `off` y un
  `UPDATE` pasa. Sobre datos reales, la protección tiene que ser algo que falle fuerte si no está —
  `BEGIN TRANSACTION READ ONLY`—, no una opción que se descarta en silencio.
- **Una cita con número de línea envejece sola, y el que la lee no tiene forma de saberlo.** Tres hallazgos
  de la auditoría apuntaban a líneas donde hoy vive otro código, movidas por arreglos posteriores. Quien
  siguiera la cita habría leído la función equivocada y sacado la conclusión equivocada.
- **Una máquina sin process group parece basura.** La Machine del job nocturno ya fue borrada una vez por "huérfana", y ese borrado dejó las suscripciones sin expirar nunca. Sigue igual. Lo que no se puede distinguir de un descuido, tarde o temprano alguien lo limpia.

