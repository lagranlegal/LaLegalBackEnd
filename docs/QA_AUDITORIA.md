# Auditoría de QA — registro por fases

> **Qué es este archivo.** El registro de la auditoría de calidad de la aplicación: qué se probó, qué se encontró, qué se arregló y qué queda abierto. Una sección por fase, la más reciente arriba. Se actualiza al cerrar cada fase.
>
> **Qué NO es.** No es el estado del proyecto (`ESTADO.md`) ni el traspaso de la última sesión (`CONTINUAR.md`). Acá vive solo lo que sale de probar la app contra sus propias reglas.
>
> **Dónde vive y por qué.** Cruza los dos repos, pero está acá y no en la raíz del workspace para que quede **versionado**: la raíz no es un repo git. Vive en el backend porque la auditoría verifica reglas de negocio y esas viven acá — si alguna fase de UI genera mucho material propio, se puede partir entonces, no antes.
>
> Los scripts que produjeron todo esto están en [`scripts/qa/`](../scripts/qa/), con su propio README.

---

## Estado de las fases

| Fase | Alcance | Estado |
|---|---|---|
| **0** · Laboratorio | Empresas espejo, usuarios por rol, arsenal de scripts, mapa de endpoints | ✅ 08/09/2026 |
| **1** · Identidad, permisos y aislamiento | Matriz completa de permisos, roles, ciclo de vida del usuario, multi-tenancy, guards de UI | ✅ 08/09/2026 |
| **2** · Dinero y caja | Ciclo diario, arqueo sin tolerancia, reapertura, cuentas, traslados, idempotencia | 🟡 08/09/2026 — cerrada salvo lo que nace de contratos y ventas, que va con las fases 3-4 |
| **3** · Contratos | Snapshot legal, herencia de categoría, meses completos, máquina de estados, remate, import | ✅ 08/09/2026 |
| **4** · Inventario y tienda | Códigos y letras, producto vs lote, unidades, transformaciones, kardex, ventas, devoluciones | ⏳ |
| **5** · El círculo completo | Que cada operación de dinero aparezca a la vez en caja, reportes, auditoría y kardex | ✅ 08/09/2026 |
| **6** · UX, UI y accesibilidad | Estados de carga, mensajes, responsive, teclado, contraste, tema oscuro, impresión | ✅ 08/09/2026 |
| **7** · Regresión | Convertir lo encontrado en suite automatizada | ⏳ |

**Principios de método** (los mismos del proyecto, aplicados a probar):

- **Toda aserción de error va contra el `code`, nunca contra el status solo.** Un test que mira el status y no el código no cubre nada — le costó once días de trabajo a un cliente.
- **Cada permiso se prueba dos veces:** en la pantalla (¿oculta?) y en la API pelada con el JWT de ese rol (¿403?). La UI oculta, no protege.
- **Un test que pasa no prueba nada hasta que se ve fallar sin el fix.** Todo test nuevo de esta auditoría se ejecutó con el arreglo revertido, para confirmar que falla con el error exacto.






---

## Fase 6 — UX, UI y accesibilidad (08/09/2026)

**Veredicto: tres hallazgos, y los tres tienen fix en un solo lugar.** Ninguno es una pantalla rota; son cosas que se arreglan en un componente compartido o en `tokens.css`, que es exactamente el mecanismo que este proyecto ya usa para no tocar features una por una.

Lo medido con Playwright contra la app en vivo, con login real: 12 pantallas × 2 temas para el contraste, 12 × 3 anchos para el responsive, y los cuatro formularios largos.

### F6-01 · Los tres formularios largos no usan `revealFirstError` — MEDIA-BAJA, abierto

`CONTINUAR.md` lo dejó anotado: *«mismo patrón sin revisar en otros formularios largos (venta, transformación, ingreso): si alguien reporta "el botón no hace nada", empezar por acá»*. Confirmado: el helper existe, es genérico, y **solo lo usan `ContractFormPage` y `ContractImportPage`**.

No es que no muestren nada — los tres dan señal. Lo que falla es *cuál* señal se ve. Medido en **Nuevo ingreso**, enviando el formulario incompleto:

```
scrollY tras enviar: 469 · ventana visible del documento: 469 … 1269

y=  361  fuera    "Un ingreso de tipo «Compra» necesita un proveedor"   ← el más arriba
y=  888  VISIBLE  "El nombre es obligatorio"
y=  984  VISIBLE  "Selecciona una categoría"
y= 1080  VISIBLE  "Selecciona la categoría final"

foco tras enviar: lines.0.name
```

El error que está **más arriba en el documento** queda 108 px por encima de la vista, y el foco cae en el nombre del artículo. El usuario corrige lo que ve, reenvía, y vuelve a fallar por algo que nunca vio — que es la mitad del bug que se arregló en contratos el 03/09.

Los otros dos: **Nueva venta** muestra «Agrega al menos un artículo al carrito» y sí es visible (el formulario es corto y cabe). **Nueva transformación** usa otra estrategia: deshabilita el botón. Eso evita el clic muerto, pero el botón no dice por qué (sin `title` ni texto asociado) — el aviso está en la página, y hay que buscarlo.

**Fix:** aplicar el helper que ya existe, tres líneas por formulario. Y decidir si la transformación sigue con botón deshabilitado o se alinea con el resto.

### F6-02 · Doce combinaciones bajo WCAG AA en el tema claro; el oscuro está impecable — MEDIA, abierto

Amplía el H-03 de la Fase 1 (que encontró tres) a un barrido de 12 pantallas en los dos temas:

| Tema | Combinaciones por debajo de AA |
|---|---|
| **Claro** | **12** |
| **Oscuro** | **0** |

Que el tema oscuro —hecho después, con ~25 variables redefinidas— esté perfecto y el claro no, dice dónde está el problema: en el bloque original de `tokens.css`.

Las peores, por impacto:

| Ratio | Mín | Dónde |
|---|---|---|
| **2.70** | 4.5 | «+ Nuevo contrato» y todo CTA de texto teal — **en 10 de las 12 pantallas** |
| **2.70** | 3 | Cifras de KPI de 24px en el inicio |
| **2.77 / 2.97** | 4.5 | `--text-muted`: labels de tabla, hints, «Actualizado al…» — sistémico |
| **2.98** | 4.5 | «Caja abierta» en el banner global |
| **3.33** | 4.5 | La utilidad en Reportes, 18px |
| **1.97** | 4.5 | «Caja cerrada» sobre su fondo ámbar (medido en la Fase 1) |

**La parte buena: la marca no hay que tocarla.** `DESIGN_SYSTEM.md` §4.10 ya prescribe *«usar `--brand-600`+ para texto sobre claro»*, y los números dicen cuál sirve:

```
--brand-500  #00b19e   2.51   ✗
--brand-600  #009c8b   3.19   ✗
--brand-700  #00806f   4.53   ✓ pasa AA
```

O sea: **el token correcto ya existe y la guía ya lo pide; lo que falta es usarlo para texto.** Cero cambios de paleta, cero riesgo para el rebranding.

Para los semánticos sí hay que oscurecer. Valores calculados contra el fondo gris (el peor caso), conservando el tono:

| Token | Hoy | Ratio | Propuesta | Ratio |
|---|---|---|---|---|
| `--text-muted` | `#8a97a8` | 2.77 | `#647387` | 4.50 |
| `--success` | `#22a06b` | 3.10 | `#1b8056` | 4.58 |
| `--danger` | `#e5484d` | 3.65 | `#de2026` | 4.51 |
| `--warning` | `#e8a23d` | 2.02 | `#9e6513` | 4.52 |
| `--info` | `#3b82f6` | 3.43 | `#1268f4` | 4.54 |
| `--status-extension` | `#d97706` | 2.97 | `#ab5e05` | 4.51 |

Y para el texto de estado sobre su propio fondo suave: `warning` → `#9a6312` (4.58), `success` → `#1b7e54` (4.52), `danger` → `#d41e24` (4.56), `info` → `#0b63f3` (4.55).

**No lo apliqué**: cambia la cara de toda la app y esa es una decisión de producto, no de QA.

### F6-03 · Tres pantallas desbordan a 360 px, y la causa es un componente compartido — MEDIA-BAJA, abierto

`DESIGN_SYSTEM.md` §4.11 lo pone como regla dura: *«la operación diaria debe ser 100% usable en un teléfono de gama media — el mostrador puede ser un celular»*, y la Definición de Hecho del front pide «responsive verificado (360px y 1280px)».

| Pantalla | 360 px | 768 | 1280 | Culpable |
|---|---|---|---|---|
| `/caja` | **desborda 59 px** | ok | ok | El botón «Cerrar caja» llega a x=419 |
| `/cuentas` | **desborda 15 px** | ok | ok | Un `<path>` de ícono sobresale |
| `/contratos` | **desborda 14 px** | ok | ok | El botón «+ Nuevo contrato» llega a x=374 |

Las otras nueve pantallas pasan limpias en los tres anchos. **`/caja` es la más grave** porque es operación diaria de mostrador, justo el caso que la regla nombra.

La causa de `/caja` y `/contratos` es la misma: **la fila de acciones del `PageHeader` no envuelve en pantallas angostas**. Como es un componente compartido que usan todas las pantallas, se arregla en un solo sitio — y de paso previene las que vengan.

> **Lo que sí está bien y conviene no tocar:** en `/inventario` el botón «Transformaciones» llega a x=430 con el viewport en 360, pero **el documento no desborda** (`scrollWidth` = 360). Es la fila de pestañas dentro de su contenedor con scroll horizontal — el fix del 02/09 funcionando exactamente como debe.

### Lo que se probó y está bien

| Comprobación | Resultado |
|---|---|
| Tema oscuro, 12 pantallas | **Cero** problemas de contraste |
| Responsive 768 y 1280, 12 pantallas | Sin desbordes |
| Responsive 360, las otras nueve pantallas | Sin desbordes |
| Pestañas de Inventario a 360 | Scroll contenido, sin desbordar el documento (fix del 02/09) |
| Formulario de contrato incompleto | Sube a la vista, muestra los cinco errores y enfoca el primero (fix del 03/09) |
| Venta con carrito vacío | «Agrega al menos un artículo al carrito», visible sin scroll |
| Transformación vacía | Botón deshabilitado — no hay clic muerto posible |
| `--bg-muted` (#ebeef3) vs `--bg-app` (#f5f7fa) | Distintos: los skeletons se ven (fix del 28/08) |
| Dashboard sin `reports.view` | Nombra el permiso que falta y a quién pedírselo (Fase 1) |

---

## Fase 5 — El círculo completo (08/09/2026)

**Veredicto: el círculo cierra.** Cada peso movido en las fases 2, 3 y 4 aparece con el mismo número en la caja, en los reportes y en la auditoría, y las cuatro reglas contables que este proyecto pagó caras se cumplen. **Un solo hallazgo: una asimetría entre dos definiciones de ingreso dentro del mismo estado de resultados.**

### El arqueo cuadra al peso

```
base                                          500.000
+ pawn  in  efectivo   (interés + capital)  1.340.000
− pawn  out efectivo   (préstamos)          8.500.000
+ store in  efectivo   (venta)                180.000
− store out efectivo   (anulación, compras,
                        devolución)          2.490.000
− general out efectivo (gastos, traslados)     270.000
                                            ──────────
esperado en el cajón                       −9.240.000   ✓ exacto
```

Y cuenta **solo el efectivo**: quedan fuera los 80.000 del gasto por transferencia, los 3.000.000 cobrados por Sistecrédito y los 1.400.000 que entraron al banco al liquidar.

### Las cuatro reglas contables

| Regla | Cómo se comprobó |
|---|---|
| **El interés es ingreso; el capital recuperado no** | `total_revenue` = ventas + intereses. Los 8.500.000 desembolsados y los 1.050.000 recuperados van **fuera** del resultado, en campos propios |
| **Ingreso no es ganancia** | `gross_profit` = 3.480.000 − 2.145.000 de costo de ventas = 1.335.000; luego − 140.000 de gastos = 1.195.000 |
| **Una cuenta por cobrar no es plata** | La venta por Sistecrédito cuenta como ingreso (es un documento) pero **no entra a la caja**; el efectivo aparece recién al liquidar, y por lo cobrado, no por lo facturado |
| **Un traslado no es ingreso ni egreso** | Los 210.000 trasladados no aparecen ni en ingresos ni en gastos operativos (que son exactamente los 3 gastos: 140.000), y el arqueo **sí** los cuenta — si consignaste, esos billetes ya no están |

### F5-01 · El descuento de interés no se resta del ingreso; el de ventas sí — MEDIA, abierto

La asimetría está en dos líneas contiguas de `reports/service.py`:

```python
ventas    = _dec(t["gross_revenue"]) - _dec(t["discounts"])   # ← resta el descuento
intereses = _dec(e["interest_collected"])                     # ← NO resta interest_discounts
```

El dato existe —`interest_discounts` se consulta y se devuelve en la respuesta— pero no entra en el cálculo. Medido con un descuento real de 10.000 sobre un abono:

```
ventas netas (descuento ya restado)      3.180.000
intereses BRUTOS                           300.000     ← por caja entraron 290.000
total_revenue                            3.480.000

utilidad reportada                       1.195.000
utilidad restando el descuento           1.185.000
```

**La utilidad se sobreestima por todos los descuentos de interés otorgados.** En este laboratorio son 10.000 sobre 1.195.000; en una compraventa que negocia intereses seguido, la desviación es sistemática y siempre en la misma dirección. Y lo mismo ocurre en `GET /reports/series`, que usa la misma definición — así que la gráfica de doce meses arrastra el mismo sesgo.

**Por qué creo que debería restarse:** un descuento sobre el interés es plata que la compraventa **decidió no cobrar**, o sea una rebaja del ingreso, no un dato informativo. Es la misma naturaleza que el descuento de una venta, y para ese caso el proyecto ya decidió: *«el descuento se resta del ingreso y no se trata como gasto»* (`PENDIENTES_BACKEND_INFRA.md` §26). Hoy dos ingresos del mismo estado de resultados siguen criterios distintos.

**No lo arreglé** porque cambia el valor de un indicador que el dueño ya está mirando, y eso es una decisión suya — igual que F3-01. El fix es una línea.

### Todo lo demás cruza

| Dato | Fuente A | Fuente B | ¿Coincide? |
|---|---|---|---|
| Ventas del período | `/profit`: 3 ventas, 3.180.000 | Dashboard: `today_count` 3, `today_total` 3.180.000 | ✓ |
| Capital en la calle | `/pawn-performance`: 8.950.000 | Dashboard: `capital_outstanding` 8.950.000 | ✓ |
| Inventario disponible | `/inventory-valuation`: 3 lotes, 1.470.000 al costo | Dashboard: `available_count` 3, `available_value` 1.470.000 | ✓ |
| Ingresos del mes | Estado de resultados: 3.180.000 / 300.000 / 140.000 | `/series`: idénticos | ✓ (misma semántica, no una tercera definición) |
| Abonos registrados | `/pawn-performance`: `payment_count` 5 | Auditoría: 5 × `create_payment` | ✓ |
| Gastos | Estado de resultados: `expense_count` 3 | Auditoría: 3 × `create_expense` | ✓ |
| Ventas vivas | `/profit`: 3 | Auditoría: 4 × `create_sale` − 1 × `void_sale` | ✓ |

### La auditoría no dejó nada fuera

**87 entradas y 33 acciones distintas** en la empresa espejo. Se cruzó la lista completa de operaciones ejecutadas en las cuatro fases contra lo registrado: **ninguna quedó sin rastro** — contratos (crear, importar, editar, abonar, descontar, rematar), inventario (ingresar, publicar, pagar, egresar, transformar), ventas (vender, anular, devolver), caja (abrir, cerrar, reabrir, gastar, trasladar, liquidar), catálogos, clientes, cuentas e identidad.

### Nota de uso, no defecto

`GET /reports/closings-breakdown` devolvió **cero líneas** pese a todo el movimiento del día: solo cubre sesiones **cerradas**, y la de hoy sigue abierta. Está documentado y es coherente (un acta se arma sobre un turno cerrado), pero significa que **la tabla de desglose de la pantalla de Reportes está vacía para el día en curso**. Un dueño que la abre a media tarde no ve lo de hoy. El estado de resultados sí lo incluye, porque sale de los documentos y no del desglose de caja — que es justamente la razón por la que se construyó así.

---

## Fase 4 — Inventario y tienda (08/09/2026)

**Veredicto: sólido, con un solo desajuste y es de documentación.** El módulo más grande de la app —códigos, producto contra lote, unidades, transformaciones, kardex, ventas, devoluciones y notas crédito— hizo todo lo que promete. De paso quedó cerrado el pendiente de la Fase 2: la liquidación de un convenio con saldo real.

### F4-01 · El formato del código de inventario documentado no es el real — BAJA, **corregido**

| | |
|---|---|
| La doc decía | `[cat1][cat2][cat3][consecutivo 4 dígitos][letra origen]` → `JOC0001I` / `JOC0001R` |
| El real es | `JOC0002-01U` — el consecutivo es del **producto**, y hay un segmento de **lote** antes de la letra |

Comprobado comprando dos veces el mismo producto: salieron `JOC0002-01U` y `JOC0002-02U`, con costos de 100.000 y 120.000 respectivamente. La documentación se quedó en el modelo anterior a producto+lote (migración 00021).

**Importa porque ese código va impreso en la etiqueta de cada pieza** y se teclea en el buscador del mostrador. Corregido en `CLAUDE.md` y `API_GUIDE` §9.

### Los códigos y sus letras de origen

Las cinco letras salieron de una operación real, no de leer el código:

| Código emitido | De dónde salió |
|---|---|
| `JOC0001-01R` · `JOA0001-01R` | Las dos prendas del remate de la Fase 3 |
| `JOC0002-01U` · `JOC0002-02U` | Dos compras al mismo proveedor (letra `U`), dos lotes del mismo producto |
| `JOC0003-01T` | La barra de oro producida fundiendo esos dos lotes |
| `JOC0002-03D` | Un lote que volvió por devolución cuando el original ya estaba `written_off` |

Y el código es inmutable: republicar o hacer `PATCH` sobre un artículo publicado da `409`.

### La trazabilidad hacia atrás, que es el punto de todo esto

```
barra JOC0003-01T  →  source_transformation_id  →  transformación #1
                                                 →  consumió JOC0002-01U y -02U
                                                 →  comprados a Proveedor Uno
```

Y del otro lado, los artículos del remate llegan hasta el contrato del cliente que dejó la prenda. La cadena se recorre entera sin adivinar por nombre.

### Lo que se probó y está bien

| Comprobación | Resultado |
|---|---|
| Publicar sin precio · sin `inventory.create` | `422` · `403` |
| Los cuatro orígenes de ingreso | `purchase` sin proveedor `400`; `initial_stock` con medio de pago `400` (no toca caja); `other` sin notas `400`; rama de categorías inválida `400` |
| Compra en efectivo | Genera su movimiento de caja — el fix del punto 21 sigue en pie |
| Compra sin medio de pago | Queda a crédito y aparece en `/reports/payables` con su antigüedad |
| Pagarla | Exige `inventory.pay_purchase` (Bodega no puede); mueve la caja; pagar dos veces da `409` |
| Publicación automática | Una línea de ingreso con `sale_price` sale ya `available` con su código; sin precio queda `draft` |
| Unidades decimales | 12,5 gramos se aceptan; 2,5 unidades se rechazan con «se mide en u y no admite cantidades fraccionarias» |
| Costos por lote | El producto reporta el **rango** 100.000–120.000, nunca un promedio |
| Venta en efectivo | Entra a caja; stock descontado |
| Vender más de lo que hay | `400` — «No hay suficiente cantidad disponible» |
| Venta por Sistecrédito | **No toca la caja** y deja 1.500.000 por cobrar: una cuenta por cobrar no es plata |
| Anulación | Motivo obligatorio (`422` sin él), `sales.void` exigido, contra-movimiento, stock repuesto de 2 a 3, y `409` al anular dos veces |
| Egresos, los cinco tipos | Los cinco `201`; sin motivo `422`; sin `inventory.exit` `403`; el lote a cero pasa a `written_off` |

### La liquidación del convenio, con saldo real (pendiente de la Fase 2)

```
por cobrar 1.500.000 · banco 130.000
liquidar 1.500.000 recibiendo 1.400.000
  → commission 100.000 · commission_pct 6.67 · new_pending_balance 0.00
por cobrar 0 · banco 1.530.000
```

Un solo movimiento en el banco (`settlement_in` de 1.400.000). **La comisión no genera movimiento propio**: no es plata que salió, es plata que nunca llegó.

### Devoluciones y notas crédito

- **Devolver en efectivo una venta cobrada por un convenio todavía sin liquidar** → `400 SALE_ACCOUNT_NOT_SETTLED`. Una vez liquidada, la misma devolución pasa. Es el guardrail que evita sacar del cajón plata que el negocio nunca recibió.
- **Nota crédito**: se emite por el total, se redime **parcialmente** (180.000 de 1.500.000, saldo 1.320.000 derivado en cada lectura), no entra efectivo cuando cubre la venta entera, y **no es transferible**: usarla con otro cliente da `400`.
- **Reapertura de lote, el segundo camino**: como el lote original estaba `written_off` (lo había fundido), la devolución creó un lote nuevo **al costo congelado en la línea de venta** (120.000), que al publicarse tomó `JOC0002-03D`.

### El kardex

Cinco movimientos sobre un producto con dos lotes, una venta, una anulación y otra venta:

```
entry      JOC0002-01U   saldo 3 u.   300.000
entry      JOC0002-02U   saldo 6 u.   660.000
sale       JOC0002-02U   saldo 5 u.   540.000
sale_void  JOC0002-02U   saldo 6 u.   660.000     ← no existe como fila: se sintetiza
sale       JOC0002-02U   saldo 5 u.   540.000
```

Dos cosas que confirman el diseño: **la anulación aparece aunque no exista ninguna fila inversa** (`void_sale` solo cambia el `status`), y el valor **no se deriva de la cantidad** — al vender del lote de 120.000 el saldo bajó 120.000, no el promedio de los dos lotes. Las líneas traen `quantity_in`/`quantity_out` separadas, como un kardex contable de verdad.

### Las transformaciones: el costo viaja

```
entran  2 × 100.000  +  2 × 120.000   =  440.000
extra_cost (el fundidor)              =   50.000   → sale de la caja como `purchase`, no como gasto
                                        ─────────
sale    1 barra de oro                =  490.000
```

El costo de la salida **no se digita**: es todo lo que entró. Y en una segunda transformación con tres salidas y sin estimaciones, los 490.000 se repartieron en partes iguales (163.333,33 cada una), como documenta la regla. El `extra_cost` se capitaliza —es parte de producir el activo— en vez de ensuciar el gasto del mes.

---

## Fase 3 — Contratos (08/09/2026)

**Veredicto: es el módulo más sólido auditado hasta ahora.** Un solo hallazgo, y no está en el cálculo del dinero sino en lo que el sistema deja pasar antes de calcularlo. Las reglas que definen el negocio —interés sobre saldo, meses completos, snapshot legal, reparto del remate— se cumplen al peso, incluidos los ejemplos textuales de `CLAUDE.md`.

### F3-01 · Prestar y gastar no validan que haya efectivo; trasladar sí — MEDIA, **en definición de negocio**

Con el cajón en 240.000 esperados, presté 1.000.000 dos veces. Ambos desembolsos pasaron. Siguiendo desde un esperado ya negativo:

```
saldo esperado en el cajón: -2.260.000

traslado de 10.000        → 400  "No se puede trasladar más de lo que hay en la cuenta de origen"
gasto en efectivo 10.000  → 201  (esperado: -2.270.000)
préstamo de 5.000.000     → 201  (esperado: -7.270.000)
```

**La misma app dice «no puedes mover 10.000 porque no hay» y a la vez «sí puedes prestar 5.000.000».** Solo los traslados comprueban disponibilidad; las dos operaciones que más plata sacan del cajón —el gasto y el desembolso del préstamo— no.

**Por qué importa:** `expected_cash` queda negativo, que es un imposible físico — el sistema espera que en el cajón haya menos siete millones. Y al cerrar, la política es «sin tolerancia, justificación obligatoria», así que el cajero tiene que justificar a mano un descuadre **que el propio sistema fabricó**. Es el mismo espíritu del hallazgo #21 del backlog (las compras que no generaban movimiento y obligaban a justificar un descuadre inventado), visto desde el otro lado.

**No es obvio que deba bloquearse, y por eso es una pregunta de negocio.** Un argumento razonable para no validar: durante el día entra efectivo por ventas y abonos, y si el registro no es cronológico, validar estricto bloquearía operaciones legítimas. Pero entonces el traslado tampoco debería validar. **La inconsistencia es el hallazgo, más que la decisión.**

Tres salidas posibles: (a) validar en las tres operaciones, (b) no validar en ninguna y dejar que el arqueo lo revele, (c) advertir sin bloquear, como ya se hace con el LTV. La (c) encaja con el criterio que el proyecto ya tomó para un caso análogo.

**Trasladado a `frontend-starter/docs/DECISIONES_PENDIENTES.md` §3** (decisión de Mateo, 08/09), con las tres preguntas de negocio y las opciones desarrolladas. Sea cual sea la elegida, las tres operaciones deberían comportarse igual: hoy dos dicen una cosa y una dice la contraria.

### Lo que se probó y está bien

**La herencia de parámetros de categoría, incluido el caso sutil.** El árbol se sembró a propósito para exigirla:

| Categoría del artículo | Plazo | Ventana | De dónde salen |
|---|---|---|---|
| *Cadena* (n3, sin datos) → *Oro* (n2, sin datos) → *Joyería* (n1) | 4 | 4 | Ambos del **abuelo**: sube dos niveles |
| *Gama alta* (n3, sin datos) → *Celulares* (n2: plazo) → *Tecnología* (n1: ventana) | 1 | 1 | Plazo del **padre**, ventana del **abuelo** — resolución **por campo**, no por categoría |

Y rechaza lo que debe: mezclar en un contrato artículos con distinto plazo (`400`), o clasificar en categorías de nivel 1 o 2 (`400`).

**El snapshot legal.** Cambié *Joyería* de plazo 4 / ventana 4 a plazo 12 / ventana 9 con un contrato vivo colgando de ella: el contrato conservó 4 y 4; el siguiente contrato nació con 12 y 9.

**La aritmética del interés, con el ejemplo textual de `CLAUDE.md`:**

```
capital 1.000.000 al 5%   → interés mensual 50.000
abono de 3 meses (150.000) + 200.000 a capital
capital 800.000            → interés mensual 40.000     ✓
```

| Comprobación | Resultado |
|---|---|
| `payment-options` con 5 meses adeudados | 5 opciones, interés = N × 50.000, y **solo la que cubre todos los meses** permite capital |
| Capital con 2 de 5 meses · con 0 meses | `422 PAYMENT_PARTIAL_INTEREST_REJECTED` |
| Pagar 9 meses debiendo 5 | `400` — «Solo se adeudan 5 mes(es) de interés» |
| Abono válido | `interest_paid_until` avanza exactamente N meses; el estado se recalcula (salió de prórroga a `active`) |
| Descuento sobre intereses | `total = interés − descuento`; motivo obligatorio (`400` sin él); no puede superar el interés del abono |
| Permisos | Asesor abona (`201`) pero no descuenta (`403`); Bodega no abona (`403`) |
| Saldar el contrato | `paid`, prendas `returned`, y `GET /settlement` pasa de `404` a devolver `settled_at` + `receipt_number` **derivados** del abono que lo saldó |
| Abonar sobre un contrato `paid` o `auctioned` | `400 CONTRACT_CLOSED` |
| `PATCH /contracts/{id}` con `status`, `capital_balance`, `principal`, `interest_rate_pct` | Los ignora; solo aplica avalúo y notas. Sin `contracts.edit`, `403` |
| LTV muy por encima del máximo | `ltv_warning: true` y el contrato se crea igual — advierte, no bloquea |
| Buscador `?q=` | Encuentra por `legacy_code`, número, nombre y documento. `q='5'` devuelve el contrato #5, **no** todos los clientes con cédula que empieza en 5 (el fix del 02/09 aguanta) |

**El remate, que es el flujo más cruzado del sistema.** Contrato con dos prendas tasadas en 900.000 y 300.000, capital 1.000.000 y 7 meses de interés pendientes:

```
deuda = 1.000.000 + 7 × 50.000 = 1.350.000
Cadena grande  (75%)  → artículo draft, costo 1.012.500
Anillo pequeño (25%)  → artículo draft, costo   337.500
                                       suma  1.350.000  ✓
```

Y con ello: contrato y prendas a `auctioned`; `origin='auction'` con `source_contract_id`; **las fotos de la prenda heredadas al artículo** (el fix documentado funciona — sin él, toda pieza rematada quedaba bloqueada esperando que alguien refotografiara algo ya fotografiado); el vínculo navegable en los dos sentidos (`contract_item.inventory_item_id` ↔ `ItemOut.source_contract_id`); y **cero movimiento de caja**, que es lo correcto: el dinero salió cuando se desembolsó el préstamo. Rematar un contrato vigente da `409 CONTRACT_NOT_READY_FOR_AUCTION`, y sin `contracts.auction`, `403`.

**El import de contratos preexistentes.** Crea el contrato con el estado ya recalculado (`in_arrears` desde la primera respuesta), y **el efectivo esperado no se mueve ni un peso** — el préstamo ya se entregó en el sistema viejo. Las cinco validaciones responden con su código propio: `CONTRACT_LEGACY_CODE_EXISTS`, `IMPORT_CAPITAL_EXCEEDS_PRINCIPAL` (por exceso y por cero), `IMPORT_DATES_MISALIGNED`, `400` para una fecha de inicio futura, y `403` sin `contracts.import`.

**La auditoría cubre el ciclo entero:** `create_contract`, `import_contract`, `update_contract`, `create_payment`, `apply_payment_discount` (con monto y motivo) y `auction_contract`.

> **Nota sobre el descuento de intereses (H-04).** Esta fase confirma que del lado del backend está completo y funcionando: calcula, valida, exige motivo y audita en dos entradas. Lo único que falta es la pantalla — ver `frontend-starter/docs/DECISIONES_PENDIENTES.md`.

---

## Fase 2 — Dinero y caja (08/09/2026)

**Veredicto: el motor de caja hace lo que promete.** El arqueo cuenta solo el efectivo, el descuadre no tiene tolerancia ni de un peso, la sesión cerrada es inmutable, el ciclo diario es único, y las reglas de las cuentas se cumplen por todos sus caminos. Los tres hallazgos son de **mensajes y documentación**, no de dinero mal calculado.

Queda fuera, para las fases 3-4: los movimientos que nacen de un contrato o una venta, y la liquidación de un convenio con saldo real (necesita una venta por Sistecrédito).

### Los dos pendientes de la Fase 1, cerrados

**El histórico de caja no se rodea por ninguna de sus cinco puertas.** Con una sesión cerrada de ayer sembrada en la base, el Asesor (solo `cashbox.view`) accede a su turno de hoy y se le niega todo lo demás:

| Puerta | Admin (`view` + `view_history`) | Asesor (solo `view`) |
|---|---|---|
| `/cashbox/sessions/current` · `/today` | 200 | 200 |
| `/cashbox/sessions/{de hoy}` y su `/report` | 200 | 200 |
| `/cashbox/sessions` (listado) | 200 | **403** |
| `/cashbox/sessions/{de ayer}` y su `/report` | 200 | **403** |
| `/reports/closings` | 200 | **403** |
| `/reports/closings-breakdown` | 200 | **403** |

El corte es la **fecha de la sesión**, no su estado: la de hoy ya cerrada sigue siendo el turno de quien la cerró. *«Si un permiso se puede rodear por otra URL, no es un permiso»* — se cumple.

**Las cuentas de otra empresa se rechazan también con la caja abierta.** En la Fase 1 el `409 CASH_SESSION_NOT_OPEN` se adelantaba y tapaba la validación; con caja abierta, un gasto o un traslado contra una cuenta de la empresa B responde `404`.

### F2-01 · Con la caja cerrada, un traslado dice "no hay plata" en vez de "no hay caja" — MEDIA, abierto

```
POST /accounts/transfers  (desde el cajón, con la caja cerrada)
  → 400 BAD_REQUEST  "No se puede trasladar más de lo que hay en la cuenta de origen."
     saldo reportado de la cuenta cash: 0.00     (el cajón tenía 250.000)
```

`API_GUIDE` §13 promete otra cosa: *«Si toca efectivo **exige caja abierta** (`409 CASH_SESSION_NOT_OPEN`)»*. Lo que ocurre es que sin sesión abierta el saldo de una cuenta `cash` se reporta como `0.00` —correcto y documentado— y la validación de saldo se adelanta a la de sesión.

**Por qué importa, y no es cosmético:** es el mismo patrón que costó once días con los contratos. El cajero lee *«no hay plata en la caja»* cuando la caja tiene 250.000 y lo que pasa es que está cerrada, así que va a buscar un problema que no existe. Y el front no puede ofrecer el modal de «Abrir caja», porque ese comportamiento está mapeado a `CASH_SESSION_NOT_OPEN` y acá llega `BAD_REQUEST`.

**Arreglo sugerido:** comprobar la sesión antes que el saldo cuando el origen es una cuenta `cash`.

### F2-02 · Un gasto pagado por transferencia se bloquea si la caja está cerrada — MEDIA-BAJA, abierto

```
POST /cashbox/expenses  (payment_method: transfer, cuenta bancaria, caja cerrada)
  → 409 CASH_SESSION_NOT_OPEN
```

**La documentación se contradice consigo misma:**

- §8 (cashbox): *«Siempre contra la sesión abierta actual — `409 CASH_SESSION_NOT_OPEN` si no hay ninguna»* → coincide con el código.
- §13 (accounts): *«Quién exige sesión de caja: el **tipo de cuenta**, no la operación… una transferencia no pasa por el cajón y no se bloquea si nadie abrió caja»* → lo contrario.

El código es coherente con el **esquema**: `expense.session_id` es `NOT NULL`, así que un gasto está estructuralmente atado a una sesión y sin ella no hay dónde anclarlo. (`cash_movement.session_id` sí es opcional desde 00026 — la restricción viene solo de `expense`.)

Así que no es un bug de implementación, pero sí una **limitación funcional real**: pagar el arriendo por transferencia un domingo, o antes de abrir la caja, no se puede registrar. El gasto existió; el sistema no lo admite. Decidir si se cambia es de negocio: cambiarlo pide hacer `session_id` opcional y decidir a qué corte contable pertenece un gasto sin sesión.

### F2-03 · La misma clave de idempotencia con otro cuerpo devuelve el documento viejo sin avisar — BAJA, abierto

```
POST /accounts/transfers  key=K  monto 10.000  → 201  #2  (10.000)
POST /accounts/transfers  key=K  monto 77.777  → 201  #2  (10.000)   ← el monto pedido se ignora
```

Devolver el resultado original es el comportamiento seguro y estándar (no duplica ni cobra de más), y el riesgo real es bajo porque el front genera un UUID por acción de usuario. Pero un cliente que reutilice una clave por error recibe un `201` con un monto distinto al que pidió, y nada se lo dice. Un `409` sería más honesto.

### F2-04 · La auditoría se documentaba al revés — BAJA, **corregido**

`API_GUIDE` §11 decía *«paginado por cursor, más reciente al final»*. Es descendente: **lo más reciente va primero**. La frase era cierta cuando el orden era `order by id` sobre UUID aleatorios —o sea, ningún orden— y quedó sin actualizar tras el fix del 08/09. Corregido.

### Lo que se probó y está bien

| Comprobación | Resultado |
|---|---|
| El arqueo cuenta **solo** el efectivo | 500.000 base − 200.000 traslado − 50.000 gasto en efectivo = **250.000**; el gasto de 80.000 por transferencia no lo toca |
| Descuadre de **un peso** sin justificación | `400` — *«Todo descuadre exige justificación (sin tolerancia)»* |
| Cerrar sin `cashbox.open_close` | `403` |
| Sesión cerrada = inmutable (cerrar, gastar, trasladar sobre ella) | `409 CASH_SESSION_NOT_OPEN` |
| Abrir una segunda sesión el mismo día | `409 CASH_SESSION_ALREADY_CLOSED_TODAY` |
| Reabrir sin `cashbox.reopen` / sin motivo / con motivo | `403` · `422` · `200` |
| Traslados: origen = destino, desde o hacia `settlement`, más de lo disponible, fecha futura, monto 0 o negativo | Los seis rechazados, con mensaje propio |
| `settlement` como fuente de pago de un gasto | `400 ACCOUNT_CANNOT_FUND_PAYMENT` |
| Liquidación: sin saldo, hacia sí misma, recibiendo más de lo liquidado, sin `accounts.settle` | Los cuatro rechazados |
| Saldos derivados: listado vs. extracto | Coinciden; la `cash` sin saldo corriente (la base se redeclara en cada apertura), `bank` con acumulado |
| Idempotencia: misma clave dos veces · sin el header | Mismo documento, sin duplicar · `400 IDEMPOTENCY_KEY_REQUIRED` |
| Auditoría de la fase | `open_session`, `close_session`, `reopen_session`, `create_expense`, `account_transfer`, `create_account`, `create_expense_category` — todas registradas |

> **Nota de método:** la acción del traslado se llama `account_transfer`, no `create_transfer`. Es la misma suposición que ya había fallado antes y que motivó `tests/unit/test_audit_actions.py`. Confirma que el nombre de una acción hay que leerlo del código, no deducirlo del patrón.

---

## Fase 1 — Identidad, permisos y aislamiento (08/09/2026)

**Veredicto: el control de acceso está sólido.** 420 comprobaciones (105 endpoints × 4 roles, con el permiso y sin él) y las 420 coinciden con lo esperado. Los 167 casos sin permiso devolvieron `403 PERMISSION_DENIED` sin una sola excepción. Ningún endpoint quedó sin guard. Lo que falla está fuera de la capa de permisos.

**14 hallazgos: 3 altos (los tres arreglados), 3 medios, 8 documentales (los ocho corregidos).**

### H-01 · El job nocturno no existía en Fly — ALTA, resuelto

`fly machines list` devolvía una sola máquina, la del process group `app`. La Fly Machine programada que describe `ARCHITECTURE.md` §11 no estaba. `ESTADO.md` registra que el 27/08 se borró «una máquina huérfana, fuera del process group, sin deploys desde el 17/08» — el perfil exacto del job, porque estar fuera del fleet de `fly deploy` es justo su diseño.

**Evidencia de que llevaba días sin correr:**

```
select event_type, count(*) from subscription_event group by 1;
  created 5 · extended 3 · expired 0      ← cero vencimientos automáticos en toda la historia
```

Y el contrato #8 de Empresa Demo Front estaba en `active` con 51 días de mora, mientras su gemelo #9 (un día de diferencia, mismo snapshot) sí estaba `in_arrears`. El #8 se corrigió solo al leerlo.

**La consecuencia, demostrada con un caso reproducible.** Contrato con 5 meses de mora y la prórroga vencida hace dos, con el `status` sin tocar:

```
— antes de que alguien abra el contrato —
Lista de contratos     estado mostrado: active
Listos para remate     0 contratos · ¿está el nuestro? NO
Dashboard              active:1  in_extension:0  ready_for_auction:0

— alguien abre GET /contracts/{id} —
                       estado: in_extension · prórroga venció 2026-07-08

— después —
Listos para remate     1 contrato · SÍ
Dashboard              active:0  in_extension:1  ready_for_auction:1
```

`get_contract` recalcula al leer (`service.py:424`), pero **`list_contracts` no**, y `list_ready_for_auction` filtra por `status = 'in_extension'` persistido. Sin el job, el estado solo avanza si un humano abre ese contrato — y un contrato abandonado es el que nadie abre. **Las prendas rematables son invisibles precisamente porque nadie las mira.**

Segundo efecto: una empresa con la suscripción vencida hace 38 días entraba con normalidad.

**Arreglado y verificado.** Máquina `nightly-job` recreada en `sjc` con `--schedule daily`. Para probar que hace su trabajo, se desarmó el estado a propósito:

```
job_nocturno_completado: 1 contrato(s) recalculado(s), 1 suscripción(es) vencida(s)
contrato → in_extension · suscripción → expired · evento expired (la primera de la base)
```

**El comando que documentaba el proyecto no funcionaba:** usaba `registry.fly.io/…:latest`, y ese tag no existe en el registry de Fly (las imágenes se publican como `deployment-<id>`). Corregido en `fly.dev.toml` y `fly.prod.toml`.

**Dos cosas que conviene recordar de esta máquina** (ya en `ARCHITECTURE.md` §11):

1. Queda clavada a la imagen con la que se creó. `fly deploy` **no** la actualiza, porque no pertenece a su fleet — hay que recrearla tras un cambio que la afecte.
2. **Su ausencia es silenciosa.** No hay health check ni alerta. Para comprobar que vive: `fly machines list -a compraventa-backend-dev` debe mostrar `nightly-job`, o buscar `job_nocturno_completado` en los logs del último día.

**Queda como recomendación, no hecho:** recalcular también en `list_contracts`, para que la lista no pueda mentir aunque el job vuelva a fallar. Cambia el costo de una consulta que corre en cada carga de la pantalla de contratos — decisión de Mateo.

### H-14 · Una suscripción vencida no se podía renovar — ALTA, resuelto

**Lo destapó H-01: un bug estaba escondido detrás del otro.** Con el job arreglado, la empresa de pruebas pasó a `expired` como debe. Al intentar devolverle el acceso:

```
POST /platform/companies/{id}/subscription/extend  → 404 "no tiene una suscripción activa"
POST .../activate                                  → 200, pero la suscripción sigue expired
GET  .../companies/{id}                            → plan_code: null, expires_at: null
```

**No quedaba ningún camino en la API** para reactivarla: el único arreglo era entrar a la base a mano. Es el flujo comercial más normal del producto — el cliente paga tarde y se le renueva. Nunca se detectó porque para llegar hasta él hace falta una suscripción `expired`, y el job que las produce no estaba corriendo.

**Causa:** `extend_subscription` buscaba con `get_active_subscription`, que filtra `status = 'active'` — justo el estado que una vencida ya no tiene. Y aunque la encontrara, el `UPDATE` solo movía `expires_at` sin tocar `status`: el acceso habría seguido bloqueado.

**Arreglado:** `get_subscription_for_renewal` la encuentra esté o no vigente, y el `UPDATE` la vuelve a poner `active`. Con test que falla sin el fix. Verificado en vivo: `plan_code: null → "full"`, `vence: null → 2027-12-31`, y la empresa volvió a entrar.

**Abierto, decisión de producto:** una empresa vencida se muestra en el panel con `plan_code: null`, indistinguible de una que nunca tuvo plan — el super-admin renueva sin ver a qué fecha ni con qué plan. El front ya tiene la lógica para pintar un vencimiento pasado en rojo (`CompanyDetailDialog.tsx:166`) **y nunca puede verse**, porque el dato llega en `null`. Cambiarlo toca el contrato documentado de `CompanyOut`.

### H-02 · `GET /accounts/transfers` devolvía 500 desde su creación — ALTA, resuelto

```
GET /api/v1/accounts/transfers  → 500 "Internal Server Error"   (texto plano, sin envelope)
```

Fallaba con la lista vacía y con datos, para todo rol con `accounts.view`. Causa reproducida contra la base:

```
asyncpg.exceptions.AmbiguousParameterError: could not determine data type of parameter $2
```

La cláusula `(:cursor is null or t.id > :cursor)` en `accounts/repository.py:238`: el parámetro aparece primero en `is null`, sin contexto de tipo. Era el **único** sitio del backend con ese patrón; los demás arman el `WHERE` dinámicamente.

**Por qué nadie lo vio:** el endpoint aparecía 9 veces en `tests/integration/test_accounts.py` y **las 9 eran POST**. Ningún test hacía GET al listado, así que 325 tests estaban en verde con un endpoint roto al 100%. En el front, `useTransfersList()` existe pero no tiene consumidores — la pantalla de histórico de traslados nunca se construyó, así que estaba roto y latente.

**Arreglado**, con el test GET que faltaba (cubre con y sin cursor, y falla sin el fix con el error exacto). Verificado en vivo con un traslado real.

### H-03 · Contraste por debajo de WCAG AA — MEDIA, abierto

Medido con `getComputedStyle` sobre la app en vivo:

| Texto | Ratio | Mínimo | Origen |
|---|---|---|---|
| «Caja cerrada — no se pueden registrar operaciones de dinero» | **1.97** | 4.5 | `--warning` sobre `--warning-soft` |
| «Tu rol no incluye el resumen del inicio…» | **2.77** | 4.5 | `--text-muted` sobre `--bg-app` |
| Nombre del rol bajo el avatar | **2.97** | 4.5 | `--text-muted` sobre `--bg-surface` |

`DESIGN_SYSTEM.md` §4.10 exige AA 4.5:1 y advierte específicamente sobre el teal; ese cuidado no se aplicó al ámbar ni al gris. El peor caso es el mensaje operativo más importante del producto — el mismo que costó once días a LA GRAN LEGAL. Y `--text-muted` no es un caso suelto: es el token de labels de KPI, hints y placeholders, así que recorre la app entera. Se corrige en `tokens.css`, el mismo mecanismo que ya sostuvo el rediseño.

**Recomendación:** verlo en la Fase 6, con capturas del antes y el después.

### H-04 · El descuento sobre intereses existe en el backend y no tiene pantalla — MEDIA, en definición

Cruzando el catálogo de 36 permisos contra los que el front menciona sobran dos, y los dos son **especiales**: `payments.apply_discount` y `sales.return_override_time_limit`.

El backend acepta `discount_amount` en un abono, lo audita y tiene el permiso en la matriz de roles; `PaymentOptionsPanel.tsx` nunca lo envía. El módulo puede **mostrar** descuentos que ninguna pantalla puede crear. Y `MIGRACION_CONTRATOS.md` §5 define que el interés parcial ya pagado en el sistema viejo se reconoce «usando el descuento existente» — un paso que hoy no se puede dar por pantalla.

**Necesita definición de negocio.** Documentado con sus cinco preguntas y tres opciones en `frontend-starter/docs/DECISIONES_PENDIENTES.md`.

### H-05 · El inicio del Asesor es una pantalla vacía — MEDIA, abierto

Sin `reports.view`, `/` muestra un párrafo y unos 700 px de vacío. El texto está bien escrito (nombra el permiso y a quién pedírselo), pero deja al rol de mostrador —el que más usa la app— abriendo en una pantalla que no le sirve. Es una oportunidad: ese espacio es el sitio natural para nuevo contrato, nueva venta, buscar cliente, contratos que vencen hoy.

### H-06 … H-13 · Desajustes entre documentación y código — BAJA, los ocho corregidos

Ninguno rompía nada, pero en este proyecto la documentación *es* la especificación.

| # | Decía | Hace |
|---|---|---|
| H-06 | `GET /accounts/{id}/statement` con rango opcional, «últimos 30 días» por defecto | Lo **exige**: `422` con `missing` en ambos |
| H-07 | Letras reservadas `R`, `P`, `T` | Son cuatro — también `D` (devolución, 00044) |
| H-08 | Catálogo de errores de `API_GUIDE` §15 | Faltaban `CANNOT_DEACTIVATE_SELF`, `USER_ALREADY_EXISTS`, `USER_ALREADY_INVITED`, `EMAIL_ALREADY_REGISTERED`, `AUTH_ACCOUNT_MISSING`, `TEMPLATE_IS_ACTIVE`, `INVITE_RATE_LIMITED`, `AUTH_ADMIN_ERROR` |
| H-09 | `CASH_SESSION_NOT_OPEN` es 409 | Es 409 salvo en `/cashbox/sessions/current`, donde es 404 a propósito |
| H-10 | «38 permisos» (`ESTADO.md`) / «37» (`README.md`) | Son **36** |
| H-11 | Exclusiones del Moderador en `seed.sql` | El código excluye 5 más: `accounts.manage/settle/transfer`, `inventory.pay_purchase`, `inventory.transform` |
| H-12 | «Paginación por cursor en toda lista» | **Trece** endpoints devuelven array plano, sin cursor ni tope |
| H-13 | `PATCH /me` ignora `role_id`/`status`/`email` | Los ignora **y responde 200**, así que quien los manda cree que funcionaron (sin riesgo de escalada — verificado) |

Más un noveno que apareció al arreglar H-01: el comando del job en los `.toml` usaba un tag `:latest` inexistente.

### Lo que se probó y está bien

Vale tanto como la lista de arriba: son los sitios donde no hay que buscar. Varios nunca se habían verificado en vivo.

| Comprobación | Resultado |
|---|---|
| 105 endpoints × 4 roles, con el permiso y sin él | **420/420**; los 167 negados dieron `403 PERMISSION_DENIED` |
| Endpoints sin `Depends(require_permission)` | Ninguno, en los 109 del AST |
| Salvaguarda del último admin: desactivar, bajar de rol, quitar el permiso al rol | Los tres caminos → `409 LAST_ADMIN_SAFEGUARD` |
| Auto-desactivación por API, no solo por UI | `409 CANNOT_DEACTIVATE_SELF` |
| Escalada vía `PATCH /me` (rol, estado, correo, empresa) | Ninguna: el schema descarta los campos |
| Aislamiento entre empresas: leer, y meter ids ajenos en cliente, categoría, rol, usuario, cuenta | Todo `404`; nunca confirma que exista en otra empresa |
| Guard de `/platform` sin el claim *(pendiente desde el 19/08)* | Cerrado incluso para un Admin con los 36 permisos |
| Activación `invited → active` solo con `amr: password` | Correcta en los 4 usuarios nuevos |
| Errores del alta: reinvitar, correo ya registrado, enlace de un inactivo | 409 con código propio y mensaje que nombra la salida |
| Alta de empresa devuelve `admin_invite_link` (fix del 04/09) | Confirmado creando dos empresas |
| Gates de UI: menú y ruta directa, en Admin / Asesor / Bodega | Coinciden exactamente con los permisos, en las dos capas |
| Un 403 no se lee como falla | Nombra el permiso y a quién pedírselo |
| Banner de caja cerrada con y sin `cashbox.open_close` (fix del 03/09) | Correcto; Bodega, sin `cashbox.view`, no ve el banner en vez de afirmar un estado |
| Desborde horizontal a 360 px | Ninguno |
| Ventana tras desactivar a alguien con sesión abierta | **32 s** — coincide con el cache de 30 s ya anotado como conocido |

### Pendiente de la Fase 1, para hacer al abrir la Fase 2

Dos comprobaciones que necesitan historia de caja, que la empresa espejo todavía no tenía:

1. Que el histórico de sesiones de días anteriores no se alcance sin `cashbox.view_history` por **ninguna** de sus puertas (`/cashbox/sessions`, `/cashbox/sessions/{id}` de otro día, `/reports/closings`, `/reports/closings-breakdown`). Requiere insertar una sesión de ayer en la base.
2. Que una cuenta de otra empresa se rechace **con la caja abierta**: hoy el `409 CASH_SESSION_NOT_OPEN` se adelanta y tapa la validación del `account_id` ajeno.

---

## El laboratorio (cómo retomarlo)

Todo vive en el proyecto Supabase de **dev** (`driyubkodnsqxbtxcmaz`). Las empresas reales (*La Legal*, *LA GRAN LEGAL*, *Empresa Demo Front*) **no se tocan** salvo autorización explícita.

### Empresas y usuarios de prueba

| Empresa | Para qué |
|---|---|
| `ZZ QA — auditoria 08/09` | La empresa espejo principal: catálogo, cuentas, clientes, contratos |
| `ZZ QA-B — aislamiento 08/09` | La segunda empresa, para probar que A no ve nada de B |

Seis usuarios, todos con contraseña `QaLab2026!`:

| Correo | Rol | Permisos |
|---|---|---|
| `qa.admin@qalab.com` | Admin | 36 |
| `qa.moderador@qalab.com` | Moderador | 19 |
| `qa.asesor@qalab.com` | Asesor | 11 |
| `qa.bodega@qalab.com` | Bodega | 5 |
| `qa.gestor@qalab.com` | Gestor Usuarios QA (rol creado a medida) | 1 — `identity.manage_users`, para probar la salvaguarda del último admin sin ser admin |
| `qa.b.admin@qalab.com` | Admin de la empresa B | 36 |

El super-admin de plataforma es la cuenta de Mateo (claim `app_metadata.platform_role`). Para crear usuarios nuevos sin gastar cuota de correo: invitar con `send_email: false` y luego fijar la contraseña con el `SUPABASE_SERVICE_ROLE_KEY` (`PUT /auth/v1/admin/users/{id}`).

### Datos sembrados en la empresa QA

- **Categorías con herencia repartida a propósito:** *Joyería* (nivel 1) define plazo/ventana/LTV y sus hijas *Oro* → *Cadena*/*Anillo* no definen nada (prueba que la herencia sube dos niveles); *Tecnología* define solo la ventana y su hija *Celulares* solo el plazo (prueba que la herencia es **por campo**, no por categoría).
- **Cuentas de los tres tipos:** `Caja principal` (cash), `Bancolombia QA` (bank), `Sistecrédito QA` (settlement).
- **Contrato `QA-JOB-TEST-1`** con fechas manipuladas en la base a propósito, para la demostración de H-01.

### Cómo se probó

- **Matriz de permisos:** `require_permission` es un `Depends`, así que se evalúa **antes** del body. Un request con body vacío y un UUID inexistente devuelve `403` si falta el permiso y `422`/`404` si lo tiene — así se barre el catálogo entero sin crear ni modificar nada.
- **Mapa de endpoints:** los paths salen de `/openapi.json` (la verdad), y el permiso de cada uno del AST de los `router.py` cruzando por el nombre de la función. Ojo: varios routers declaran **más de un `APIRouter`** en el mismo archivo, así que tomar el último `prefix` asignado da rutas equivocadas.
- **UI:** Playwright vía el caché de npx, con login real de cada rol contra Vercel.
- **Contraste:** `getComputedStyle` recorriendo los nodos de texto y calculando el ratio WCAG contra el primer ancestro con fondo opaco.

Los scripts viven en [`scripts/qa/`](../scripts/qa/) — ver su README para levantar el laboratorio y correr la matriz de permisos completa.
