# Recomendaciones — qué construir después y por qué

> **Qué es.** El único documento de recomendaciones de mejora del producto (fase 14 de la auditoría integral,
> 30/09/2026). Compara Prendo con cómo trabaja el software profesional de punto de venta y de casas de empeño, y
> propone qué adoptar, con el porqué, el costo y el riesgo. **No es una lista de bugs** (esa es
> [`QA.md`](QA.md) §4) ni de decisiones de negocio abiertas (esas están en [`ESTADO.md`](ESTADO.md) §4); las
> ideas sueltas de [`QA.md`](QA.md) §5 están integradas aquí.
>
> **Cómo se mantiene.** Al construir una recomendación, sale de aquí en el mismo commit y la regla nueva va a
> [`DOMINIO.md`](DOMINIO.md). Todo lo que dice «existe» o «no existe» se verificó contra el código el 30/09/2026;
> antes de construir, se vuelve a verificar (el código es la fuente de verdad, [`QA.md`](QA.md) §1).
>
> **Sobre otras apps.** Donde se nombra un producto (Shopify POS, Square, Bravo, PawnMaster) es por lo que la fase 9
> de la auditoría dejó registrado como conocido y general de ese producto. Lo demás se describe como **práctica
> común** de POS o de software de empeño, sin atribuirlo a una app concreta.
>
> **Sobre lo legal.** Prendo no tiene concepto de abogado. Todo lo marcado ⚖️ **se verifica con un abogado (o un
> contador, si es tributario) antes de construirlo o de venderlo como cumplimiento**.

**Escala de esfuerzo:** **S** = hasta 2 días · **M** = 3 a 10 días · **L** = más de dos semanas (una persona, con
pruebas y documentación). **Prioridad:** **P0** = antes del segundo cliente · **P1** = el próximo trimestre ·
**P2** = cuando haya tracción · **P3** = oportunista.

---

## 1. Resumen ejecutivo: las 10 de mayor impacto

| # | Qué | Por qué | Esfuerzo | Impacto | Prioridad |
|---|---|---|---|---|---|
| 1 | **CI en verde en cada push, y bloqueante** | Las dos CI existen y fallan en todos los pushes recientes: la del back no pasa de aplicar migraciones (usa `postgres:15` pelado, sin los roles de Supabase) y la del front falla en Vitest y en `gen:api:check`. Una CI que siempre falla no avisa de nada | S–M | Alto | **P0** |
| 2 | **Producción con backups restaurados de verdad, y dev convertido en staging** | Solo existe dev y ahí opera el primer cliente con datos reales: no hay dónde ensayar un deploy, y nunca se ha probado restaurar un backup (las fotos de Storage no entran en el backup de la base) | L | Crítico | **P0** |
| 3 | **Monitoreo: errores, disponibilidad y job nocturno** | Sentry está listo en el back pero apagado (sin DSN) y no existe en el front; el health no toca la base; nadie se entera si el job nocturno no corrió | S | Alto | **P0** |
| 4 | ⚖️ **Base legal del SaaS**: términos, política de datos, contrato de encargo, derechos del titular, tope de tasa | La landing no tiene términos ni política; no hay forma de atender «conozca/suprima mis datos» sin SQL a mano; ningún contrato valida la tasa contra un tope | M | Crítico para vender | **P0** |
| 5 | **Autorización de supervisor en el mostrador** (otro usuario autoriza con su PIN) | Hoy una excepción (descuento, LTV, devolución fuera de plazo) obliga a que el dueño inicie sesión; por eso el descuento en abonos no tiene pantalla y hay cuatro decisiones abiertas que son la misma pregunta | M | Alto | **P1** |
| 6 | **Mostrador centrado en el cliente** + búsqueda global + cierre de venta con recibo | En software de empeño la operación central es «buscar cliente → ver sus préstamos → cobrar/renovar/rescatar». En Prendo son varias pantallas y no hay buscador global | M | Alto | **P1** |
| 7 | **Recordatorios y recibos por WhatsApp**, primero manual (enlace), después por API | El cliente casi nunca da correo (2 de 16 en el primer cliente); da el celular. Todo el motor de avisos, con la Ley 2300, ya existe y hoy no llega a nadie | S (manual) · L (API) | Alto (recuperación de cartera) | **P1** |
| 8 | **Tasación asistida por peso y precio del gramo**, y fotos obligatorias por categoría | `weight_grams` ya existe y no se usa para nada; las fotos son opcionales en todas las categorías. Un préstamo mal tasado o una prenda sin foto es plata en riesgo y un reclamo sin defensa | M | Alto | **P1** |
| 9 | **Arqueo ciego y conteo por denominación guardado** | El conteo por denominación existe al cerrar, pero no se guarda y el esperado se ve antes de contar: el cajero puede «cuadrar» en vez de contar | S–M | Medio-alto | **P1** |
| 10 | **Onboarding de una empresa nueva**: categorías de partida, empresa de demostración, lista de pasos en la app | El alta crea roles, cuentas y caja, pero ninguna categoría; un cliente pasó once días sin crear un contrato por no abrir caja. Vender exige mostrar el producto con datos | M | Alto para vender | **P2** |

Lo que no entra en el top 10 pero es barato y vale la pena: code-splitting y caché de assets (S, §4.6), la casilla
«Enviar comprobante» del mostrador (S, el back ya lo acepta, §2.2), E2E versionada (M, §4.2) y el laboratorio en un
subdominio propio (S, §4.8).

---

## 2. Flujos de negocio

### 2.1 Empeño

#### a) Mostrador centrado en el cliente (top 10 #6)

- **Qué hace el software de empeño profesional.** La pantalla de trabajo es la **ficha del cliente**: sus
  préstamos vivos con el estado en grande (vigente, días de mora, fecha de remate), y en cada uno los botones
  cobrar interés, renovar, ampliar, rescatar. El cálculo del préstamo se muestra antes de emitir la boleta.
- **Qué tiene Prendo.** La búsqueda de contratos ya encuentra por nombre y cédula del cliente
  (`contracts/repository.py`, cláusulas de `q`), la ficha del cliente lista sus contratos, y la tanda H hizo
  visibles mora y prórroga en el detalle. Falta el recorrido: desde la ficha no se cobra, y cada acción es otra
  pantalla.
- **Cómo se vería.** En la ficha, una tarjeta por contrato vivo con «debe hoy», estado y los botones de acción que
  abren el mismo diálogo del detalle del contrato (sin endpoint nuevo: `payment-options` ya da los montos). En
  «Nuevo contrato», un resumen previo: capital, tasa, interés mensual, vencimiento, fecha a partir de la cual puede
  rematarse. Es la idea P3-13 de la fase 9.
- **Esfuerzo M · riesgo bajo** (solo front, reutiliza diálogos).

#### b) Autorización de supervisor con PIN (top 10 #5)

- **Práctica común en POS**: el *manager override*. Cuando el cajero hace algo que su rol no permite (descuento,
  devolución fuera de plazo, anulación, reabrir caja), aparece un recuadro donde **otra persona** con el permiso
  digita su PIN o sus credenciales **en esa misma pantalla**; la operación queda registrada como hecha por el
  cajero y **autorizada por** el supervisor.
- **Por qué aquí.** Prendo ya modela bien el *quién puede* (43 permisos, los especiales auditados), pero la única
  forma de ejercer un permiso es tener la sesión iniciada. La rama «pídeselo a un responsable» existe en el
  diseño de `contracts.override_ltv` (DOMINIO §11) y en la práctica obliga a cerrar la sesión del asesor o a
  darle el permiso a todos, que es lo que pasó con 00051. Cuatro puntos abiertos de [`ESTADO.md`](ESTADO.md) §4 se
  resuelven con este mismo mecanismo:
  - descuento sobre intereses en un abono (`payments.apply_discount` sin pantalla),
  - desembolsar más efectivo del que hay en el cajón (un permiso para pasarse, como `override_ltv`),
  - devolución fuera de plazo (`sales.return_override_time_limit` sin aviso en pantalla),
  - topes en retiros de capital y ajustes de arqueo.
- **Cómo se vería.** Un PIN numérico por usuario (hash en la base, nunca en claro; bloqueo tras varios intentos;
  no reemplaza la contraseña de la sesión). El endpoint que exige un permiso especial acepta, además del JWT, un
  `authorized_by` + PIN; el backend verifica que ese usuario **de la misma empresa** tenga el permiso y guarda
  ambos en la auditoría y en el documento. En el front, un único componente `SupervisorApproval` que aparece
  cuando la respuesta es `PERMISSION_DENIED` en una acción que lo admite.
- **Esfuerzo M · riesgo medio**: toca el núcleo de autorización. Va con tests de permiso en las dos puntas
  ([`QA.md`](QA.md) §1.3), límite de intentos y una revisión de seguridad propia antes de desplegar. No se usa el
  PIN para nada que no sea autorizar una excepción puntual.

#### c) Tasación asistida por peso y precio del gramo (top 10 #8)

- **Práctica común en empeño de joyería**: el avalúo de oro se calcula como **peso × pureza (quilates) × precio
  del gramo del día**, y el préstamo como un porcentaje de eso. El precio del gramo cambia a diario y lo fija el
  negocio (o lo toma de una referencia).
- **Qué tiene Prendo.** `contract_item.weight_grams` existe y se imprime; el LTV por categoría existe y se hereda
  por el árbol; el avalúo es un número digitado. **Nada conecta peso con avalúo.**
- **Cómo se vería.** En la configuración, una tabla «precio de compra del gramo» por pureza (10k, 14k, 18k, 24k…),
  con fecha y quién la cambió (auditado; un precio viejo no se sobrescribe, se versiona). En la prenda de una
  categoría marcada «se tasa por peso», se pide peso y pureza, y el avalúo sale **sugerido** (editable, con el
  mismo `override_ltv` si se pasa). El contrato guarda el precio usado en su snapshot legal, como ya guarda la tasa.
  Primero con precio digitado por la empresa; una fuente externa del precio del oro, solo si los clientes lo piden
  (§6).
- **Esfuerzo M · riesgo bajo** (aditivo; la tasación sigue siendo decisión de una persona).

#### d) Fotos obligatorias por categoría (top 10 #8)

- **Por qué.** La foto de la prenda es la defensa del negocio ante «me devolvieron otra cadena» y la trazabilidad
  que viaja al inventario cuando se remata (ya viaja, DOMINIO §2.4). Hoy `photos` es un arreglo opcional en todas
  las categorías, y la regla de «foto obligatoria» solo existe al publicar una pieza única en la tienda.
- **Cómo se vería.** `category.min_photos` heredable por el árbol como el plazo (celulares 2: frente y reverso con
  IMEI visible; oro 1; herramienta 0). El backend lo exige al crear el contrato con un código propio; el front lo
  muestra junto al campo de fotos.
- **Esfuerzo S · riesgo bajo.**

#### e) Remate: liquidación en bloque

- **Qué hace el rubro.** Lo rematado no siempre se vende en vitrina: el oro de baja rotación se vende **por peso a
  una fundición o a otro comprador**, en lote.
- **Qué tiene Prendo.** El remate es asistido y está bien resuelto (DOMINIO §2.4): cada prenda nace como artículo en
  borrador con su costo. Para venderla hay que publicarla con precio y venderla línea por línea.
- **Cómo se vería.** Una acción «Liquidar en bloque» sobre artículos rematados en borrador: se eligen piezas, se
  pone un precio por gramo o un total, y sale **una venta** a un cliente-comprador, con el costo congelado de cada
  pieza (la utilidad queda bien medida sin reglas nuevas). Subastas en línea, no (§6).
- **Esfuerzo M · riesgo medio** (toca ventas e inventario; el reparto del total entre piezas debe ser por avalúo,
  como ya lo hace el remate).

#### f) ⚖️ Tope de tasa y avisos formales

- **Tasa de usura.** Prendo guarda la tasa pactada de cada contrato y no la compara con nada. En Colombia existe un
  tope legal de interés que se certifica periódicamente; **cómo aplica a una compraventa (pacto de retroventa o
  prenda) es exactamente la pregunta para un abogado**. Si aplica, la recomendación es barata: una tabla de topes
  con vigencia (la carga el super-admin) y un aviso o bloqueo al crear un contrato por encima. **Esfuerzo S.**
- **Aviso formal de remate (R5 certificado)**: ya anotado como mejora en DOMINIO §13; depende del mismo concepto.

### 2.2 Tienda (POS)

- **Lo que hace el POS profesional** (Shopify POS, Square, según la fase 9): el buscador o el escáner está listo sin
  tocar nada; efectivo recibido y cambio; al cerrar la venta, en la misma pantalla, **imprimir o enviar el recibo**
  y «Nueva venta»; botones grandes para pantalla táctil.
- **Ya hecho** (tanda H, 30/09): vuelto en el POS; aviso de caja cerrada antes de llenar; Enter ya no registra
  dinero.
- **Falta, en orden de costo:**
  1. **Casilla «Enviar comprobante a <correo>»** al cobrar venta y abono. El backend ya acepta `send_receipt_email`
     (00066, DOMINIO §9.2); el front no la usa. Primero el backend debe exponer a quien vende si el interruptor
     general de correos está encendido (p. ej. en `/me`). **S.**
  2. **«Enviar por WhatsApp»** en el comprobante: un enlace `wa.me` con el número del cliente y un texto con el
     resumen (número, total, medio, fecha). Sin API, sin costo, sin enlace público (un enlace de un solo uso lo
     quemaría la vista previa del chat). **S.**
  3. **Cierre de venta con recibo y «Nueva venta»**, foco automático al escáner (idea P3-14 de la fase 9). **S–M.**
- **Descuentos**: hoy exigen el permiso en la sesión activa; con el supervisor con PIN (§2.1 b) el asesor vende y el
  dueño autoriza sin cambiar de usuario.

### 2.3 Caja

#### a) Arqueo ciego y denominaciones guardadas (top 10 #9)

- **Práctica común en control de efectivo**: el **arqueo ciego**. El cajero cuenta **sin ver** cuánto debería
  haber; el sistema compara después. Si ve el esperado antes, la tentación es digitar el esperado y justificar
  «redondeo».
- **Qué tiene Prendo.** El cierre muestra `expected_cash` y luego pide `counted_cash` (`CloseSessionDialog`). Existe
  un contador por denominación (`DenominationCounter`, billetes y monedas COP) que suma en pantalla pero **no se
  envía**: el backend solo recibe el total.
- **Cómo se vería.** Una preferencia de empresa «arqueo ciego» (encendida por defecto en empresas nuevas): el
  esperado aparece **después** de registrar lo contado. El detalle por denominación viaja y se guarda con el cierre
  (JSON en la sesión) y sale en el acta; también en la apertura. La regla de «toda diferencia exige justificación»
  no cambia.
- **Esfuerzo S (ciego, solo front) + S (guardar denominaciones: migración aditiva y acta) · riesgo bajo.**

#### b) Validar saldo al desembolsar

Decisión abierta en [`ESTADO.md`](ESTADO.md) §4: préstamo y gasto no validan saldo del cajón; traslado y retiro sí.
Recomendación: **validar siempre, y permitir pasarse con autorización de supervisor** (§2.1 b). Un cajón en negativo
no es un número posible, y el primer cliente ya tiene uno por abrir sin registrar el efectivo inicial. **S** una
vez exista el supervisor.

#### c) Conciliación bancaria ligera

- **Qué tiene Prendo.** El extracto por cuenta existe (`accounts/service.py`, «para conciliar contra el del
  banco»), y la liquidación de convenios deriva la comisión.
- **Lo que falta** es marcar qué movimientos ya aparecieron en el extracto del banco. **Primera versión (M):** una
  casilla «conciliado» por movimiento en cuentas `bank`/`settlement`, con fecha y quién, y un saldo «conciliado vs.
  en tránsito». **Segunda versión (L, §6):** importar el extracto (CSV del banco) y emparejar por monto y fecha.
  Integración directa con bancos, no por ahora.

#### d) Alertas que faltan

Anotadas en [`ESTADO.md`](ESTADO.md) §4 y coherentes con el catálogo A1–A4: **alerta de descuadre de arqueo** sobre
un umbral (quinto tipo) y tope por monto en retiros de capital. **S** cada una, sobre el motor que ya existe.

### 2.4 Reportes

- **Lo que ya está por delante del rubro** (fase 9): textos que enseñan contabilidad al dueño, una definición por
  concepto, el estado de resultados que lee documentos. Eso no se toca.
- **Recomendado** (de [`QA.md`](QA.md) §5, verificado como no construido):
  - **Alertas en la propia pantalla**: contratos que entran en mora esta semana, gastos que suben sobre un umbral
    (`computeDelta` ya da el dato). **S.**
  - **Proyección de vencimientos** de los próximos N días (cuánto capital vence y cuánto interés se espera): es la
    pregunta de flujo de caja del dueño de una compraventa. **M.**
  - **Rotación de inventario** (disponibles hace más de N días) y **comparación año contra año**. **S–M.**
  - **Ranking por operador** (quién presta, quién vende, quién descuenta): antes, confirmar que la API expone el
    autor de cada venta y abono. **M.**
  - **Auditoría legible**: una frase («María aplicó un descuento de $20.000 al contrato #128») en vez del JSON de
    `before`/`after`. **M.**
- ⚖️ **Reportes regulatorios.** Es frecuente que las normas locales y de policía exijan a las compraventas llevar un
  **registro de lo que reciben** (quién lo trajo, con su documento, qué es, con serial o peso, cuándo) y tenerlo a
  disposición de la autoridad; y las operaciones en efectivo pueden tener obligaciones de reporte por prevención de
  lavado de activos. **No se verificó qué aplica, en qué formato ni con qué periodicidad.** La buena noticia: Prendo
  ya tiene todos esos datos (cliente con cédula, prenda con descripción, serial/IMEI y peso, fecha, foto), así que
  el reporte sería una exportación. Preguntar a un abogado antes de venderlo como cumplimiento. Igual con la
  **facturación electrónica DIAN** de las ventas de tienda: está fuera de alcance por decisión (DOMINIO §13), pero
  si un cliente está obligado a facturar, Prendo le resuelve la mitad del mostrador; conviene saberlo con un
  contador antes de la venta.

### 2.5 Multi-sucursal

El diseño completo está en [`diseno/SUCURSALES.md`](diseno/SUCURSALES.md) y las tres adecuaciones previas ya están
hechas. **Se mantiene la decisión: se construye cuando llegue el primer cliente con un segundo local**, no antes
(§6). Lo único recomendable ahora es lo que el propio diseño pide: correr `verificar_sedes.py` en cada alta y no
aceptar el rodeo de «una empresa por sede».

---

## 3. UI/UX

El detalle (64 hallazgos F9-01…F9-64, mediciones de contraste y desborde, y las 18 ideas de rediseño P1–P3) está en
el informe de la fase 9, `auditoria_2026-09/17_fase9_uiux.md` (carpeta privada del workspace, fuera del repo). Las
reglas vigentes del front: [`frontend-starter/docs/DESIGN_SYSTEM.md`](../../frontend-starter/docs/DESIGN_SYSTEM.md)
y [`frontend-starter/docs/ARQUITECTURA.md`](../../frontend-starter/docs/ARQUITECTURA.md). Aquí va solo la
recomendación de **orden**.

### 3.1 Patrones a adoptar del rubro

| Patrón | Estado | Recomendación |
|---|---|---|
| Efectivo recibido y cambio en el POS | hecho (tanda H) | — |
| Confirmación de dinero con resumen («abono de $50.000 al #6 de X, en efectivo…») | hecho en el abono (tanda H) | extenderlo a préstamo, venta, gasto y traslado con el mismo componente |
| Acción de dinero bloqueada por adelantado con la caja cerrada | hecho (tanda H) | — |
| Ficha del cliente como centro del mostrador | no | §2.1 a |
| Búsqueda global (cliente, contrato, código de artículo) | no; el back ya tiene `?q=` en cada listado | **S–M**, un cuadro en la barra superior con atajo de teclado |
| Recibo y «Nueva venta» al cerrar | no | §2.2 |
| Objetivos táctiles de 44 px en móvil | no | con el rediseño P3 |
| Autorización de supervisor en pantalla | no | §2.1 b |

### 3.2 El rediseño visual, en fases

1. **P1 — plata y confianza, antes de cualquier cambio visual.** MoneyInput, KPI que no se pisan, bloqueo con caja
   cerrada y confirmaciones con resumen: **en su mayoría ya hechos** (tandas G2 y H). Queda extender la confirmación
   con resumen a todas las acciones de dinero.
2. **P2 — sistema de diseño.** Un solo `Input`/`Field` (hoy hay 27 copias de `inputClass`), semántica de color
   (rojo = requiere acción, verde = entra plata, neutro = saldos), un solo primario por pantalla, tablas con fila
   enlazable y dinero a la derecha, barra de acción fija en formularios largos, formato único es-CO. **Es la fase
   que más rinde**: cada pantalla nueva sale bien sin pensarlo. **M.**
3. **P3 — por rol y rendimiento.** Inicio por rol, detalle de contrato centrado en la acción, POS con cierre de
   venta, Reportes con índice en vez de 4.500 px de scroll, páginas de salida con marca, code-splitting. **M–L**,
   pantalla por pantalla.

**Recomendación de método:** propuesta visual primero (capturas o un prototipo de dos o tres pantallas: detalle de
contrato, POS, Inicio), aprobación, luego tokens y componentes, y al final pantallas. No rediseñar pantallas sueltas
antes de tener el `Field` único: cada una tendría que rehacerse.

### 3.3 App instalable

Un manifest y un ícono para «agregar a la pantalla de inicio» en la tableta del mostrador: **S**, útil. **Nunca modo
offline para dinero**: caja, idempotencia y estados viven en el servidor (§6).

---

## 4. Ingeniería y operación

### 4.1 CI en verde y bloqueante (top 10 #1)

- **Evidencia (30/09/2026, `gh run list`):** en el back, `lint-and-unit` pasa y `integration` falla en todos los
  pushes al aplicar `00003_identity.sql` (`role "supabase_auth_admin" does not exist`: la CI levanta `postgres:15`
  pelado y Supabase real es Postgres 17 con sus roles). En el front, `Tests (Vitest)` falla en CI (localmente pasan
  655) y `api-drift` falla; su `VITE_API_URL` por defecto sigue apuntando al host viejo de Fly.
- **Cómo se vería.**
  1. Back: el job de integración con `supabase start` (misma versión de Postgres, Auth y Storage que dev) y
     `supabase db reset`, que además prueba **las migraciones desde cero**, cosa que hoy nadie verifica.
  2. Front: reproducir el fallo de Vitest en CI (entorno, zona horaria o locale son sospechosos habituales en un
     proyecto con fechas de Bogotá y formato es-CO); `vars.VITE_API_URL` a `api-dev.prendo.com.co`.
  3. **Protección de rama**: `main` (la de producción) solo por PR con la CI en verde.
- **Esfuerzo S–M · riesgo bajo.** Es la recomendación más barata del documento con el mayor retorno: hoy todo lo
  demás de esta sección depende de que alguien corra la suite a mano por tramos.

### 4.2 E2E con Playwright versionada

- **Hoy:** los recorridos de UI son scripts sueltos (`scripts/qa/ui_*.js` en el back, más los de cada fase de la
  auditoría fuera del repo), corren con el Playwright de la caché de `npx` y Chrome del sistema, y nadie los corre
  de forma periódica.
- **Cómo se vería.** `@playwright/test` como dependencia de desarrollo del front, carpeta `e2e/` con **cinco a
  ocho flujos críticos** (login, abrir caja, crear contrato, abonar, vender con vuelto, cerrar caja con diferencia,
  remate, reportes del día), contra una empresa de laboratorio propia. Corren **cada noche contra dev** y a mano
  antes de un deploy de producción, no en cada push (necesitan un back vivo). Fixtures copiados de respuestas
  reales ([`QA.md`](QA.md) §1.5).
- **Esfuerzo M · riesgo bajo.** Es la fase 15 del plan de auditoría.

### 4.3 Monitoreo (top 10 #3)

- **Errores.** Back: `app/core/observability.py` ya inicializa Sentry si hay `SENTRY_DSN` y limpia cabeceras,
  cookies y cuerpo antes de enviar; **solo falta el DSN**. Front: no hay captura de errores del navegador; agregar
  el SDK con el mismo cuidado (sin datos personales, sin cuerpos de request) y los *source maps* subidos en el build.
  **S.**
- **Disponibilidad.** Un monitor externo sobre la API y el front con alerta al celular, y un health **profundo**
  (`select 1`) en una ruta aparte del que usa Fly, para no reiniciar máquinas por una caída de la base. **S.**
- **Job nocturno.** Los guardianes vigilan que la Machine exista y tenga su programa, no que **haya corrido**. Una
  alerta por ausencia del log de fin del job en 26 horas cierra el hueco, y resuelve de paso la hipótesis abierta
  JOB-sched (la hora que cambia tras un `machine update`). **S.**

### 4.4 Producción, backups y staging (top 10 #2)

- El paso a paso de producción ya está escrito ([`PRODUCCION.md`](PRODUCCION.md)). Lo que se recomienda **agregar**:
  1. **Restaurar un backup de verdad** a un proyecto temporal antes de meter datos reales, y después cada
     trimestre. Un backup que nunca se restauró es una hipótesis.
  2. **Exportar Storage** (fotos de prendas y documentos de identidad) periódicamente, porque no entra en el backup
     de la base; con acceso restringido, por ser datos personales sensibles.
  3. **Staging**: cuando exista producción y el primer cliente viva ahí, **dev deja de tener datos reales** y se
     convierte en el ensayo de cada deploy. Antes de eso, cada deploy a dev es un deploy a producción.
  4. Un `deploy_prod.sh` equivalente al de dev, que actualice también la Machine del job (la trampa de que no la
     tocan ni `fly deploy` ni `fly secrets set`).
  5. ⚖️ **Plan del hosting del front**: confirmar que el plan de Vercel en uso admite uso comercial; los planes
     gratuitos de estas plataformas suelen ser para uso personal.
- **Esfuerzo L · riesgo alto si se hace sin ensayo**; el runbook lo mitiga.

### 4.5 Seguridad (en términos de práctica)

Los hallazgos concretos viven fuera del repo, que es público. Como práctica recomendada antes de producción:
defensa en profundidad en los privilegios de la base (mínimos, no solo RLS), límites de uso en todo endpoint que
envía correo, auditoría de dependencias en la CI (`pip-audit` y `npm audit`, o Dependabot), rotación documentada de
tokens y llaves, y tokens de despliegue con el alcance mínimo. **Un SaaS con clientes normalmente tiene sus
repositorios privados**: conviene decidirlo antes de producción, porque la historia de git también se publica.

### 4.6 Code-splitting y caché de assets

- **Evidencia (fase 9):** bundle único de 1,9 MB (≈ 520 KB comprimido) que el login, el POS y la landing descargan
  enteros, con Reportes, gráficas y el editor de plantillas; `vercel.json` no pone caché a `/assets/*`, que se
  sirve con `max-age=0`; LCP de 4,6 s en el Inicio móvil. Solo el editor de plantillas es *lazy* hoy.
- **Cómo se vería.** Carga diferida por ruta (Reportes, Configuración y Documentos, Plataforma) y
  `Cache-Control: public, max-age=31536000, immutable` para `/assets/*` (los nombres llevan hash). Medir LCP antes
  y después.
- **Esfuerzo S · riesgo bajo.** Ojo con que un deploy nuevo deje a una pestaña abierta pidiendo un trozo que ya no
  existe: recargar al fallar la carga de un trozo.

### 4.7 El test intermitente

`test_platform::test_get_and_list_companies_include_plan_and_subscription` falla en la suite completa y pasa sola:
casi siempre es dependencia de orden (datos que deja otro test, o un listado que asume cuántas empresas hay).
Correrlo con orden aleatorio y semilla fija para reproducirlo; mientras tanto, marcarlo y documentarlo, no
reintentarlo en silencio. **S.** Con la CI en verde, un intermitente pasa a ser urgente: una CI que falla al azar
se aprende a ignorar.

### 4.8 Laboratorio de QA en un subdominio propio

Los usuarios y clientes del laboratorio usan un dominio real de un tercero (LAB-01): si una empresa de laboratorio
enciende avisos, salen correos a ese dominio y los rebotes dañan la reputación de `prendo.com.co`. Migrarlo a un
subdominio propio **sin MX** (o con un buzón de laboratorio real, que además permitiría probar la baja por enlace
que la fase 8 no pudo). **S · riesgo bajo.**

### 4.9 Correo

DMARC publicado, prueba de spam, y el **webhook de Resend** (entregado/rebotado → `email_invalid_at`) antes de
encender avisos en cualquier empresa: sin él, un correo que rebota se sigue intentando. Separar el remitente de
dev del de producción. **S.**

---

## 5. Producto y negocio del SaaS

### 5.1 Onboarding de una empresa nueva (top 10 #10)

- **Hoy** ([`OPERACION.md`](OPERACION.md) §8): el super-admin crea la empresa (roles, cuentas, caja, suscripción) y
  entrega el enlace; el admin configura a mano datos, logo, plantilla, **categorías con plazo, ventana y LTV**,
  cuentas y usuarios. El alta no crea ninguna categoría, y sin categoría de nivel 3 con plazo no se puede crear un
  contrato. El primer cliente pasó once días sin crear uno por no abrir caja.
- **Cómo se vería.**
  1. **Categorías de partida** al crear la empresa, editables: un árbol típico de compraventa (oro por pureza,
     celulares, cómputo, herramienta, electrodomésticos) con plazos y ventanas razonables, marcados como
     sugerencia. **S.**
  2. **Lista de pasos en el Inicio** del admin hasta completar lo mínimo: datos de empresa, plantilla con la
     cláusula de avisos, categorías revisadas, cuentas reales, abrir la primera caja. Desaparece al terminar. **S–M.**
  3. **Empresa de demostración**: una empresa con datos sintéticos (clientes, contratos en todos los estados,
     ventas, un mes de caja) para mostrar el producto en una venta sin tocar datos reales. `seed_contratos.py` y el
     import ya siembran contratos en cualquier estado; falta empaquetarlo. **M.** Nunca con nombres o cédulas
     reales.

### 5.2 Facturación de la suscripción

- **Hoy:** manual; el super-admin amplía `expires_at` y el job bloquea al vencer. Precios fuera del sistema.
- **Recomendación:** **mantenerlo manual hasta unos cinco o diez clientes**; el costo de integrar una pasarela no se
  paga antes. Mientras tanto, dos cosas baratas: un **aviso de vencimiento** al admin de la empresa (7 y 1 días antes;
  el motor de avisos ya existe) y un **período de gracia** configurable antes del bloqueo, para no cortarle la caja a
  un negocio abierto un sábado por una transferencia demorada. **S.** Después: pasarela colombiana con cobro
  recurrente y el tope de usuarios por plan (`max_users`, hoy no existe la columna). ⚖️ La suscripción que cobra
  Prendo sí necesita su propia factura electrónica: verificar con un contador.

### 5.3 ⚖️ Términos, política de datos y Ley 1581 (top 10 #4)

- **Hoy:** la landing no tiene términos de servicio ni política de privacidad; la plantilla de contrato ya trae una
  cláusula de autorización de avisos (bien hecha, con la finalidad y la base por cliente); no hay forma de atender
  un derecho del titular (conocer, actualizar, suprimir) sin SQL a mano.
- **Recomendado:**
  1. **Términos del servicio y política de tratamiento de datos de Prendo**, enlazados desde la landing y el login.
  2. **Contrato de encargo del tratamiento** con cada empresa: cada compraventa es la responsable de los datos de sus
     clientes y Prendo el encargado; hay que dejarlo por escrito, con dónde se alojan los datos (fuera de Colombia,
     lo que es una transferencia o transmisión internacional).
  3. **Exportar y anonimizar un cliente** desde la app: la exportación es un reporte; la anonimización borra nombre,
     documento, contacto y fotos de identidad **y conserva los documentos contables** (un contrato, un abono o una
     venta no se borran, DOMINIO §1). **M.**
  4. Plan de limpieza de datos reales en dev una vez que exista producción.
- **Esfuerzo M (código) + el tiempo del abogado.**

### 5.4 Soporte

- Un canal único y visible: el buzón `contacto@prendo.com.co` que la landing publica **y hoy no recibe**
  ([`ESTADO.md`](ESTADO.md) §2), más WhatsApp del negocio. **S.**
- En la app, «Ayuda» en el menú con la guía de usuario y el contacto. **S.**
- Para diagnosticar sin pedirle capturas al cliente: el panel de plataforma ya ve empresas; lo siguiente sería ver
  el **estado de configuración** de una empresa (categorías, caja abierta, suscripción: la consulta de
  [`OPERACION.md`](OPERACION.md) §7 hecha pantalla). **Entrar como el usuario del cliente, no** (§6).

### 5.5 Métricas de uso

- **Hoy no hay ninguna** (ni analítica en el front ni métricas por empresa).
- **Recomendado:** métricas **del lado del servidor y agregadas por empresa**, en el panel de plataforma: último
  ingreso, contratos y ventas por semana, usuarios activos, avisos enviados. Salen de tablas que ya existen y
  responden lo que importa a un SaaS pequeño: ¿quién está dejando de usarlo? **S–M.** Analítica de terceros en el
  navegador, no por ahora: sube la superficie de datos personales y el CSP, para responder preguntas que el panel ya
  contesta.

---

## 6. Lo que NO recomiendo hacer todavía

| Qué | Por qué no, por ahora | Cuándo sí |
|---|---|---|
| **Multi-sucursal** | Diseño listo y adecuaciones hechas ([`diseno/SUCURSALES.md`](diseno/SUCURSALES.md)); construirlo sin un cliente real con dos locales es adivinar sus reglas (quién ve qué sede, traslados de mercancía) | el primer cliente con un segundo local |
| **Modo offline** | La caja, la idempotencia y los estados viven en el servidor; un cobro offline que se sincroniza tarde es exactamente el doble cobro que la auditoría acaba de cerrar | nunca para dinero |
| **Facturación electrónica DIAN propia** | Es un producto aparte (numeración autorizada, proveedor tecnológico, contingencias); fuera de alcance por decisión | si varios clientes lo exigen para comprar; primero integrar un proveedor, nunca construirlo |
| **Recordatorios por WhatsApp vía API** antes del enlace manual | La API exige plantillas aprobadas, costo por conversación y revisión legal de cobranza; el enlace `wa.me` prueba primero si los clientes lo usan | cuando el enlace manual se use y el volumen lo justifique |
| **Precio del oro desde una API externa** | Cada compraventa compra a su propio precio, que no es la cotización internacional; una dependencia externa más que puede caerse a las 8 a. m. | si varios clientes lo piden |
| **Tasación automática por foto o IA** | Riesgo de préstamo mal tasado con responsabilidad de Prendo; el valor está en ayudar a una persona a tasar (§2.1 c), no en reemplazarla | no en este horizonte |
| **Subastas en línea del rematado** | Otro negocio (pagos en línea, envíos, reputación); el rematado se vende hoy en vitrina o en bloque | si un cliente lo pide con volumen |
| **Contabilidad de partida doble / cierre de ejercicio** | Prendo no reemplaza al contador; su estado de resultados por período ya responde la pregunta del dueño | exportar a un software contable antes que construirlo |
| **Conciliación bancaria automática con bancos** | Integraciones frágiles y por banco; la versión con casilla (§2.3 c) cubre la necesidad | tras la versión con importación de CSV, si se usa |
| **Rediseño visual completo de una vez** | Sin el `Field` único ni el sistema de color, cada pantalla rediseñada habría que rehacerla | después de P2 (§3.2) |
| **Entrar a la cuenta de un cliente para dar soporte** | Rompe la trazabilidad (quién hizo qué) y exige consentimiento y auditoría propios | con un diseño explícito, si el soporte lo necesita |
| **Microservicios, colas o cambiar de stack** | El monolito modular con RLS aguanta con holgura el volumen de decenas de compraventas; el cuello de botella es producto, no infraestructura | si una métrica medida lo pide |
