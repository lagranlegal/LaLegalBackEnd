# Continuar acá — 25/09/2026 · debajo, las sesiones del 25/09, 24/09, 23/09, 21/09, 20/09, 12/09 y 11/09

## 🟢 Sesión del 26/09 (tarde) — la landing pública de venta. ✅ PUBLICADA (`b7c579a`)

Pedido de Mateo: la página de venta en la raíz, pública, con diseño «brutal», paleta y metodología de la
app, animaciones y transiciones. Trabajado como orquestador (cuatro agentes: rutas, hoja de datos
verificada, implementación, documentación); diseño, revisión, ajuste del hero y docs de la raíz, míos.

| | |
|---|---|
| **Diseño** | Lienzo tipo Design en claude.ai (no hay conector de Figma en el entorno): <https://claude.ai/artifact/MbHqXJJBoKf1zjVjqqmaX5> — escritorio 1440, celular 390 y notas de movimiento. Privado hasta que Mateo lo comparta |
| **Rutas** `2b5df96` | `/` pública → `LandingPage`; el panel pasa a **`/inicio`**. `postLoginTarget`: tras entrar va a `/inicio` si no hay `redirect` o si es la raíz, y descarta destinos externos. Los correos no se afectan (solo enlazan a `/auth/callback` y `/baja/…`, verificado en `templates.py`) |
| **Landing** `c473bdd` + `7fab32a` | `src/features/landing/`: hero carbón con composición de producto, el problema, la cadena empeño→venta (se dibuja al hacer scroll), dos motores + una caja, bento, para quién, confianza, migración, CTA. Solo tokens (varios nuevos), Archivo + JetBrains Mono autoalojadas (el CSP no permite Google Fonts), claro y oscuro, `prefers-reduced-motion`. Con sesión, el nav dice «Ir a mi panel» |
| **Texto verificado contra el código** | Cambió 13 frases del primer borrador: la tasa no es por categoría, la app no imprime etiquetas, no hay botón de «cancelar total», no se afirma cumplimiento legal de las leyes 2300/1581. Cifras reales: 43 permisos, 4 roles, 12 avisos + 4 alertas + 2 resúmenes |

**Verificado por mí:** 357 tests, typecheck, lint sin errores nuevos; capturas en Chrome real a 360/768/1280/1440
en los dos temas, sin desborde. Encontré y corregí que la etiqueta del hero tapaba «Vigente» y el chip de
intereses tapaba la hora de cierre de la caja (`7fab32a`).

**Decisiones de Mateo (26/09), aplicadas en `b7c579a` y pusheadas:** canal = correo `contacto@prendo.com.co`
(no hay WhatsApp todavía; cuando lo haya, `DEMO_CONTACT` pasa a `https://wa.me/57…`); publicar = sí; Inter = sí
(`--font-sans` ahora nombra `'Inter Variable'`, medido en Chrome que carga). Backend `251d579` (solo docs) pusheado.

**Queda:**
1. 🔴 **Mateo: crear o redirigir el buzón `contacto@prendo.com.co`.** El dominio solo envía (Resend); el MX del apex
   apunta a `feedback.forge.rmta.net`, que no es un buzón de nadie. Probarlo mandándole un correo desde Gmail.
2. **Revisar las pantallas internas con Inter sobre lo servido** (sobre todo a 360 px): Inter es más ancha que la
   fuente del sistema y puede mover cortes de línea o columnas. No se pudo ver en local (CORS del backend dev).
3. Compartir el lienzo si otros lo van a revisar.

---

## 🟢 Lo primero (26/09)

**Todo lo de la sesión del 25/09 está desplegado en dev** y los dos guardianes en verde. Resumen en `ESTADO.md`
(la caja de arriba). Para retomar:

1. ✅ **Paso de recordatorios VERIFICADO (26/09, 11:51):** Mateo lanzó `flyctl machine start` → exit 0 en 13 s;
   registró R1 5, R2 2, R3 2, R4 1, resumen diario 5, remate 1, y **cero entregas** (todo apagado: correcto).
   Guardianes en verde. **Queda por medir la hipótesis de abajo** (un día sin deploys).
   Nota original: ⚠️ **26/09, 11:48: el job NO había
   corrido desde el 25/09** (último `company_daily_digest` = 25/09). **Hipótesis sin medir:** cada deploy hace
   `machine update` (hubo a las 00:26 y 11:44 del 26/09) y eso podría reiniciar el reloj del `--schedule daily` de
   Fly, así que deploys seguidos correrían el job. Cómo medirla: un día sin deploys, ver si `max(occurred_on)` del
   resumen avanza. Si se confirma, `deploy_dev.sh` debería lanzar una corrida (`flyctl machine start <id>`) al
   terminar. El clasificador me bloqueó `flyctl machine start`: se lo pedí a Mateo. Consulta:
   `select event_type, max(occurred_on), count(*) from notification_event where event_type in
   ('installment_due_soon','installment_overdue','extension_started','extension_ending_soon') group by 1;`
   Primera noche: registra sin entregas (todo apagado). Y el guardián del job.
2. ✅ **Prueba real de las alertas HECHA (26/09, 00:30):** rol temporal «QA Alertas» solo con
   `notifications.receive_alerts` asignado a `<alias de correo de prueba del dueño>` (NO se tocó Bodega: lo comparte
   `qa.bodega@qalab.com`, inventado); encendida solo `alert_sale_voided`; `qa.admin` anuló la venta Nº 10 → alerta
   **`sent`** solo al alias (el autor queda excluido). Revertido: interruptor apagado, alias de vuelta en Bodega,
   el rol quedó vacío y renombrado «QA Alertas (temporal, sin uso)» (la API no desactiva roles).
   **El job de la noche del 26/09 todavía no corrió** cuando se miró (Machine actualizada 00:26 por el deploy):
   verificar el paso de recordatorios la próxima vez.
3. **Ver los impresos nuevos con datos reales** (comprobante y contrato de LA GRAN LEGAL), solo mirando.
4. Pendientes de Mateo: ver `ESTADO.md`.
5. ✅ **Desplegado** (26/09, 00:26, Mateo; guardianes en verde): `3945253` (R1 solo 3 días antes, decisión de
   Mateo 25/09). Backend **784 passed, 0 skipped**, verificado por mí. Sin cambios de front.
6. ✅ **Reprogramación HECHA** (`44408b1`, pusheado; el agente murió por el límite de sesión DESPUÉS de commitear y
   yo verifiqué: **796 passed, 0 skipped**, ruff y mypy limpios). Un R1–R4 frenado por el tope (semanal o diario)
   vuelve a `pending` —la MISMA entrega— con `scheduled_at` en el primer momento que permiten el tope y la hora
   hábil, y `deferred_at` puesto; no cuenta como intento. Queda `throttled` solo si ya no diría la verdad (R1/R4
   valen hasta la fecha que anuncian; R2/R3 mientras el hecho siga). Al enviarla re-verifica el hecho con el mismo
   planificador del job: si el cliente pagó, `suppressed`. §20.6.
   ✅ **26/09: Mateo aplicó 00060 y desplegó**; verificado por mí: columna `deferred_at` en dev, Machine con la imagen
   al día, guardianes en verde. El job del 26/09 aún no había corrido (sin resumen con fecha 26).
   ~~Migración 00060 (aditiva) SIN APLICAR en dev:~~ el clasificador bloqueó `supabase db push` (el 25/09 había
   pasado). Orden para Mateo: `supabase db push --linked` → `./scripts/deploy_dev.sh` (el script frena si hay
   migraciones pendientes).
   ~~Contexto original:~~ con R1 3 días antes y el tope de 1 por semana, el aviso de MORA (R2) del día
   del vencimiento queda `throttled` y, como R2 sale una vez por ancla, **se pierde** (no se corre). Recomiendo
   que un recordatorio frenado por el tope semanal se **reprograme** al primer momento permitido en vez de
   perderse (NOTIFICACIONES §20.4).

**Anotado, sin hacer (decisión o no urgente):** alerta de descuadre de arqueo (quinto tipo, decisión de
producto); webhook de Resend (`delivered`/`bounced` → `email_invalid_at`); correo certificado para el aviso de
remate; verificar en Gmail que aparece «Anular suscripción» (exige un aviso al cliente encendido); el mensaje de
`SALE_PAID_WITH_CREDIT_NOTE` podría simplificarse (ahora toda devolución liquida bien, F21-37); firmas que saltan
solas a la última hoja en plantillas largas; el rango sin cierres pero con banco muestra «No hay cierres».

> Reglas que siguen valiendo: el deploy lo corre Mateo (`./scripts/deploy_dev.sh`); **si toca el front y el
> backend, backend primero**; la Machine `nightly-job` NO se destruye (`flyctl machine update`, lo imprime el
> guardián); lecturas a dev con `BEGIN TRANSACTION READ ONLY` explícito.

---

## Sesión del 25/09 (noche, 3) — impresión, contratos y mejoras chicas. ✅ DESPLEGADO

Tres agentes en paralelo. **Verificado por mí:** backend **781 passed, 0 skipped**; front **344**, typecheck y build limpios.

| | |
|---|---|
| **Impresión** front `579f7f9` | `PrintLayout` va por portal a `<body>`: el comprobante de venta imprime SOLO el comprobante (antes salía la lista con el botón de Excel). Membrete de marca con tokens `--paper-*` (papel blanco aunque la app esté en oscuro). Contrato con secciones, filas y firmas que no se parten, firma transparente o con fondo blanco bien apoyada (`mix-blend-multiply`). Cambios visibles: «Impreso el …», nombre y documento bajo la firma del cliente, títulos de sección |
| **Contratos** backend `024a03c`+`2e03fda` · front `aca7e4c` | `GET /contracts/{id}/chain` + panel con la cadena de ampliaciones y enlaces. **F21-38:** un sucesor sin margen ocultaba el formulario de ampliar aun con `override_ltv` (el backend sí lo acepta). La ventana contada desde el contrato ORIGINAL es diseño (RECARGOS §3) y ahora el mensaje lo explica. Casilla de autorización de avisos al crear el contrato (`customer_email`, `customer_email_consent`, origen `contract_form`, misma transacción) |
| **Mejoras chicas** backend `9514a43`+`dfb24d1`+`941869d` · front `4d46296`+`4214278` | F21-05 «Volver al documento de fábrica»; `List-Unsubscribe` + One-Click (RFC 8058) en correos al cliente; límite de tasa en memoria del enlace público (60/min por IP, 10/10 min por token; por máquina); E2 del resumen con la guarda de R3 |

✅ **DESPLEGADO** (25/09): backend por Mateo, guardianes en verde, front `aca7e4c` servido. Verificado en vivo
(solo lectura) el contrato #9 de ZZ QA: «fue ampliado el 11/09/2026 … la deuda pasó al contrato #10», botón «Ir al
contrato #10» e «Historia de este préstamo».

---

## Sesión del 25/09 (noche, 2) — Fase 5: recordatorios R1–R4. ✅ DESPLEGADA (API con `reminders`, Machine al día, guardianes en verde)

Backend `88cf5c5`+`6641f09`: paso nuevo del job nocturno (son 5). R1 cuota por vencer (3 días antes y el día),
R2 vencida, R3 entró en prórroga, R4 la prórroga vence pronto (3 días antes). **Un correo por cliente y día y
tipo** (la llave es por cliente, no por contrato: §2.3 le ganó a §6.1). Límites de la Ley 2300 activos. Todo
apagado por defecto. §12.3 CERRADA con la decisión legal de Mateo; §9.2-i; §20. **Verificado por mí: 760 passed,
0 skipped.** Sin migración.

**Deploy:** `./scripts/deploy_dev.sh` (tiene que actualizar la Machine `nightly-job`, o el paso nuevo no corre).
Verificar de solo lectura: `max(occurred_on)` de los eventos R1–R4 en `notification_event` a la mañana siguiente.

**Decisión pendiente de Mateo:** con los días de fábrica (3 y 0) y el tope de 1 por semana de la Ley 2300, el
aviso del DÍA del vencimiento queda `throttled` casi siempre. Opciones: dejar solo 3 días antes (`[3]`), solo el
día (`[0]`), o aceptar que el del día casi nunca salga.

---

## Sesión del 25/09 (noche) — Fase 7: alertas inmediatas A1–A4. ✅ DESPLEGADA

| | |
|---|---|
| **Backend** `08af01f`+`001b644` | Anular venta (A1), descuento > umbral en venta o abono (A2; umbral 0 = todos), retiro del dueño (A3) y reabrir caja (A4) generan alerta a los usuarios ACTIVOS con `notifications.receive_alerts`, **menos quien hizo el acto**. Inmediata, sin ventana horaria ni Ley 2300. El resumen sigue listando todo. `GET /notifications/settings` suma `alert_recipients`. §19 |
| **Front** `ca69c6b`+`0353d25` | La pantalla dice qué disparan las alertas y quién las recibe; la nota de «Avisos al cliente» ya no dice que no existe base legal |

**Verificado por mí:** backend **730 passed, 0 skipped**; front **289**. Empresas con el interruptor encendido en
dev: **0 de 7**, así que el deploy no le manda alertas a nadie sin que lo enciendan.

✅ **DESPLEGADO** (25/09): backend por Mateo, guardianes en verde, front `0353d25` servido. **Prueba real
pendiente:** en ZZ QA el único con `receive_alerts` es `qa.admin@qalab.com` (correo inventado) y quien actúa no
recibe; hace falta que Mateo active `<alias de correo de prueba del dueño>` (la invitación) para darle el permiso.

**Decisión legal de Mateo (25/09):** «tal cual lo recomiendas». Ley 2300 = todo recordatorio de pago (R1–R4)
es cobranza y cumple los límites (ya son los de fábrica); comprobantes no. R3 informativo. R5 aviso de cortesía,
la notificación formal es la del contrato; correo certificado (4-72, Certicámara) como mejora futura. Lo que más
protege: **cláusula de autorización de avisos en el contrato** + política de datos (Ley 1581) → el front la ofrece
como ejemplo insertable (pedido de Mateo: las empresas no lo saben). Dos agentes lanzados: fase 5 (backend) y
la cláusula (front).

✅ **Cláusula de avisos DESPLEGADA** (front `bd62cb5`, servido): nodo TipTap propio `noticeConsentClause`
(detección por nodo, no por texto), recuadro + botón «Insertar cláusula de avisos» en el editor de CONTRATO
(se inserta antes de la primera firma), incluida en el formato de arranque y en el impreso de fábrica
(`ContractPrintView`), y estado hecho/pendiente en Notificaciones. Campo nuevo `cliente.correo`. 312 tests.
**LA GRAN LEGAL tiene plantilla propia activa → su contrato impreso NO cambió**; le aparece «pendiente» en
Notificaciones. Texto = BORRADOR para revisión legal (`src/lib/documents/noticeConsentClause.ts`).

~~Orden original:~~ Mateo corre `./scripts/deploy_dev.sh` → recién ahí push del front (lee `alert_recipients`; contra el
backend viejo rompería la sección de eventos) → prueba real en ZZ QA.

**Anotado sin hacer:** no hay alerta de descuadre de arqueo (sería un quinto tipo, con migración: decisión de
producto); si el único con el permiso es quien actúa, la alerta no sale (queda en `audit_log` y en el resumen).

---

## Sesión del 25/09 (tarde) — plantillas nuevas + fases 4 y 6 + F21-36/37. ✅ DESPLEGADO

| | |
|---|---|
| **Plantillas** `56e3987` | Los correos del backend usan el molde de `frontend-starter/docs/correo-invitacion.html` (pedido de Mateo). Avisos al cliente con la marca de la EMPRESA, «Enviado por Prendo en nombre de X». §8.1 |
| **Fases 4 y 6** `8171f6c`+`404b799` | Contrato creado, abono (o paz y salvo en su lugar), ampliación, venta con cliente, anulación/devolución (o nota crédito) generan su aviso en la transacción y lo mandan al commit. Importar contrato no avisa. Comprobantes fuera del tope SEMANAL de la Ley 2300 (`transactional_in_weekly_cap=false`, parámetro), pero sí dentro del horario y del tope diario de 3. Todo apagado por defecto. §18 |

**Verificado por mí:** suite completa **656 passed, 0 skipped**.

✅ **F21-36 CERRADO** (backend `929fc01`, front `22cbf3e`, pusheados; el backend **falta desplegar**): anular
una venta con nota crédito redimida → `409 SALE_PAID_WITH_CREDIT_NOTE`. Suites: **659** backend, **278** front.
Los dos guardianes estaban en verde tras el deploy de fases 4 y 6.

✅ **Prueba real de la fase 6 (25/09, por mí, en ZZ QA):** eventos de empresa apagados (correos de mentira) +
`sale_receipt` encendido + interruptor encendido; cliente «Mateo Prueba Correo» (`<alias de correo de prueba del dueño>`,
`email_consent` → base `consent`); venta Nº 10 de $90.000 en efectivo (artículo JOA0003-02P) → entrega **`sent`**
al primer intento. **Interruptor de ZZ QA vuelto a apagar**; quedaron los overrides (empresa apagada,
`sale_receipt` encendido). Mateo confirma en Gmail cómo se ve.

✅ **F21-37 CERRADO** (backend `3221d20` pusheado; front `2282103` **SIN PUSHEAR hasta el deploy**): la
devolución de una venta pagada con nota parte la liquidación, proporcional a cómo se pagó, sobre el acumulado
(mismo telescopio de F21-33). $800.000 = nota $500.000 + efectivo $300.000, devuelta en efectivo → salen $300.000
y nace una nota de $500.000. Suites: **680** backend, **284** front. **Desplegado** (25/09): backend por Mateo, guardianes
en verde; front pusheado y servido por Vercel.

~~Descripción original de F21-37:~~ una DEVOLUCIÓN liquidada en efectivo sobre una venta pagada con nota
saca del cajón el total (mismo ejemplo: salen $800.000 con $300.000 entrados). Y liquidada en nota, convierte
en nota también la parte que se pagó en efectivo. Medido en dev: **1 devolución** sobre venta con nota, liquidada
en nota (sin plata perdida). Falta decidir: rechazar el efectivo por encima de lo cobrado en plata, o partir la
liquidación entre nota y efectivo.

~~Descripción original de F21-36:~~ anular una venta pagada en parte con nota crédito devuelve el
TOTAL en efectivo y la nota sigue redimida (`sales/service.py`, `refunded = total`). Reproducido en local por el
agente ($800.000 = $500.000 nota + $300.000 efectivo → salen $800.000 del cajón). **Medido en dev (solo
lectura): 0 casos**, no hay daño. Falta decisión de Mateo: rechazar la anulación (como `SALE_HAS_RETURNS`) o
devolver la nota.

**Falta:** Mateo corre `./scripts/deploy_dev.sh` (lleva plantillas + fases 4 y 6); probar en una empresa `ZZ` con un
cliente de correo `<alias de correo de prueba del dueño>`; la pantalla de Notificaciones no muestra el parámetro nuevo.

---

## Sesión del 25/09 — Fase 3 (base legal del cliente) + F21-34 + F21-35. ✅ DESPLEGADO

Dos agentes en paralelo; revisión, suites completas, migración y push centralizados.

| | |
|---|---|
| **Fase 3** backend `da76b63`+`a449fd0` · front `2f022dd`+`35b1280` | `customer.email_basis` (`contract`/`consent`), autorización del mostrador en la ficha del cliente, baja por enlace firmado (`/baja/{token}`: el GET solo muestra, la baja es POST), `notification_delivery.legal_basis`. Detalle: `NOTIFICACIONES.md` §17 |
| **F21-34** `7f09ba1` · front `3e12813` | Reabrir una caja ya abierta → `409 CASH_SESSION_NOT_CLOSED` con mensaje propio |
| **F21-35** `e9e8756` | El desglose de cierres usa LEFT JOIN: un movimiento de banco sin caja abierta entra por su día. Suma exactamente 2 movimientos ($60.000 desembolso + $5.000.000 aporte del dueño). Medido en dev solo lectura |

**Verificado por mí:** backend **585 passed, 0 skipped**; front **275**, typecheck y build limpios.

**Migración 00059 APLICADA en dev** (25/09, `supabase db push --linked`, era la única pendiente). Medido antes, en
solo lectura: el backfill toca **2 clientes** (los únicos con correo de los 16; ninguno de laboratorio) → quedan
con `email_basis='contract'`. **No pude verificar el después**: el clasificador bloqueó la lectura. Mateo:

```
psql "$URL" -c "begin transaction read only; select email_basis, count(*) from public.customer group by 1; rollback;"
```
(esperado: `contract | 2`, `null | 14`).

> ✅ **25/09, más tarde: DESPLEGADO todo.** Mateo cargó `NOTIFICATIONS_LINK_SECRET`, corrió `deploy_dev.sh`
> y el `machine update` que el guardián pidió (el script no alcanzó a actualizar la Machine: **octava vez**).
> Verificado por mí: API con 99 rutas y `/public/unsubscribe/{token}`; los dos guardianes en **verde**; 00059
> en dev = `contract 2 / null 14`, lo esperado; front `35b1280` pusheado y **servido** por Vercel; `/baja/<inválido>`
> a 360 y 1280 sin desborde; ficha del cliente a 1280 con «Avisos: Sin correo». Sin errores de página ni
> mutaciones. **Falta:** la ficha a 360 px (el script no encontró la fila en móvil) y la **invitación real**
> de prueba en una empresa `ZZ` (hace falta un buzón que Mateo elija).
> ⚠️ `machine update --image` no copia secrets: comprobar que la Machine del job tiene `NOTIFICATIONS_LINK_SECRET`
> antes de encender cualquier aviso al cliente (hoy ninguno lo está).

**Pasos que faltaban (ya hechos, se dejan como registro):**
1. `fly secrets set NOTIFICATIONS_LINK_SECRET=$(openssl rand -hex 32) --app compraventa-backend-dev --stage`
   (el deploy lo lleva también a la Machine del job). Sin él, un correo al cliente queda `dead`, pero hoy
   ninguno está encendido.
2. `./scripts/deploy_dev.sh` en `backend-starter`: despliega fases 2 y 3 + F21-34/35 y actualiza el job.
3. **Recién ahí** pushear el front: `cd frontend-starter && git push origin dev`. **No antes:** el formulario
   de cliente ya manda los campos nuevos y la página `/baja` llama a un endpoint que el backend viejo no tiene.
4. Invitación de prueba en una empresa `ZZ` (fase 2) y ver la ficha de un cliente a 360/1280 (la ficha no se
   vio en navegador: el Auth local no tiene el hook de claims).

**Anotado sin hacer:** la casilla de autorización quedó en la ficha del cliente (origen `counter`), no al crear
el contrato como dice §9.2-f; sin cabeceras `List-Unsubscribe` ni límite de tasa en el endpoint público; nadie
escribe `email_invalid_at` (falta el webhook de Resend); el texto de la casilla es de producto, no legal.

---

## Sesión del 24/09 (noche) — Fase 2: la invitación sale por nuestro correo

Trabajado con **dos agentes en paralelo** (uno por repo); revisión, push y docs de la raíz, centralizados.

| | |
|---|---|
| **Backend** `fbf7b8a` + `3c45142` | La invitación (P1) se pide a Supabase con `generate_link` (sin correo) y sale por Resend: evento `user_invitation` + entrega en la misma transacción, envío inmediato con `BackgroundTasks`, el job como red. El correo lleva `{FRONTEND_URL}/auth/callback?token_hash=…&type=invite` (canje por POST). Sin `RESEND_API_KEY` o `FRONTEND_URL` → vuelve al correo de Supabase (`invite_delivery: "email_supabase"`). El interruptor de la empresa **no** la bloquea (audience `platform`). **545 passed, 0 skipped**, sin migración. Detalle: `NOTIFICACIONES.md` §16 |
| **Front** `cf1285a` | El canje del enlace espera un clic en «Continuar» (un escáner que ejecute la página ya no lo quema); red/5xx/429 ofrece reintentar; «ya se usó o venció». **También agrega el clic a «Generar enlace»**: decisión pendiente de Mateo si lo quiere solo para el correo. 255 tests |

**Verificado por mí, no solo reportado:** suite completa corrida; el hallazgo de que FastAPI 0.141 corre las
`BackgroundTasks` **antes** del commit de `get_db` (por eso `send_after_commit` commitea explícito) se midió
quitando ese commit: fallan 8 de 13 tests de invitación. `FRONTEND_URL` y `RESEND_API_KEY` ya están en el API.

**Pendiente — lo corre Mateo:** `./scripts/deploy_dev.sh` en `backend-starter` (el clasificador bloquea
`machine update`). Después: invitar a una persona de prueba **en una empresa `ZZ`** y ver llegar el correo real
(Gmail y Outlook), y comprobar en «Correos recientes» que la entrega quedó `sent`. Sin verificar contra el
proyecto hosted: si `generate_link` tiene límite propio y cuánto dura el token.

---

## Sesión del 24/09 — cinco defectos cerrados, uno nuevo de plata cerrado el mismo día

Trabajado con **agentes en paralelo, uno por repo**, y revisión + push + deploy centralizados.

| | |
|---|---|
| **Push del front** `938a3aa` | Hecho y verificado en el bundle servido |
| **F21-32 verificado sobre lo servido** | `scripts/qa/verificar_f21_32.py` (aborta si la empresa no es `ZZ`). Tres cierres con reapertura en `ZZ QA`: el cajón vale lo contado cada vez; sin el fix habría quedado 757.000 con acta de −5.000. Laboratorio devuelto a su estado |
| **F21-14** `1e6b422` | Tarjeta «Descuadres de caja al cierre» en Reportes. Sin «cierres sin motivo» (el backend lo impide: sería siempre 0). No incluye el descuadre de APERTURA (vive solo en `audit_log`) |
| **F21-17 + «Nota crédito redimida»** `c8ee9f0` · front `1d3b203` | `SaleOut.returned_amount` y columna «Devuelto» en tabla y Excel. La columna de nota crédito ya no sale vacía |
| 🔴 **F21-33 (nuevo, plata)** `75ec5ce` | Una devolución sobre venta con descuento **pagaba el bruto**: 900.000 pagados → 1.000.000 devueltos. **Decisión de Mateo: se devuelve lo pagado.** Ahora liquidación, `returned_amount`, `/profit` y `/series` salen de **una sola** `return_line_amounts_sql`, prorrateo sobre el ACUMULADO (la devolución que agota la venta se lleva el residuo: nunca un centavo de más). De paso: una línea repetida en el body permitía devolver más de lo vendido, y `create_return`/`void_sale` ahora toman la venta `FOR UPDATE` |

**Desplegado** (backend en Fly, front en Vercel). Backend **452 passed, 0 skipped**; front **238**. Los dos
guardianes: cadenas en verde; job nocturno cazó la Machine desactualizada **dos veces** (sexta y séptima).

**Anotado sin arreglar:** reabrir una caja ya abierta da `CONFLICT` genérico, sin código de negocio; los
movimientos contra cuentas `bank` quedan fuera del INNER JOIN de `closings-breakdown` (2 mov., $5.060.000).

---

## Lo primero del 23/09 (ya resuelto el 24/09)

**1. Pushear el front.** Quedó un commit sin pushear (`938a3aa`, los nueve defectos de UI): el clasificador
bloqueó el `git push` y no es determinista — el del backend en la misma sesión sí pasó. El comando:

```
cd /Users/mateojaramillo/projects/compraventa_app/frontend-starter && git push origin dev
```

**2. Verificar el COMPORTAMIENTO de F21-32 sobre lo servido.** El backend está desplegado y los dos
guardianes en verde, pero **solo se verificó que el deploy llegó**, no que la app servida ya no descuadre.
Probarlo exige abrir, cerrar y reabrir una caja, y en dev hay datos reales bajo Ley 1581 — va contra una
empresa `ZZ` de laboratorio, no contra LA GRAN LEGAL. *El deploy no es la prueba.*

**3. Decirle a Mateo lo del cajón de LA GRAN LEGAL** (abajo).

> **Del deploy del 23/09 quedó confirmado, por quinta vez:** `fly deploy` **no** actualiza la Machine del
> job nocturno. El guardián la cazó desactualizada y hubo que hacer `flyctl machine update` a mano, y
> después **volver a correr el guardián** para comprobar que el `schedule` sobrevivió. No es una anécdota:
> es el paso que falta en todo despliegue de este proyecto.

**Lo que espera a Mateo y no es código:** el cajón de **LA GRAN LEGAL reporta −$1.108.000**. Un cajón no
puede estar en negativo. No es un bug: su `opening_balance` es **0** y se desembolsaron $1.600.000 en
cuatro préstamos — **nunca registraron el efectivo con el que abrieron**. Se arregla contándolo y abriendo
la caja con el conteo real, no tocando la base. Hay que decírselo.

---

## Sesión del 23/09 (tarde) — once defectos cerrados y uno nuevo de plata

Se atacó la serie F20-xx / F21-xx que quedaba abierta, en **tres frentes paralelos**: códigos de error,
etiquetas/UX, y una medición en solo lectura de los cinco defectos de reportes. Registro completo, con los
números, en `backend-starter/docs/QA_AUDITORIA.md`; el detalle del front, en
`frontend-starter/docs/IMPLEMENTATION.md`.

**Lo que más valió no fue arreglar: fue medir.** Tres hallazgos estaban **mal descritos** (F21-02, F21-05 y
F21-09), dos arreglos propuestos resultaron **imposibles o dañinos**, y el defecto más grave del día **no
estaba en ninguna lista**.

### 🔴 F21-32 — reabrir y recerrar una caja descuadraba el cajón (CERRADO, sin desplegar)

`reopen_session` limpiaba el acta pero **no revertía el `adjustment` que el cierre había emitido**. Y como
ese ajuste vive con `session_id = NULL` —a propósito—, `_expected_cash` no lo ve al recerrar: el segundo
cierre calculaba su diferencia como si el primero nunca hubiera existido y emitía otro encima. Los dos se
acumulaban sobre el saldo mientras el acta solo reportaba el último.

**Medido:** acta de −20.000 sobre un cajón desviado **+$2.700.100**, con cero movimientos de por medio.
Rompía el invariante que `00048` vino a establecer y que la regla 5 de `CLAUDE.md` recoge.

Tres tests, los tres vistos fallar; el segundo reproduce el bug exacto (**87.000 donde el acta dice
95.000**). **El fixture de `test_cash_balance.py` no tenía `cashbox.reopen`** — por eso el invariante nunca
se había probado del lado de la reapertura, aunque el archivo existiera justo para vigilarlo.

⚠️ **Los datos ya dañados de Empresa Demo Front (+$2.700.100) NO se repararon.** Es una empresa de prueba;
repararla es su propia decisión y su propio script.

### Cerrados

| | |
|---|---|
| **F20-01 · F20-02 · F20-03** | `errors.ts` catalogaba `ALREADY_CLOSED_TODAY`, una entrada **muerta desde que se escribió**. Y **F20-01 y F21-03 eran el mismo bug**: con el código sin tipar, toda rama que preguntara por «la caja de hoy ya se cerró» era **inalcanzable** |
| **F21-02** | Mal descrito: el front ya mostraba el texto del backend. El defecto real era que **es un toast** — se desvanece, no dice dónde está la acción ni a quién pedírsela |
| **F21-03 · F21-06 · F21-07** | Mensajes que tapaban al backend, y el nombre del proveedor de infraestructura que se le mostraba al usuario |
| **F21-04** | La cantidad de una línea de venta mentía |
| **F21-08** | Más grande de lo escrito: **una etiqueta que falta esconde el filtro**. No se podía filtrar la auditoría por capital ni por cuentas |
| **F21-09** | El backfill de `00051` le había dado `override_ltv` **y `extend_loan`** (que el hallazgo omitía) al rol Asesor. Aplicado y auditado sobre LA GRAN LEGAL |

### Los tres hallazgos que estaban mal descritos

1. **F21-02** — ver arriba. *Un hallazgo que sigue vivo puede haber cambiado de causa.*
2. **F21-05 estaba al revés.** No es una etiqueta huérfana: el backend **sí** emite
   `deactivate_document_template` por un camino real (existe desde F8-02, porque sin él no había vuelta al
   documento de fábrica). **Lo que falta es el botón.** Queda abierto como **feature, no como defecto**.
3. **F21-09 no era un defecto de diseño, sino una divergencia entre empresas viejas y nuevas** —
   `_ASESOR_CODES` nunca incluyó esos permisos, así que una empresa creada hoy no los recibe. Y **omitía el
   permiso más grave**: `extend_loan` no autoriza una excepción, **desembolsa más dinero**.

### Dos arreglos propuestos que resultaron imposibles, con número

- **F21-13 — netear las devoluciones en `aggregate.ts` no puede funcionar.** Una devolución pagada con
  **nota crédito no emite ningún `cash_movement`**: **2 de 5 devoluciones, el 51,8 % del valor devuelto**.
  Sería una **cuarta definición de ingreso**, justo lo que F21-12 evitó. Y la pantalla **ya muestra el neto
  dos veces**, a pocos píxeles del bruto, sin que nada diga que son definiciones distintas.
- **F21-18 — no es defecto.** Agrupar por `paid_at` daría un número **peor**: el backend guarda
  `paid_at = now()` y no la fecha real del pago, así que sería **F21-15 creado a propósito**.

### Lo barato que quedó identificado y no se hizo

- **F21-14 sale casi gratis:** el endpoint ya devuelve `difference` y `difference_reason` y
  `ReportesPage.tsx:340` **ya los tiene en memoria** — solo los usa para contar sesiones. El número llega y
  **se descarta**. Una función pura y una tarjeta; cero backend.
- **F21-15 → cero casos** en toda la base, y el nudo no es el SQL: **no existe una definición de «mes
  cerrado»**. Decisión de negocio.
- **F21-17** necesita tocar el endpoint (`_SALE_COLUMNS` no trae nada de devoluciones); la columna es
  `Devuelto` **en pesos**, reusando la expresión de `profit_summary`.
- **Bug de paso, sin número:** la columna «Nota crédito redimida» del Excel de Ventas está **siempre
  vacía** — `list_sales` llama a `_row_to_sale` sin ese parámetro, que tiene default `None`. **El mismo
  `LEFT JOIN LATERAL` que resuelve F21-17 la arregla de paso.**

### Dos trampas de método que conviene no re-descubrir

- 🔴 **`PGOPTIONS='-c default_transaction_read_only=on'` NO funciona contra Supavisor en modo transacción.**
  El pooler ignora las opciones de arranque: `show default_transaction_read_only` devuelve `off` y un
  `UPDATE` pasa como no-op sin que nada lo detenga. **La única barrera real es `BEGIN TRANSACTION READ ONLY`
  explícito.** Importa porque la dev remota tiene datos reales bajo Ley 1581.
- **Tres citas de `QA_AUDITORIA.md` apuntaban a líneas que ya se habían movido**, y se corrigieron. *Una
  cita con número de línea envejece sola, y el que la lee no tiene forma de saberlo.*

### Decisiones tomadas que quedan anotadas para no reabrirlas a ciegas

- **Las otras 6 empresas de dev** tienen la misma divergencia de permisos de F21-09. Son todas de prueba y
  quedaron fuera del alcance a propósito.
- **El rol Moderador también recibió `override_ltv` y `extend_loan`.** Por el criterio que el propio código
  escribe en `_MODERADOR_EXCLUDED_CODES` —excluido de todo lo que mueve plata y de toda excepción a una
  política comercial— **los dos deberían estar en esa lista y no están.** Es decisión de producto.
- **El script de F21-09 va acotado a un `role_id`, no al predicado**, y eso salvó dos decisiones del
  cliente: al comparar el después contra `_ASESOR_CODES` sobraba `contracts.edit` y faltaba `cashbox.view`,
  pero **no son del backfill** — el admin editó esa matriz a mano el 09/09. *El predicado es lo que hay que
  vigilar, no lo que se ejecuta a ciegas sobre datos reales.*

---

## Cómo retomar esto en una sesión nueva

Este archivo y `ESTADO.md` **son** el mecanismo de traspaso: una sesión nueva no hereda nada de la anterior,
así que lo que no esté escrito acá se perdió. Pegá esto y listo:

> Leé `ESTADO.md` y el primer bloque de `CONTINUAR.md` para ponerte al día. Estamos en el proyecto Prendo.
> El plan vivo es `frontend-starter/docs/PLAN_MARCA.md`, y el diseño de lo que sigue está en
> `backend-starter/docs/NOTIFICACIONES.md`.
>
> **El plan de marca está terminado.** Las cinco fases: marca al código ✅, kit ✅, guía de usuario ✅
> (ocho partes, publicada), dominio ✅ (`prendo.com.co` → `dev.prendo.com.co`, backend en
> `api-dev.prendo.com.co`) y correo ✅ (Resend verificado y conectado, plantillas aplicadas y verificadas
> contra crawlers).
>
> **Lo que sigue, en orden de valor:**
> 1. **Notificaciones de negocio (Fase 5b).** Es lo que Mateo preguntó explícitamente: hoy **crear un
>    contrato, una venta o un abono no le avisa a nadie**. El backend **no tiene módulo de correo** — cero
>    código. El diseño está completo en `NOTIFICACIONES.md` (13 secciones) y **empieza con siete preguntas
>    de negocio que solo Mateo puede contestar** (§12).
>    **Por dónde empezar, que está medido:** de 16 clientes en la base **2 tienen correo**, así que avisarle
>    al cliente no llega al 87 %. Pero **la empresa siempre tiene correo** (sus usuarios entran con él), así
>    que **los avisos al negocio se pueden construir ya** sin depender de nada.
> 2. **Los defectos abiertos** de `QA_AUDITORIA.md`, serie F21-xx. Ninguno de dinero: los tres que lo eran
>    (F21-10, F21-12 y F21-31) están cerrados.
> 3. **El ambiente de producción.** Mateo lo dejó **de último a propósito** (23/09). Sigue siendo el único
>    bloqueante real para venderle esto a un cliente, pero no es urgente hasta que haya uno.
>
> **Tres reglas duras de este proyecto, confirmadas a los golpes:**
> - **Lo que se documente se verifica contra el código**, no contra un informe intermedio ni contra lo que
>   ya estaba escrito. De ahí salieron 20 hallazgos en tres días.
> - **Guardar no es aplicar.** `git push` no despliega en Fly, `fly deploy` no actualiza la Machine del job,
>   republicar no mueve el pin, guardar una plantilla de Supabase no la aplica, y un workflow fuera de la
>   rama por defecto no corre. **Verificar el efecto sobre lo servido, nunca la pantalla de configuración.**
> - **Correr los dos guardianes después de cada deploy:** `scripts/qa/verificar_cadenas.py` y
>   `scripts/qa/verificar_job_nocturno.py`. El segundo cazó la Machine desactualizada **tres veces en un
>   día**, incluido el deploy de hoy.

**Qué se carga solo y qué no.** Los `CLAUDE.md` de cada repo y la memoria de
`~/.claude/projects/-Users-mateojaramillo-projects-compraventa-app/memory/` entran solos en cada sesión
nueva. **El historial de la conversación no.** Y `README.md`, `ESTADO.md`, `CONTINUAR.md` y `marca/`
**no están versionados** — viven solo en esta máquina, así que tampoco viajan a otra.

---

## Sesión del 22–23/09 — el correo, y diez defectos que salieron de verificar

### Fase 5 · El correo, cerrada

**Resend verificado y conectado a Supabase.** El correo de autenticación —invitación y recuperación— sale
del dominio propio y llega con el `token_hash` correcto.

**Lo que costó, y conviene no re-descubrir:**

- **La trampa del DMARC se disolvió.** Los documentos advertían dos veces que había que **reemplazar** el
  `p=quarantine` que GoDaddy auto-provisionó. **Ese registro ya no existe** — desapareció al reemplazar los
  registros del parking. Medido contra los dos NS autoritativos y dos resolvers públicos. *Una trampa
  anotada hace dos días puede haber dejado de existir: se mide antes de trabajar sobre ella.*
- **Resend no pidió lo que la documentación decía.** En vez de tres registros (TXT + TXT + MX con
  `amazonses.com`), pidió **dos**, y el del medio es un **CNAME** a `send.forge.rmta.net`. Es mejor: con un
  CNAME **Resend rota sus IPs sin que toquemos el DNS**; con el SPF a mano, cada cambio de su lado nos
  dejaría apuntando a IPs muertas **sin ninguna señal**.
- 🔴 **Guardar una plantilla de Supabase no la aplica: la cachea unos minutos.** Se guardaron las dos, llegó
  un correo con el enlace **viejo**, y el editor mostraba el cuerpo nuevo. Minutos después salía bien.
- **Y una trampa de método que costó el diagnóstico:** el `iat` del JWT que aparece cuando un enlace se
  quema es **cuándo se canjeó**, no cuándo se envió el correo. Un enlace vive hasta una hora, así que un
  `iat` reciente **no prueba** que el correo lo sea. Es fácil medir un correo viejo de la bandeja y culpar a
  la configuración. **Borrar los correos viejos antes de probar.**

**Lo que falta de la fase, y no bloquea nada:** publicar el **DMARC** (ahora es *publicar el primero*, no
reemplazar ninguno — empezando en `p=none` y con el `rua` a un buzón que alguien abra; ojo que **un Gmail
cualquiera no recibe reportes DMARC**, hace falta un agregador) y la **prueba de spam** en Gmail, Outlook y
un corporativo.

### Lo que se cerró de código

| | |
|---|---|
| **F21-12** · una devolución no bajaba el estado de resultados | Contra-ingreso en el período de la devolución. **El doble conteo se cerró por el lado del costo** — era un síntoma de no registrar la devolución, no un defecto aparte |
| **F21-31** · anular una venta con devoluciones duplicaba stock y plata | Medido: una unidad inventada y **500.000 de sobrepago**. Se rechaza con `SALE_HAS_RETURNS` |
| **F21-30** · el guardián diario nunca habría corrido | `schedule` solo funciona desde la **rama por defecto**, que era `main` (141 commits atrás). La rama por defecto pasó a `dev` |

**Por qué F21-31 rechaza en vez de anular la parte no devuelta:** no es que sea más trabajo — **el número no
existe**. El monto de una devolución se deriva del **bruto** y `sale.total` es **neto** del descuento, así
que restarlos da mal en cuanto hay descuento. Hacerlo bien exigiría **una cuarta definición del cálculo de
ingreso**, que es justo lo que F21-12 evitó.

### Los defectos menores, cerrados (23/09)

| | |
|---|---|
| **F21-25** · «Costo detenido» subestimaba | Los totales salían de la **página de 20**, no del universo. El dueño mira ese número para decidir si liquida mercancía parada, y decía menos de lo real. **No fallaba ni avisaba**: con pocos productos era correcto, así que aparecía solo al crecer |
| **F21-19** · el correo del cliente no se validaba en el backend | Vivía solo en el `zod` del front. Medido antes de tocar: 16 clientes, 2 con correo, **0 inválidos**. Se valida en la **entrada**, no en la salida — validar la salida haría que una fila vieja mal escrita diera 500 al **leer** la ficha |
| **F21-01** · «(Enter agrega)» | El más viejo de la serie. Ahora dice «(agrega con clic)» |
| **F21-16** · el botón de exportar desaparecía al buscar | Queda visible y **deshabilitado, con el motivo al lado** |
| **F21-26 · F21-27 · F21-29** | Dos comentarios que decían lo contrario del código, y un rótulo que decía «más de N días» con un filtro `>=` |

**Dos descartes que valen más que los arreglos**, y quedan anotados con su bloqueante para que no se
reabran a ciegas:

- **Hacer que Enter agregue de verdad** en el carrito parece una línea y no lo es: `SearchInput` **debouncea
  300 ms**, así que un cajero que escribe el código y remata con Enter agregaría **el artículo anterior a su
  última tecla**. *Un «Enter agrega» que agrega el equivocado es peor que el que no existe.*
- **Exportar el resultado del buscador de Contratos**: `useContractSearch` pide `limit=20` sin cursor, así
  que sería un Excel **recortado a 20 filas en silencio**. Peor que no entregarlo.

### Dos ironías que enseñan más que los arreglos

1. **El guardián contra fallas silenciosas fallaba en silencio** (F21-30). Verifiqué el script —las tres
   rutas de detección, los códigos de salida— pero **no verifiqué que el mecanismo que lo dispara
   existiera**. Lo encontró Mateo abriendo Actions.
2. **El verificador de enlaces filtraba el token que venía a proteger.** Imprimía el `redirect_url`
   completo, y ahí viaja el `access_token`. Pasó de verdad: quedó un JWT de super-admin en un chat.

---

## ✅ F21-10 — cerrado el 21/09 (era «lo primero de mañana»)

Al desplegar el backend el 21/09 apareció algo que nadie estaba buscando, y resultó tener datos dañados.

La Machine programada del **job nocturno** no se actualiza con `fly deploy` —ya estaba advertido en
`ARCHITECTURE.md`— y quedó clavada a su imagen del **08/09**. El **10/09** entró el commit del recargo, que
agregó `superseded` a los estados terminales. La consulta del job filtraba `status not in ('paid','auctioned')`
por lista negra escrita a mano, así que **sí tomaba** los `superseded`: lo único que los protegía era la
guarda de `compute_status`, justo lo que la imagen vieja no tenía.

**Se midió, y hubo daño: 4 contratos — el 100 % de las ampliaciones que existen.** No hubo ni una sana: la
función nació el 10/09 y el bug nació el mismo día, así que la hipótesis optimista ("si da cero, nadie la
usó") quedó descartada por el lado contrario. Uno solo es de un cliente real, el **Nº 28 de LA GRAN LEGAL**.
La cartera estaba inflada en **5.000.000 COP**, y contada **doble**, porque el sucesor también seguía vivo.
**El daño nunca llegó a plata**: ni un abono sobre los cuatro padres.

**Tenía una bomba con fecha.** El Nº 1 de Empresa Demo Front había quedado `in_extension` con prórroga al
16/10, o sea entrando **solo** a «Listos para remate» el **17/10** — un contrato ya sustituido, con sus
prendas en `transferred`, ofrecido para rematar. Desactivada.

**Qué quedó hecho:**

| | |
|---|---|
| **Los datos** | Los 4 reparados en una transacción, con sus 4 filas de `audit_log`. Script explicado en `backend-starter/scripts/qa/reparar_f21_10.sql`. La base local **no necesitaba** reparación (verificado, no supuesto) |
| **La causa** | Machine actualizada y **`schedule: daily` verificado que sobrevivió** — si se pierde, el job deja de correr y su ausencia es silenciosa |
| **El diseño** | `rules.TERMINAL_STATUSES` es pública y la consulta del job la consume. Agregar un estado terminal nuevo ahora **alcanza**: no hay un segundo lugar que tocar |
| **El guardián** | `scripts/qa/verificar_cadenas.py`, exit 1 si una cadena se rompe. Solo lectura, sin datos personales |
| **Verificación** | backend **425 passed** (Docker arriba, sin skips) · front **193** · lint, format y mypy limpios · guardián en verde contra las dos bases |

**Tres cosas que salieron de paso y no estaba buscando nadie:**

1. **El job no era el único vector.** `get_contract` (`service.py:474-499`) también recalcula y **persiste**
   el status en cada lectura de detalle: un `GET /contracts/{id}` cualquiera resucitaba un contrato
   reemplazado sin esperar a la medianoche, y la app servida venía sin la guarda hasta el deploy del 21/09.
   **No se puede saber cuál vector causó cada fila:** el job no escribe en `audit_log`, no dejó rastro.
2. 🔴 **`create_payment` (`service.py:643`) rechaza abonos solo con `paid`/`auctioned`, sin `superseded`.**
   O sea: **un contrato ya reemplazado por una ampliación todavía admitiría un abono.** No se tocó porque es
   semántica de negocio distinta a la del job, pero huele a defecto real y **ningún test lo cubre**.
   `service.py:1004` repite los tres a mano para el cupo de ampliación: hoy está completo, se desincronizará igual.
3. ⚠️ **La Machine `nightly-job` no tiene process group.** Es exactamente la característica por la que el
   27/08 alguien la borró creyéndola "máquina huérfana" — el borrado que dejó las suscripciones sin expirar
   nunca. Sigue indistinguible de basura a simple vista.

**Lo que queda abierto de F21-10:** poner el guardián en un **cron** (sin eso vigila solo cuando alguien se
acuerda, que es el problema original con otra ropa), y las **cuatro invariantes más** que quedaron propuestas
y medidas en `QA_AUDITORIA.md` §F21-10 — la más preocupante es la inversa: un `superseded` **sin** sucesor
sería plata prestada desaparecida del sistema si el recargo fallara a mitad.

**✅ Todo commiteado, pusheado y desplegado.** Los dos árboles limpios. De esta tanda (21→23/09) salieron
**20 commits en el backend** y **18 en el frontend**; `git log --oneline` los lista con su porqué en el
mensaje — los mensajes de este proyecto explican **por qué**, no solo qué, así que sirven de registro.

**Verde al cierre:** backend **444 passed** con Docker arriba y **sin skips** · `ruff`, `format` y `mypy`
limpios · front **193 passed**, typecheck limpio y 0 errores de lint (8 warnings preexistentes de React
Compiler). Los **dos guardianes en verde** contra la dev remota.

**Verde al cierre:** backend **432 passed** con Docker arriba y sin skips · `ruff`, `format` y `mypy`
limpios · front **193 passed**, typecheck y eslint limpios.

🔴 **Falta el push, y lo tiene que hacer Mateo** — el clasificador de permisos del entorno bloquea
`git push` (y también `flyctl secrets set`, de forma no determinista):

```bash
cd ~/projects/compraventa_app/backend-starter  && git push origin dev
cd ~/projects/compraventa_app/frontend-starter && git push origin dev
```

⚠️ **El push del frontend despliega solo en Vercel.** Y eso importa por una razón concreta: el
`vercel redeploy` del 21/09 reconstruyó el **source de git**, no el working tree, así que **la etiqueta de
`correct_contract_status` todavía NO está desplegada**. Hasta que se pushee, la pantalla de Auditoría muestra
esa acción **en crudo** en las 4 filas que dejó la reparación. El backend no se autodespliega: si se quiere
en Fly, va `fly deploy --config fly.dev.toml --app compraventa-backend-dev` — y después **actualizar a mano
la Machine `nightly-job`** y verificar que el `schedule` sobreviva.

---

## ✅ Fase 4 — el dominio, CERRADA el 21/09

> **Todo verificado en navegador real, no con `curl`.** Front en **`dev.prendo.com.co`**, backend en
> **`api-dev.prendo.com.co`**, apex y `www` con **308** hacia el front. `FRONTEND_URL` y
> `CORS_ALLOW_ORIGINS` leídos del proceso en vivo. Redirect URL agregada en Supabase.
> Carga inicial con **0 mensajes de consola**; `GET /api/v1/me` con `Authorization` inventado devuelve
> **401** legible con `type: "cors"`, o sea que el **preflight `OPTIONS` pasó**; el tema persiste entre
> recargas (el hash del script anti-parpadeo sigue coincidiendo, y su fallo no dejaría error de JS); y un
> `fetch` al host viejo **queda bloqueado por CSP en modo `enforce`**.
>
> **Ya nada visible dice "compraventa"** salvo dos usos de la palabra común en español (el `meta
> description` y un hint de configuración), que se dejan a propósito — no son el nombre viejo.
>
> ⚠️ **Pendiente menor, no bloqueante:** el HSTS de `dev.prendo.com.co` va **sin `includeSubDomains;
> preload`**, mientras el dominio viejo de Vercel sí los tiene. Se endurece en `frontend-starter/vercel.json`.
> Conviene hacerlo **antes** de que haya datos reales de clientes ahí.
>
> 🔴 **Para cuando exista prod:** la app de Fly se crea como **`prendo-api-prod`** (`fly.prod.toml` todavía
> dice `compraventa-backend-prod`, hay que cambiarlo antes del `fly apps create` porque después **Fly no
> permite renombrar**). Y al mover la Production Branch a `main`, los dominios **se mudan solos de build
> sin avisar**.

**La decisión, que es lo que hay que entender antes de seguir: un hostname por ambiente.**
`dev.prendo.com.co` sirve dev **para siempre**; el apex y `www` redirigen ahí con **308** hasta que exista
prod, y ese día el apex deja de redirigir. **El día del corte a prod no se mueve nada de dev.**

Se descartó lo cómodo (apex → dev ahora, mudarlo después) porque la URL de la app queda **embebida** en las
Redirect URLs de Supabase, en los enlaces de invitación y recuperación **ya enviados**, en CORS, en el CSP y
en los marcadores del cliente. Un hostname que cambia de ambiente hace que todo eso caiga, un día
cualquiera, **en otra base con datos reales** — y no avisa: no hay error, no hay 404, no hay log. Este
proyecto ya tuvo un incidente de esa forma exacta (la URL faltante en la lista de Supabase, que descartó el
`redirect_to` en silencio y dio acceso sin pedir contraseña).

Esto **reemplaza** la propuesta vieja de `PLAN_MARCA.md` (`app.` → producto, apex → redirect a `app`), que
tenía el problema de la mudanza. El backend **no se tocó**: sigue en `compraventa-backend-dev.fly.dev`.

**Hecho (Vercel):** los tres hostnames agregados a `la-legal-front-end`; apex y `www` con redirect 308 vía
`PATCH /v9/projects/{id}/domains/{domain}` de la API —**el CLI de Vercel no soporta redirects**—, los dos
`verified: true`. La Production Branch es `dev`, así que sirven el build de dev.

**Falta, en orden de bloqueo:**

1. 🔴 **Los registros DNS en GoDaddy.** Los pega Mateo (ver la tabla de abajo). Sin esto no hay nada que probar.
2. 🔴 **`CORS_ALLOW_ORIGINS` en Fly.** Medido: preflight con `Origin: https://dev.prendo.com.co` → **400**;
   con `https://la-legal-front-end.vercel.app` → **200**. El secret **no existe** (`flyctl secrets list`
   solo muestra `DATABASE_URL`, `JWT_AUDIENCE`, `SUPABASE_JWKS_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
   `SUPABASE_URL`, `FRONTEND_URL`): hoy funciona **solo** por la regex de `*.vercel.app` de
   `app/common/cors.py` con `ENVIRONMENT=dev`, y el dominio nuevo no matchea.
   **El síntoma engaña:** con el DNS perfecto la app carga y ninguna pantalla trae datos.
   Comando preparado y **sin ejecutar** (la URL vieja va en la lista para no cortar nada en la transición):
   ```bash
   flyctl secrets set -a compraventa-backend-dev \
     CORS_ALLOW_ORIGINS=https://dev.prendo.com.co,https://prendo.com.co,https://la-legal-front-end.vercel.app
   ```
3. **`https://dev.prendo.com.co/auth/callback` en las Redirect URLs de Supabase**, por `PATCH` quirúrgico a
   la Management API (`uri_allow_list`). **Nunca `supabase config push`.** Si falta, Supabase descarta el
   `redirect_to` **en silencio** y manda a la Site URL.

**La verificación no es un `curl` al home: es un login real de punta a punta sobre `dev.prendo.com.co`.**
Es el único camino que toca las cuatro puntas a la vez; un home que carga con el CORS roto se ve igual que
uno sano.

### Tres afirmaciones de la documentación que se cayeron al medir

Misma forma las tres: **el ambiente cambió y el documento no.** Lo de infraestructura no deja diff, así que
el texto y la realidad se separan sin que nada lo señale. Ya corregidas:

| Documento | Decía | Es |
|---|---|---|
| `backend-starter/docs/QA_AUDITORIA.md` §F9-02 | el fix de `FRONTEND_URL` «no se aplicó: es infraestructura» | **aplicado**: `printenv FRONTEND_URL` → `https://la-legal-front-end.vercel.app` |
| `frontend-starter/docs/DEPLOY.md` | Production Branch `main`, variables solo en *Preview* | Production Branch **`dev`**, las tres `VITE_*` en **Production** (desde el 23/08) |
| `CONTINUAR.md` · `ESTADO.md` | Fase 4 sin empezar | a medias |

**La regla:** el estado de algo que vive en un ambiente **se lee del ambiente** (`flyctl ssh console -C
"printenv …"`, la API del proyecto, un preflight real), nunca del historial de commits.

---

## 🟢 Por dónde arrancar mañana

**La Fase 5b: las notificaciones de negocio.** Es lo que Mateo preguntó explícitamente, y la respuesta
honesta es que **no existe nada**: crear un contrato, una venta o un abono **no le avisa a nadie**. El
backend no tiene módulo de correo — cero código, cero tablas, cero cola. Lo único que manda correo hoy es la
autenticación, y eso lo manda Supabase.

El diseño completo está en **`backend-starter/docs/NOTIFICACIONES.md`** (13 secciones).

**Mi recomendación de por dónde empezar, y el porqué:** **los avisos a la EMPRESA, no al cliente.**

1. **Llegan.** Medido: de 16 clientes, **2 tienen correo** — en una compraventa colombiana el cliente da el
   celular. La empresa, en cambio, **siempre** tiene correo, porque sus usuarios entran con él.
2. **No tienen problema legal.** Avisarle al dueño que un contrato está listo para remate es información
   interna. Avisarle al cliente es un acto con peso jurídico, y es una de las preguntas abiertas.
3. **Hay uno que se rompe en silencio hoy mismo:** el vencimiento de la suscripción **no se avisa**. El corte
   es en seco y ya hay **2 suscripciones vencidas** en dev — la empresa se encuentra la app cerrada. Es de
   los más baratos porque el job que lo detecta ya existe (F21-21).

Eso deja armada toda la maquinaria —tablas, cola, plantillas, idempotencia— para cuando se decida qué hacer
con el cliente.

⚠️ **Antes de escribir código hay siete preguntas de negocio** en §12 de `NOTIFICACIONES.md` que solo Mateo
puede contestar. Dos ya están cerradas (el aviso de remate y la base legal de Habeas Data). La séptima —si el
aviso de **prórroga** tiene el mismo peso legal que el de remate— **va al mismo abogado en la misma
consulta**, y hoy ese aviso **está encendido** con criterio propio, no con concepto.

🔴 **Y una advertencia de diseño:** el plan le agrega un **tercer paso al job nocturno**, o sea más
responsabilidad sobre la pieza más frágil de la infraestructura. Esa Machine ya fue borrada una vez por
"huérfana", y el guardián la cazó desactualizada **cuatro veces el 23/09**. Al implementar esto hay que
actualizarla en el mismo despliegue y verificar que el `schedule` sobreviva.

---

## Lo que espera a Mateo, y no es código

Lo que ningún agente puede hacer por él:

| Qué | Dónde | Por qué urge |
|---|---|---|
| **Las 7 preguntas de negocio** | `backend-starter/docs/NOTIFICACIONES.md` §12 | **Bloquean la Fase 5b.** Dos necesitan un abogado: el aviso de remate (cerrada: no por ahora) y el de prórroga (abierta, y hoy está encendido) |
| **El DMARC** | GoDaddy → `_dmarc` TXT | Cierra la Fase 5a. `p=none` primero. ⚠️ **Un Gmail cualquiera NO recibe reportes DMARC**: hace falta un agregador |
| **La prueba de spam** | Gmail · Outlook · un corporativo | Un correo de recuperación en spam es una persona que no puede volver a entrar |
| ~~Pushear los dos repos~~ | — | **Hecho.** Todo commiteado, pusheado y desplegado el 23/09; los dos árboles limpios |
| **Mover el pin del kit** | Abrir el artifact → **Share** → mover el pin a la versión nueva | Republicar **no** cambia lo que ve quien abre el enlace. Verificar en el Share menu si todavía está clavado en una versión vieja |
| ~~Pegar los registros DNS en GoDaddy~~ | — | **Hecho el 21/09.** Los cuatro registros del front y los dos del API (`api-dev`) están pegados, propagados y con certificado emitido |
| ~~Decidir qué hacer con F21-10~~ | — | **Resuelto el 21/09**: los 4 contratos dañados se repararon y se verificaron. Ya no espera nada de nadie |

En el terminal, `/artifacts` lista los artifacts (`o` abre, `c` copia el enlace).

> **Dato que costó descubrir: un artifact compartido tiene dos modos, y no es obvio cuál te tocó.**
> La **guía** quedó en «los visitantes ven los cambios al instante» — republicar basta, no hay nada que mover.
> El **kit** quedó con la versión **clavada**, y ahí republicar no alcanza: hay que mover el pin a mano.
> El estado real se lee en la cabecera al abrir el artifact. Antes de decirle a un cliente «ya está
> actualizado», verificar cuál de los dos modos tiene.

---

## Estado al cierre del 21/09

| Frente | Estado |
|---|---|
| **Fase 1 · Marca al código** | ✅ Aplicada, desplegada y verificada sobre lo servido |
| **Fase 2 · Kit de marca** | ✅ Reescrito y republicado (v2) · ⚠️ falta mover el pin |
| **Fase 3 · Guía de usuario** | ✅ **CERRADA.** Las 8 partes escritas y **republicada el 22/09 (versión 6)**, en vivo para quien tenga el enlace. Falta solo lo opcional: las **capturas**, que van contra una empresa espejo sembrada (Ley 1581) |
| **Fase 4 · Dominio** | ✅ **CERRADA.** Front `dev.prendo.com.co` · backend `api-dev.prendo.com.co` · apex y `www` con 308 · `FRONTEND_URL` y `CORS_ALLOW_ORIGINS` puestos · Redirect URL en Supabase · verificado en navegador real. Queda solo endurecer el **HSTS** |
| **Fase 5 · Correo** | 🟡 **Casi.** Resend verificado y conectado a Supabase, Site URL y plantillas aplicadas, correo llegando con `token_hash`. Falta el **DMARC** (paso 3) y las dos verificaciones del paso 7 |
| **Backend en Fly** | ✅ **Desplegado el 21/09** y verificado sobre lo servido (`title: Prendo API`, health ok) |
| **Repos** | ✅ Limpios y pusheados en `dev` (front y back). ⚠️ La **rama por defecto** pasó a `dev`: sin eso los workflows programados no corren (F21-30) |

### La parte 6 de la guía, con honestidad

Se llama «Reportes y cierre contable», y **quedó en gran parte redundante**: lo que era su corazón —qué mide
cada indicador y qué deja por fuera, por qué hay dos utilidades distintas, por qué los intereses cobrados no
cuadran entre dos tarjetas— ya está escrito en la pantalla de **Reportes** de la parte 4.

Lo que sí falta, y no es poco:

- **Cómo se cierra un mes**: qué se revisa, en qué orden, y cómo se concilia lo que dice la caja contra lo
  que dice Reportes.
- **Qué entregarle al contador**, y en qué formato.
- **Por qué la utilidad del estado de resultados no coincide con la plata del cajón.** Es *la* pregunta de
  fin de mes y hoy la guía la responde a medias: la pieza que falta es que prestar y comprar mercancía
  convierten efectivo en otra cosa sin tocar la utilidad, y eso está dicho en Reportes pero no desde la
  pregunta del dueño.

Insumos disponibles: `frontend-starter/docs/GUIA_INSUMOS.md` §4 (los KPIs de Reportes, ya verificados).

### Nueve defectos del front, reportados y sin arreglar

`backend-starter/docs/QA_AUDITORIA.md`, hallazgos **F20-01..03** y **F21-01..09**. El más fácil y el más
dañino a la vez es **F21-01**: el buscador de la venta dice «(Enter agrega)» y no es cierto — Enter
**intenta registrar la venta**. Es una línea de texto.

Ninguno salió de leer código a secas: **todos salieron de escribir la guía y después verificarla.**

---

## Sesión del 20/09 — la paleta de oro, el logo nuevo y la marca en el código

Mateo trajo una paleta propia (**Oro Moderno**) y pidió un logo más diferencial. Se rehízo la identidad
visual y **se aplicó al código** — la tanda que el 12/09 quedó explícitamente aplazada.

### Lo decidido

| | |
|---|---|
| Color | **Oro** `--brand-500: #c99a3d` (claro) / `#d3ac5f` (oscuro). Reemplaza al esmeralda, que nunca llegó al código |
| Texto sobre el oro | **Carbón `#24211c`**, no blanco — ver abajo, es la decisión no obvia |
| Logo | **Etiqueta**: rombo de esquinas redondeadas con perforación, un `path` con `fill-rule: evenodd`, tile de radio 16/64. Reemplaza el monograma **P** |
| Neutrales | Cálidos: marfil `#faf8f2`, beige `#f1ebdd`, carbón `#24211c`, gris cálido `#716c63`. El sidebar pasa a carbón |
| Tipografía | Sin cambios: **Archivo** para el wordmark, **Inter** en la interfaz |

### Las dos cosas que salieron al medir, y que cambiaron el plan

1. **Blanco sobre el oro da 2.57:1** — *peor* que el teal 2.70 que este proyecto abandonó por no cumplir AA.
   Aplicar la paleta tal como venía habría reabierto `DECISIONES_PENDIENTES.md` §4 a la semana de cerrarla.
   Salida: el texto sobre el oro es **carbón (6.24:1)** y `#c99a3d` queda **intacto** como relleno.
   Es además como se resuelve el oro en las marcas premium — blanco sobre dorado se ve lavado.

2. **`bg-primary` y `text-primary` son la misma variable de Tailwind**, y con un primario claro eso rompe:
   el oro como **texto** sobre fondo claro da **2.42:1**. Ahí viven los enlaces y las cifras de dinero del
   `KpiCard` — justo lo que la paleta recomendaba pintar de dorado. Se separó `--color-brand:
   var(--brand-700)` en `globals.css` y se migraron los 12 usos.
   **Regla nueva: `bg-primary` para rellenos, `text-brand` para texto y bordes.**
   Esto no se encontró leyendo código: se encontró **mirando la pantalla de login renderizada**.

### Lo hecho

- `src/styles/tokens.css` — marca, semánticos, neutrales y sidebar, en los dos bloques.
- `src/styles/globals.css` — `--color-brand`, y `--color-ring`/el outline de Tiptap pasan a `--brand-700`.
- `tests/token-contrast.test.ts` — **mide el relleno del botón primario** en los dos temas. Era el agujero
  por el que el teal en 2.70 vivió meses. Verificado a la inversa: con `--brand-contrast: #ffffff` falla
  con 2.57, que es para lo que existe.
- Los 6 SVG de `marca/logo/` regenerados con la etiqueta en oro; copias en `public/`.
- `index.html` (`<title>` + `description`), `LoginPage` (marca de Prendo), `AppFooter` ("Hecho con Prendo").
- `AppShell`/`AppFooter`: el respaldo `'Compraventa'` pasa a **`'Mi empresa'`**, no a `'Prendo'` — ese texto
  es el nombre del **inquilino**, y poner ahí la marca de la plataforma rompería la regla de gobierno.
- `backend-starter/app/main.py` — `FastAPI(title="Prendo API")`.
- `docs/DESIGN_SYSTEM.md` §1-bis reescrito. **§2 ya no copia los hex**: el duplicado había derivado (decía
  `--success: #22A06B` cuando el archivo real tenía `#1b7e54`), así que quedó el mapa de roles y un puntero.
- `docs/PLAN_MARCA.md` — nuevo. Las 5 fases hasta el primer correo desde `prendo.com.co`.

Verde: lint (0 errores), typecheck, **193 tests** (192 + el nuevo), build.

### La trampa que salió al verificar lo servido

Medir el bundle desplegado —en vez de confiar en el push— pagó otra vez.
Después del deploy, el CSS servido traía `.text-\[\#00B19E\]{color:#00b19e}`: **el teal viejo, vivo en
producción**, después del rebranding.

No venía de ninguna feature. **Venía de `CLAUDE.md`.** Tailwind v4 escanea el proyecto entero, incluido ese
archivo, y el ejemplo de la regla 4 —el que existe justamente para *prohibir* esa sintaxis— es una clase
válida. Tailwind la encontró y la emitió. La regla se estaba disparando a sí misma.

Arreglado en `c56a854`: la regla se explica sin escribir el literal. Y de paso la regla 4 ahora advierte
sobre `text-primary`, que es el relleno y no el texto.

**La lección, que ya estaba escrita y se confirmó:** un `git push` verde no dice que el bundle servido tenga
lo que creés. Hay que mirar lo servido.

### Commiteado y desplegado

- **backend** `4dea4a9` (aviso de superado en `CONTEXTO.md`) + `642fce9` (título de la API + hallazgos de QA) → `dev`.
- **frontend** `ca4d1be` (toda la marca) + `c56a854` (el hex fantasma de `CLAUDE.md`) → `dev`. **Vercel despliega solo desde `dev`.**
- **Verificado sobre lo servido:** `<title>Prendo`, el favicon es la etiqueta en `#c99a3d`, y el CSS trae `--brand-500:#c99a3d` · `--brand-contrast:#24211c` · `--bg-app:#faf8f2` · `--color-brand:var(--brand-700)` en los dos temas.
- **Fase 2 cerrada:** `marca/IDENTIDAD.html` reescrito y republicado a la misma URL.

**Dos cosas que quedaron pendientes y no son código:**

1. **El backend no se desplegó a Fly.** `flyctl` no está autenticado acá y `fly auth login` abre el navegador.
   Correr `fly auth login` y después
   `fly deploy --config fly.dev.toml --app compraventa-backend-dev`.
   No urge: el único cambio es `FastAPI(title="Prendo API")`, que no toca el esquema.
2. **El enlace del kit sigue mostrando la versión vieja.** Un artifact compartido sirve una versión
   **clavada**. Hay que abrir el artifact → **Share** → mover el pin a la versión nueva. Republicar no alcanza,
   y `marca/README.md` decía lo contrario (ya corregido).

### Y el dominio, que tiene fecha

> **DECIDIDO el 21/09/2026: no se compra `prendo.co`.** El precio de renovación de un `.co` recién liberado
> se sale del presupuesto. **La marca vive en `prendo.com.co`**, que ya está comprado y que en Colombia es
> el dominio que un SaaS B2B usa con toda normalidad.
>
> Esto no es una pérdida: era justamente el punto de comprar el `.com.co` primero — *la marca no queda de
> rehén de un dominio*. Queda escrito para que nadie lo vuelva a proponer como pendiente urgente.

Lo que se midió en su momento, como registro: **`prendo.co` estaba LIBRE** — cayó alrededor del 16/09 y
nadie lo tomó. Verificado el 20/09 contra
`whois -h whois.registry.co` (`DOMAIN NOT FOUND`) y contra el NS autoritativo del TLD (`NXDOMAIN`).
Se daba por perdido. Conviene registrarlo antes de que lo agarre un drop-catcher.

`prendo.com.co` quedó registrado en GoDaddy con el parking por defecto. **Trampa para la fase del correo:**
GoDaddy auto-provisionó un `DMARC` con `p=quarantine` cuyos reportes van a un buzón de ellos. Al montar
Resend hay que **reemplazar** ese registro, no solo agregar SPF y DKIM.

### Fase 3 — siete de ocho partes (21/09/2026)

Escritas las partes **1 a 5, la 7 y la 8**. Falta solo la 6, y buena parte de su contenido ya quedó en la
pantalla de Reportes. Republicada, versión 5.

**Tres tandas de QA contra el código, y las tres encontraron cosas.** El patrón se repite, así que vale el
detalle:

1. **Caja y Ventas** — cinco afirmaciones falsas, entre ellas una **cita de error inventada**.
2. **Problemas frecuentes** — 18 correcciones. La peor: el atajo «si el medio de pago es transferencia
   funciona con la caja cerrada» estaba **al revés**. Lo que decide no es el medio de pago sino **el tipo
   de cuenta**: si toca el cajón de efectivo hace falta caja abierta aunque marques transferencia. Tres
   cosas la exigen siempre: gastos, anulaciones y traslados que tocan efectivo.
3. **Día a día, Administración y Glosario** — siete correcciones obligatorias, y **cuatro ya venían en la
   guía desde el 12/09**: se propagaron en vez de detectarse.

**Los errores heredados, que son los que más enseñan:**

- **«pieza única = una joya»**, falso en cuatro sitios. Solo el **remate** crea piezas únicas; una joya
  comprada a proveedor no exige foto para publicarse. La guía le decía al mostrador que no podría hacer
  algo que sí puede.
- **«Al día + capital»** no existe como botón, en tres sitios. Si el contrato está al día no hay botones:
  sale directo el campo «Abono a capital».
- **El rol se llama «Admin»**, no «Administrador», y **Bodega no paga compras**.
- **La causa del «enlace ya se usó»** describía un bug ya arreglado: los enlaces que genera un admin
  aguantan las vistas previas de WhatsApp. Solo se queman los del correo automático.
- **«El buscador de la barra no funciona»**: no está deshabilitado, **se quitó**. Afirmar que algo no
  funciona de una forma que no coincide con la pantalla es peor que no decir nada.

**La regla, confirmada tres veces:** escribir la guía desde un informe intermedio **no cuenta como
verificar**. Y el contenido heredado tampoco se salva: cuatro de los siete errores graves ya estaban
escritos y nadie los había medido.

**Nueve defectos del front** registrados como F21-01..09 en `backend-starter/docs/QA_AUDITORIA.md`.

### Fase 3 — la parte 4 (histórico)

**Las 14 pantallas escritas**, con el molde de Contratos: permisos por acción, tablas de campos con
obligatorio/opcional sacado del schema o del submit, y una tabla «Si algo sale mal» por pantalla.
Faltan las partes 3, 5, 6, 7 y 8. Republicada, versión 4.

**El QA de la guía encontró errores míos, y por eso se hizo.** Caja y Ventas se escribieron desde el
informe de otro agente, no leyendo el código, y salieron cinco afirmaciones falsas — entre ellas una
**cita de error inventada** («Esa cuenta no puede cubrir el pago», que no existe en el código) y
**«Enter agrega al carrito»**, que además es al revés de peligroso: el buscador vive dentro del
formulario, así que Enter intenta registrar la venta.

**Regla que conviene dejar escrita:** escribir la guía desde un informe intermedio **no cuenta como
verificar**. O se lee el código, o se pasa un QA que lo lea.

De paso salieron **cinco defectos del front** (F21-01..05 en `backend-starter/docs/QA_AUDITORIA.md`), tres
que un usuario sufre. El peor es el placeholder «(Enter agrega)».

### Fase 3 — lo anterior

Escritas **Caja** y **Ventas** de la referencia pantalla por pantalla, con el mismo molde que Contratos:
permisos por acción, tablas de campos con obligatorio/opcional, y una tabla «Si algo sale mal» por pantalla.
La guía además quedó **con la paleta de oro y el logo de etiqueta** — seguía en esmeralda y con la P.

Verificado renderizado: sin enlaces rotos en el índice, sin scroll horizontal, y el buscador del índice
indexa lo nuevo (buscar «descuadre» filtra a Caja).

**Republicada** a la misma URL, versión 3. *(Estaba privada; Mateo la compartió el 21/09 y quedó en modo «ver
cambios al instante».)*

**Faltan 10 pantallas** (Inicio · Inventario · Clientes · Cuentas · Capital · Catálogos · Identidad ·
Reportes · Auditoría · Configuración · Mi perfil) más las partes 3, 5, 6, 7 y 8.

### Lo que sigue

1. ~~**Fase 3 — la guía de usuario**, que sigue al ~30%.~~ *(Al 21/09: 7 de 8 partes.)* Los insumos de las 13 pantallas ya están
   extraídos y verificados contra el código en **`frontend-starter/docs/GUIA_INSUMOS.md`**, con su lista de
   lo que quedó sin verificar. **Ojo con el método:** la regla "los campos salen del schema de Zod" solo
   se puede cumplir en la mitad de las pantallas — hay 13 schemas de Zod en todo `features/`, el resto
   valida a mano.
3. **Fase 4 — el dominio.** `prendo.com.co` ya está comprado; falta DNS, Vercel, Fly y sincronizar las
   tres puntas con Supabase Auth.
4. **Fase 5 — el correo.** Resend sobre el dominio verificado. Ojo: la plantilla de
   `docs/correo-invitacion.html` está escrita pero **sin aplicar**, dice "Compraventa", usa el teal viejo y
   usa `{{ .ConfirmationURL }}` en vez de `{{ .TokenHash }}` — o sea que aplicarla hoy metería la marca
   vieja y conservaría el bug de los crawlers.

Todo el detalle, con dependencias y qué verificar en cada fase: **`frontend-starter/docs/PLAN_MARCA.md`**.

---

## Sesión del 12/09 — la marca y la guía de usuario

**Sesión sin código.** Se cerraron dos pendientes que no eran técnicos y bloqueaban la venta tanto como el ambiente de producción: el producto no tenía nombre, y no había nada que entregarle a un cliente.

### Lo decidido

| | |
|---|---|
| Nombre | **Prendo** — *prenda* en forma de verbo, y «prendo» de encender. Sin tilde ni eñe, a propósito |
| Color | **Esmeralda** `--brand-500: #0f7a5a` (claro) / `#2ed39b` (oscuro) |
| Logo | Monograma **P** con el contraojo circular, un `path` con `fill-rule: nonzero`, tile de radio 16/64 |
| Tipografía | **Archivo** SemiBold para el wordmark. **La interfaz sigue en Inter** — eso no cambia |
| Alcance | Kit visual aprobado primero; **aplicar al código es otra tanda** |

Todo en **`frontend-starter/docs/DESIGN_SYSTEM.md` §1-bis**, que reemplaza el párrafo del placeholder.

**Los dos entregables viven en [`marca/`](marca/), en la raíz** — junto con los SVG del logo y un `README.md` con el método para continuarlos. Los `.html` son la fuente; los enlaces, el resultado, y se republican a la misma URL.

| | Archivo | Enlace |
|---|---|---|
| Kit de marca | `marca/IDENTIDAD.html` | <https://claude.ai/code/artifact/bdce6752-e078-41bd-b582-44fab3d2cd4e> |
| Guía de usuario | `marca/GUIA_USUARIO.html` | <https://claude.ai/code/artifact/e10cdc49-4eea-49c6-8c2f-7e43b87ff742> |

### Tres cosas que conviene no re-descubrir

**El `whois` del sistema miente con `.co`.** Cae a IANA y devuelve los datos del TLD, así que *todo* dominio `.co` parece tomado. Hay que preguntarle al registro: `whois -h whois.registry.co <dominio>`. Con eso salió el dato que importa: **`prendo.co` estaba en `pendingDelete` el 11/09 y caía alrededor del 16/09** — esa fase dura cinco días y el dueño anterior ya no puede recuperarlo. `prendo.com.co` está libre.

> **Recado para Mateo:** registrar `prendo.com.co` (la red que no depende de la suerte) y poner un backorder de `prendo.co` en DropCatch/SnapNames/Dynadot/Namejet. Después del 16/09, verificar con el comando de arriba.

**`DECISIONES_PENDIENTES.md` §4 se resolvió por una opción que no estaba en la lista.** Las tres opciones daban por fijo el teal y preguntaban qué sacrificar (la identidad, el contraste o la convención del botón). Pero **el teal nunca fue la marca**: era un placeholder declarado como tal en `DESIGN_SYSTEM.md` §1 desde el 15/08. Definir la marca disolvió la restricción — se eligió un color que cumple en vez de ajustar uno que no. Blanco sobre el relleno: **2.70 → 5.31**. Las 10 combinaciones pasan AA.

**`CONTEXTO.md` §3 describe un esquema de códigos que ya no existe, y me indujo el error.** Escribí la sección de códigos de la guía desde ahí en vez de desde `inventory/rules.py`, y salió el esquema de **pieza única** (`JOC0001I`), que quedó obsoleto cuando el modelo se partió en **producto + lote**. Mateo lo cazó de inmediato. Lo vigente:

- **Producto (SKU):** `[Cat1][Cat2][Cat3][Consecutivo 4]` → `JAO0007`. **Sin letra de proveedor** — el proveedor pertenece al lote.
- **Lote:** `{SKU}-{lote 2 dígitos}{letra de origen}` → `JAO0007-01I`. Es el de la etiqueta.
- **Cinco orígenes, cuatro letras reservadas:** `R` remate · `P` propio · `T` transformado · `D` devuelto · otra = proveedor. `RESERVED_SUPPLIER_LETTERS` en `catalogs/schemas.py`, validado **solo al escribir**.
- Precio en el producto, costo en el lote.

Ya quedó un aviso al principio de ese párrafo en `CONTEXTO.md`. **La lección es más general que el dato:** `CONTEXTO.md` es del 14/08 y congela decisiones *de esa fecha*; el código evolucionó encima. Para documentar una regla, la fuente es el módulo, no el documento de traspaso — exactamente el mismo principio que ya está escrito como *"un comentario del código puede estar mintiendo"*, un nivel más arriba.

**Playwright ya no tiene navegador descargado.** `~/Library/Caches/ms-playwright/` solo tiene `ffmpeg`. Funciona igual con el Chrome del sistema: `chromium.launch({ channel: 'chrome' })`. Vale para cualquier verificación visual futura.

### Lo que sigue

1. **Aplicar la marca:** 6 líneas × 2 bloques en `src/styles/tokens.css`, `public/favicon.svg`, el `<title>` de `index.html`, el respaldo `'Compraventa'` de `AppShell.tsx:142,173`, `AppFooter` y el login. Un solo deploy.
2. **Extender `tests/token-contrast.test.ts` en la misma tanda** para que mida el **relleno** del botón primario. Hoy solo mide tokens de texto — por eso el 2.70 vivió meses sin que nada fallara. Sin ese test, el próximo cambio de marca repite el agujero exacto.
3. **Terminar la guía:** faltan las 13 pantallas restantes, las 14 tareas del día a día, administración, reportes, problemas frecuentes y glosario. **Cada tabla de campos se escribe leyendo el schema de Zod, no de memoria** — obligatorio/opcional sale del schema, nunca del label. Y las capturas van contra una **empresa espejo sembrada**: la dev remota tiene clientes reales con cédula y fotos de documento (Ley 1581).

---

# Cierre del 11/09/2026 (sesión de la tarde)

> **Para el próximo chat (humano o agente).** Este archivo es el traspaso de una sesión a la siguiente: dónde quedó todo, qué trampas evitar y qué sigue.
> El contexto general vive en **[`README.md`](README.md)**; el estado permanente en **[`ESTADO.md`](ESTADO.md)**; el runbook de altas de usuario en **[`RUNBOOK_USUARIOS.md`](RUNBOOK_USUARIOS.md)**.
> Este archivo se reemplaza cada sesión; `ESTADO.md` se actualiza.

## Lo primero: verifica que estás mirando lo que crees

```bash
cd backend-starter  && git status --short && git log --oneline -1
cd ../frontend-starter && git status --short && git log --oneline -1
```

> **Antes de correr `pytest`: levantá Docker.** Sin él, `supabase start` falla y la suite **pasa igual** — pero con la mayoría de tests SALTADOS. Un `95 passed` no es la suite: la completa son **422**.

Tests: **backend 422 · frontend 192**, todo en verde y **la CI también** (estaba roja desde antes de esta tanda). **57 migraciones** · 41 permisos · 122 operaciones de API (96 rutas).

> ### ✅ DESPLEGADO Y VERIFICADO SOBRE LO SERVIDO (11/09/2026)
> Las tres migraciones (`00053`, `00054`, `00055`) aplicadas en local y en la **dev remota**. Backend en Fly (96 endpoints en el `/openapi.json` servido), front en Vercel (`index-COybSePt.js`, hash comparado contra el build local).
> **Verificado ejerciendo las reglas, no mirando el deploy:** `verificar_despliegue_11_09.js` (25 OK · 0 MAL), `verificar_recargo_ancla.js` (11 OK) y `ui_caja_cerrada.js` (9 OK), más el impreso en `media print`, la eñe contra lo servido (14 OK) y el dashboard (5 OK). Los tres scripts quedaron en `backend-starter/scripts/qa/`.

---

## Qué pasó esta sesión

Mateo probó la app con el cliente y trajo **cinco cosas**. Tres eran arreglos, dos eran preguntas de negocio que el producto no sabía contestar. Las cinco están hechas. El detalle completo está en [`frontend-starter/docs/IMPLEMENTATION.md`](frontend-starter/docs/IMPLEMENTATION.md) (bloque más reciente).

### 1. Los buscadores — eran dos causas, y ninguna era un umbral de cinco

La grande: **`plainto_tsquery` compara lexemas ENTEROS**. "Mateo" encontraba a Mateo y "Mate" no encontraba nada. Como los nombres de pila tienen cinco o seis letras, desde el mostrador se veía exactamente como "solo filtra desde la quinta". Pasaba en clientes, contratos, artículos y productos.

Ahora es prefijo real (`to_tsquery` con `:*`, usando el índice GIN que ya existía) con piso de tres — y **el piso va por CLÁUSULA**: el número de contrato se sigue encontrando desde la primera tecla.

**Dos cosas que cazó el test y no yo:**

- La primera versión abría `:*` solo en la **última** palabra. Falso para un buscador que filtra mientras se escribe: "jara mateo" no encontraba a Mateo Jaramillo. Van todas abiertas.
- **`to_tsquery` es sintaxis y `plainto_tsquery` no lo era.** Un `&` o un `(` sueltos son un `SyntaxError` de Postgres → **500 en un buscador**. Riesgo NUEVO del cambio, con test parametrizado.

Y el plan B: las stopwords del español son lexemas vacíos, así que "De la Cruz" no aparecería tecleando "de la". Va un `ilike` en el `or`.

> **Encontrado de paso y arreglado después, en `00056` — pero con la causa al revés de lo que anoté primero.** La hipótesis era "faltan las tildes"; al medirlo resultó que el stemmer de `spanish` **ya** normaliza las vocales acentuadas ("jose" encontraba a José) y lo que no toca es **la eñe**. Ver el bloque de abajo.

### 2. El recargo ya no mueve la fecha de cobro (`00053`, `00055`)

El sucesor **hereda el ancla**: `start_date` de la raíz de la cadena, `interest_paid_until` y `due_date` del padre. Presta el 1, recarga el 25, se cobra el 1 sobre el capital nuevo.

Esto **disuelve** el dilema de `RECARGOS.md` §5 en vez de contestarlo: ya no hay mes en curso que perdonar ni cobrar. La palanca ya estaba puesta —`extension_interest_policy`, que existía desde `00051` sin que nada la expusiera— y ahora tiene `keep_anchor` como default.

**La parte que casi se me pasa y es la más importante:** antedatar `start_date` dejaba el impreso fechado semanas atrás en un papel que se firma hoy. **Eso es un documento antedatado, y es peor que el problema resuelto.** Por eso `extended_on` / `extension_amount`, el recuadro con las **dos fechas** en `ContractPrintView`, y la línea de la cadena reescrita (decía "ampliado el {start_date}", que habría pasado a mentir).

`00055` migró los **48 contratos vivos** a `keep_anchor`; los 13 cerrados se dejaron intactos porque `extend_loan` los rechaza antes de mirar la política.

### 3 y 4. El dinero del dueño: no existía (`00054`)

Las dos preguntas —inyectar capital y retirar utilidades— son **la misma operación en dos sentidos**, así que es un solo documento con `direction`.

Antes había tres salidas y las tres estaban mal: un `adjustment` (que **miente** — el sistema sí cuadraba), un traslado (solo sirve si la plata ya está en una cuenta de la empresa) o nada. Y el retiro como gasto falsearía la utilidad por todo el monto.

**Y la app NO necesitó partida doble:** el estado de resultados lee **documentos** (`sale`, `contract_payment`, `expense`), así que un `capital_movement` queda fuera del resultado **por construcción**. El modelo ya protegía esto antes de que el caso existiera.

Lo que le da valor a la pantalla no es el formulario: es `GET /capital/position`, que contesta **dónde está la plata** (disponible + prestado + inventario **al costo**). *Retirar "lo que hay en caja" no es retirar utilidad, es descapitalizar.* No bloquea — advierte.

Diseño completo: [`backend-starter/docs/CAPITAL_DEL_DUENO.md`](backend-starter/docs/CAPITAL_DEL_DUENO.md).

### 7. La CI llevaba días en rojo, y dos arreglos de una línea

**La CI de `dev` fallaba `ruff check .` y `ruff format --check .` desde antes de esta tanda**, así que *todo* PR salía rojo por cosas que nadie había escrito en él. Una CI que siempre falla no dice nada: enseña a ignorarla, y el día que rompa algo de verdad nadie la va a mirar. Ya está verde.

Seis de los siete archivos eran formato corriente. **El séptimo necesitaba una decisión, no un formateo:** la lista `SEEDS` de `seed_contratos.py` es una tabla de datos alineada a mano —cada fila es un caso de prueba y las columnas se comparan de un vistazo— y el formateador la explotaba a ~300 líneas. Va entre `# fmt: off` / `# fmt: on` con el porqué al lado, para que no parezca descuido.

**El dashboard mostraba la fecha equivocada** en "Listos para remate": decía *«Vencido el {due_date}»* cuando lo que pone ahí al contrato es `extension_ends_at`. Salió de explicar la diferencia entre plazo y ventana de mora. Medido en vivo sobre un contrato real: el papel decía 12/12/2025 y la prórroga venció el 12/06/2026 — **seis meses de diferencia**, mostrando la fecha que no era como si fuera la causa.

**Y la contracción de `00056`:** `ix_customer_name` (sin unaccent) ya no lo usa ninguna consulta. Un índice que nadie usa no es gratis — encarece cada alta y cada edición de cliente.

### 6. `unaccent`: la causa era la EÑE, no las tildes (`00056`)

Este salió del pendiente que dejé anotado unas horas antes, y **la hipótesis estaba al revés**. Vale la pena dejar la medición porque la intuición falla acá.

El stemmer snowball de `spanish` **sí** normaliza las vocales acentuadas: `to_tsvector('spanish','José')` da `jos` y `Gómez` da `gomez`. O sea que buscar "jose" o "gomez" **ya funcionaba** — lo que yo había afirmado que no.

Lo que el stemmer **no toca es la eñe**: `Muñoz` queda `muñoz` y `Peña` queda `peñ`. Sobre apellidos colombianos corrientes fallaban **8 de 11**, y los 8 por lo mismo:

```
José · Gómez · Andrés              ya funcionaban
Muñoz · Peña · Castaño · Ordóñez   no
Zúñiga · Núñez · Acuña · Piña      no
```

Y nadie teclea la eñe al buscar: el teclado del celular la esconde.

**Por qué `f_unaccent` y no `unaccent()` a secas:** `unaccent` es STABLE, no IMMUTABLE —depende del diccionario que resuelva el `search_path`— y Postgres se niega a indexar una expresión así. Sin el envoltorio, el índice funcional no se puede crear y cada búsqueda sería un seq scan recalculando el `tsvector` de toda la tabla. El `set search_path` de la función tampoco es decorativo: el backend **cambia de rol por transacción**, y una función inmutable cuyo resultado dependa de quién la invoca es justo lo que el planificador no espera.

Se aplica a los **dos** lados —la columna y lo tecleado—, o la comparación sería entre un texto normalizado y otro que no. Verificado con `EXPLAIN` que el índice nuevo se usa: sin eso el arreglo funcionaría y sería lento **en silencio**.

### 5. El recargo con la caja cerrada fallaba **en silencio**

`ExtendLoanPanel` tenía el `catch` **vacío**, con un comentario que afirmaba que `useMoneyMutation` dejaba el error a la vista. No lo hace: solo maneja la `Idempotency-Key`. Otra vez *"un comentario del código puede estar mintiendo"*, y las otras once pantallas de dinero lo hacían bien.

Ahora abre `CashSessionRequiredDialog`, y **avisa antes**: la sesión la exige el **tipo de cuenta**, no la operación, así que el recargo por transferencia funciona con la caja cerrada. El panel lo dice — callejón sin salida convertido en camino.

### Lo que quedó comprobado en vivo, para no repetirlo

| Qué | Resultado |
|---|---|
| Buscador de clientes con 3 letras | `"cli"` encuentra a *Cliente Uno QA*; con 2 la pantalla dice **qué falta** en vez de "Sin resultados" |
| `&`, `(`, `:*`, `de la`, `!!!` en el buscador | 200 los cinco — el `SyntaxError` que habría sido un 500 no ocurre |
| Nº de contrato con **1** carácter | Sigue encontrando: el piso es por cláusula |
| Recargo sobre contrato del 22/08, hecho el 11/09 | Sucesor con `start_date` **22/08**, `extended_on` **11/09**, `extension_amount` 500.000, capital 1.500.000, viejo `superseded`, prendas `transferred` |
| El impreso, en `media print` | Recuadro de 82px: *«Conserva la fecha de aquel (22/08/2026)… El recargo de $500.000 se entregó el 11/09/2026»* |
| Aporte del dueño | La utilidad **no se movió** (1.597.000 → 1.597.000) |
| Retiro del dueño | Los gastos **no se movieron** (148.000 → 148.000) |
| Retiro sin motivo / mayor al saldo | 422 y 400 |
| Asesor en `/capital` | 403 en ver y en retirar |
| Recargo en efectivo con caja cerrada | Aviso preventivo *"puedes ampliar por transferencia"* **antes**, y modal `Caja cerrada` con CTA al confirmar |
| La eñe (`00056`), contra lo servido | 14/14 — "munoz"/"muñoz", "pena", "castano", "ordonez", "zuniga", "acuna" encuentran; "jose" y "gomez" siguen funcionando |
| El índice nuevo se usa | `EXPLAIN` → `Bitmap Index Scan on ix_customer_name_unaccent`. Sin eso el arreglo sería correcto y lento en silencio |
| "Listos para remate" en el dashboard | Dice *«Prórroga vencida el 12/06/2026»*; antes decía *«Vencido el 12/12/2025»*, seis meses de diferencia |

---

## Lo que encontré de paso y conviene no re-descubrir

**La CI de `dev` ya estaba ROJA antes de esta sesión**, y sigue. `ruff check .` falla por un E501 en `scripts/qa/verificar_saldos.py`, y `ruff format --check .` por **siete** archivos (`contracts/router.py`, `contracts/service.py`, tres scripts de QA y dos tests). No los toqué: `seed_contratos.py` está alineado a mano a propósito y reformatearlo es ruido. **`app/` y `tests/` sí quedan limpios** salvo esos dos de `contracts/`, que son preexistentes. Arreglarlo es media hora y desbloquea la CI.

**Ningún test cubría `start_date` del sucesor.** Los 26 tests del recargo pasaron sin tocar nada después de invertir la regla. El agujero está tapado con cinco tests nuevos.

**El caché de permisos de 60s arruina los tests de permiso.** Borrar un `role_permission` en la base no se ve dentro del test: la llamada pasa el `require_permission` y falla después por otra cosa, dando un 400 que parece cubrir un 403. Hay que crear un **rol nuevo**, no revocarle a uno cacheado.

**El `movement_date` obligó a un cursor nuevo.** `encode_time_cursor` es sobre `datetime` (`created_at` = cuándo se registró). Un documento con fecha propia necesita `(date, id)`: está en `app/common/pagination.py` como `encode_date_cursor` / `make_date_page`.

---

## Los pendientes, en orden de lo que yo haría primero

### A. El ambiente de producción

**Es el único bloqueante real para venderle esto a un cliente**, y lo que queda por delante no es código: es infraestructura y decisiones (dominio, correo, proyecto Supabase de prod). Todo lo demás de la lista es mejora.

Ver `ESTADO.md` § "Lo que bloquea entregarle esto a un cliente" y `frontend-starter/docs/DEPLOY.md`.

### B. La sesión de caja de LA GRAN LEGAL — abierta desde el 03/09

**Nueve días.** No es trabajo de código: hay que contar el cajón y cerrarla, y eso lo hace el cliente. Es un recado para Mateo.

### C. Lo de antes, que sigue igual

- **Contraer `doc_photo_url`.** `00050` dejó las dos columnas sincronizadas a propósito; con el front desplegado, toca la migración que borra la vieja.
- Las cuatro decisiones de `frontend-starter/docs/DECISIONES_PENDIENTES.md`. **La §3 (desembolsar sin efectivo) tiene un precedente nuevo:** el retiro del dueño **sí** valida saldo, porque el argumento que sostiene la excepción del préstamo —el mostrador registra fuera de orden— no aplica a un acto deliberado.
- `fetchAllPages` cortando a 10.000 filas **en silencio** (F10-02).
- El bundle sin code-splitting.
- De `RECARGOS.md` §9: si se pueden dejar prendas nuevas al ampliar, y revisar qué autoriza `contracts.override_ltv` en la matriz de roles (hoy lo tienen **todos** los que pueden crear contratos, así que la rama "no puedes, pídeselo a alguien" no la ve nadie).

### D. Multi-caja / multi-sucursal

Aplazado. El disparador **no es el volumen de datos** sino **el primer cliente que abra un segundo local**. Correr `python scripts/qa/verificar_sedes.py` al dar de alta una empresa nueva; sale con código 1 si la premisa se rompió.

---

## Trampas que costaron tiempo (no repetirlas)

**`to_tsquery` acepta sintaxis y `plainto_tsquery` no.** Cambiar de uno a otro convierte un error de dedo del usuario en un 500. Si alguien vuelve a tocar `app/common/search.py`, los signos se descartan a propósito.

**Un test que pasa después de invertir una regla no cubría esa regla.** Los 26 del recargo siguieron en verde con el comportamiento opuesto.

**Un `limit 1` sobre un conjunto que puede tener más de un elemento es una suposición, no una consulta.** Ya costó tres veces.

**`multiplyMoney(valor, pct/100)` corrompe el monto.** Para eso está `percentOfMoney`.

**Las de antes, que siguen valiendo**

- **Un comentario del código puede estar mintiendo** — esta sesión volvió a pasar, en el `catch` vacío de `ExtendLoanPanel`.
- **`alter type ... add value` no se puede USAR en la misma transacción que lo declara.**
- **El orden de despliegue no es negociable:** el front genera sus tipos desde el `/openapi.json` **en vivo**. Backend primero, siempre.
- **`fly deploy` necesita su config:** `fly deploy --config fly.dev.toml --app compraventa-backend-dev`.
- **Sembrar estados de contrato solo se puede por `POST /contracts/import`.**
- **"listo para remate" no es un `status`**: es `in_extension` con la prórroga vencida.
- Las trampas del entorno (dos bases, dos cuentas de Supabase, nunca `supabase config push`) están en **`ESTADO.md` § "Trampas del entorno"**.

---

## Dónde está cada cosa

| Qué buscas | Dónde |
|---|---|
| Estado permanente del proyecto | `ESTADO.md` — **empezar por acá** |
| Mapa del producto y las piezas | `README.md` |
| **El capital del dueño (aportes y retiros)** | `backend-starter/docs/CAPITAL_DEL_DUENO.md` |
| El recargo (ampliar un préstamo) | `backend-starter/docs/RECARGOS.md` — **§4-bis primero**: §5 y §8.2 quedaron superadas |
| El modelo de efectivo | `backend-starter/docs/CAJA_TRAZABILIDAD.md` |
| Multi-caja y multi-sucursal (fase 2) | `backend-starter/docs/SUCURSALES.md` |
| Qué se probó, qué se encontró, cómo reproducirlo | `backend-starter/docs/QA_AUDITORIA.md` |
| Volver a correr esas pruebas · sembrar datos | `backend-starter/scripts/qa/README.md` |
| Lo que la app espera que alguien **decida** | `frontend-starter/docs/DECISIONES_PENDIENTES.md` |
| Registro vivo de qué se construyó y por qué | `frontend-starter/docs/IMPLEMENTATION.md` |
| Contrato de la API y catálogo de errores | `backend-starter/docs/API_GUIDE.md` (§13-bis capital, §15 los códigos) |
| Multi-tenancy, RLS, capas, errores, deploy | `backend-starter/docs/ARCHITECTURE.md` |
| Tokens, componentes, protocolos de UX | `frontend-starter/docs/DESIGN_SYSTEM.md` |
| Problemas de alta de usuarios | `RUNBOOK_USUARIOS.md` |
