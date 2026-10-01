# Dominio — las reglas de negocio vigentes y su porqué

> **Qué es.** Las reglas que el backend hace cumplir hoy, cada una con el módulo que la ejecuta y la razón
> por la que es así. Es el documento que se lee antes de tocar plata, estados o reportes.
>
> **Fuente de verdad: el código.** Cada regla cita el archivo del módulo (sin número de línea: una cita con
> línea envejece sola y quien la sigue no tiene cómo saberlo). Si esto contradice al código, gana el código
> y se corrige aquí. Los endpoints y los códigos de error están en [`API_GUIDE.md`](API_GUIDE.md); la mecánica
> (transacciones, bloqueos, errores) en [`ARQUITECTURA.md`](ARQUITECTURA.md).

## 1. El negocio en una página

Prendo es un SaaS multi-tenant para **compraventas colombianas**: casas de empeño con tienda. Cada compraventa
es una **empresa** con sus datos aislados. El negocio tiene **dos motores que se miden distinto** y una caja
que los une:

| | Empeño | Tienda |
|---|---|---|
| Qué hace | presta plata contra una prenda | compra y revende mercancía |
| Cómo gana | **intereses** sobre el capital prestado | **margen** sobre el costo |
| Qué NO es ganancia | el capital que el cliente devuelve | la plata de una venta hasta restarle el costo |

La vida de un contrato: se presta contra una prenda → el cliente paga interés mes a mes → si deja de pagar
entra en mora → agotada la ventana de mora entra en prórroga → vencida la prórroga queda lista para remate →
al rematar, la prenda se vuelve artículo de inventario y se vende en la tienda. **Esa cadena se recorre
también hacia atrás** (del artículo en vitrina al contrato del cliente): un vínculo que existe en los datos
pero no en la aplicación no es trazabilidad.

### Los principios de la plata (cada uno costó una corrección)

- **El interés es ingreso; el capital recuperado no.** Prestar no es gasto, cobrar no es ganancia.
- **Ingreso no es ganancia**: una utilidad que no resta el costo de ventas sobreestima por todo lo que costó la
  mercancía.
- **Una cuenta por cobrar no es plata**: una venta con Sistecrédito es ingreso pero no flujo de caja hasta que
  el convenio consigna. Se filtra por **tipo de cuenta**, no por concepto.
- **Un traslado no es ingreso ni egreso**: es la misma plata en otro bolsillo.
- **Ni un aporte del dueño es ingreso, ni un retiro es gasto**: mueven patrimonio, no resultado.
- **El costo nunca se promedia** (identificación específica): el precio vive en el producto; el costo, en el lote.
- **Los saldos se derivan, nunca se guardan**: un saldo almacenado se desincroniza; uno derivado no puede.
- **El estado de resultados lee DOCUMENTOS, no movimientos de caja**: así un documento nuevo (un aporte de
  capital) queda fuera del resultado por construcción, sin exclusiones que alguien pueda olvidar.
- **Nada se edita a mano**: estados, stock y saldos solo cambian por documentos; se corrige con un
  contra-documento, nunca editando (`cash_movement`, `audit_log`, `contract_payment` son inmutables por trigger).
- **Hoy es la fecha de la EMPRESA** (zona `America/Bogota` por defecto), nunca la del servidor
  ([`ARQUITECTURA.md`](ARQUITECTURA.md) §9).
- **Generalizar, no calcar un negocio.** Es un SaaS: ante una variante de proceso (tiene caja fuerte o no,
  consigna todo o una parte) se busca el modelo que no asume el proceso, no una casilla por empresa.

## 2. Contratos de empeño

Código: `app/modules/contracts/` (`rules.py` es lo puro: intereses, estados, cupo; `service.py` lo aplica).

### 2.1 Crear

- **Categoría de nivel 3** para cada prenda; el plazo, la ventana de mora, la prórroga y el LTV se **heredan
  por campo** subiendo el árbol de categorías (una hija puede definir solo el plazo y heredar la ventana del
  abuelo). Sin plazo o ventana en ninguna parte del árbol, error explícito nombrando la categoría.
- **SNAPSHOT legal:** al crear se copian al contrato la tasa, el plazo, `arrears_window_months`,
  `extension_months` y `extension_window_days`. Cambiar la configuración después **no toca contratos firmados**:
  el papel que el cliente firmó manda.
- **LTV y avalúo** (`service._check_ltv`): si la categoría define LTV, el **avalúo es obligatorio**; prestar sin
  avalúo o por encima de `avalúo × LTV` exige `contracts.override_ltv`, y el contrato queda con `ltv_warning` y
  auditado como quien autorizó. Sin LTV en la categoría no hay techo. Por qué un permiso y no una casilla por
  empresa: nadie sabe contestar "¿advierte o bloquea?" al dar de alta una empresa, y el permiso expresa además
  el caso real (el asesor no puede, el dueño sí).
- **El desembolso sale de la caja** (`loan_disbursed`): en efectivo exige turno abierto
  ([§4.3](#43-el-turno-y-el-arqueo)). Hoy **no** se valida que haya efectivo suficiente (decisión abierta, ver
  [`ESTADO.md`](ESTADO.md)).

### 2.2 Intereses y abonos

- **Interés mensual = tasa del contrato × saldo de capital actual** (`rules.monthly_interest`). 1.000.000 al 5 %
  → 50.000/mes; tras abonar 200.000 a capital → 40.000/mes.
- **Solo meses COMPLETOS.** Un pago parcial de interés se rechaza (`PAYMENT_PARTIAL_INTEREST_REJECTED`). El
  capital solo recibe abono cuando los intereses quedan al día en el mismo pago o ya lo estaban.
  `GET /contracts/{id}/payment-options` devuelve los montos exactos aceptables (1 mes, 2 meses… todo + capital
  libre): la UI nunca calcula un interés.
- Pagar N meses mueve el ancla: `interest_paid_until += N meses`, y se recalcula el estado.
- **Saldar causa como mínimo UN mes** (`rules.minimum_payoff_months`, decisión del dueño 27/09/2026): sin esto,
  quien empeña y devuelve dentro del primer mes no pagaba interés. El mínimo es sobre la vida del contrato: si
  el ancla ya se movió, ya se cobró. Un sucesor de ampliación hereda inicio y ancla, así que ampliar no lo
  esquiva.
- **Descuento sobre intereses:** el endpoint de abonos acepta `discount_amount` + motivo con
  `payments.apply_discount` (especial), auditado y con alerta A2. **No hay pantalla que lo use** (decisión
  abierta). Aplica solo a intereses, nunca a capital.
- Cada abono registra la **cuenta elegida** (no la predeterminada del medio de pago).

### 2.3 La máquina de estados

`rules.compute_status` — la calculan el servicio (al escribir y al leer el detalle) y el job nocturno. **Nunca
se edita a mano.**

| Estado | Cuándo |
|---|---|
| `active` (Vigente) | 0 meses adeudados; indefinido mientras pague el interés |
| `in_arrears` (En mora) | de 1 a N−1 meses adeudados (N = `arrears_window_months` del snapshot; p. ej. metales 4, tecnología 1: con 1, el primer mes adeudado ya es prórroga) |
| `in_extension` (Prórroga) | al llegar a N meses; `extension_ends_at = ancla + N meses + extension_months`. Se fija una vez; un abono mueve el ancla y la fecha se recalcula desde la nueva |
| `paid` | saldó capital e intereses; las prendas se devuelven todas juntas |
| `auctioned` | **solo** la acción manual Rematar |
| `superseded` | el contrato fue ampliado y lo sucede otro |

`paid`, `auctioned` y `superseded` son **terminales** (`rules.TERMINAL_STATUSES`, una sola constante que usan la
guarda, el job, la puerta de abonos y el cupo de ampliación). **"Listo para remate" no es un estado**: es
`in_extension` con `extension_ends_at` vencida (`GET /contracts/ready-for-auction`).

**«Para hoy»** (`GET /contracts/attention`, `rules.attention_for`): cada contrato que debe al menos un mes cae en
**un** motivo — listo para remate, en mora, en prórroga o **vence hoy** — para que las tarjetas no se pisen. «Vence
hoy» es que la primera cuota sin pagar (`ancla + 1 mes`) cae hoy; como `months_owed` pasa de 0 a 1 ese mismo día, el
estado ya es `in_arrears`, y por eso el motivo, no el estado, es lo que separa «vence hoy» de «en mora» (≥1 día de
atraso). Los montos son los de `payment-options`: ponerse al día, un mes en «vence hoy», y saldar en «listo para
remate». Hay días sin vencimientos: el 31/10 ninguna cuota vence (no hay 31/09 y el 30/09 + 1 mes es el 30/10).

### 2.4 Remate

`service.auction_contract` (`contracts.auction`, especial): en una transacción el contrato y sus prendas pasan
a `auctioned`, nace un artículo de inventario en `draft` por cada prenda (`origin='auction'`, puntero
`source_contract_id`, las fotos de la prenda viajan con él), un ingreso de inventario, y la auditoría.

**Costo del artículo = saldo de capital + interés pendiente**, repartido entre las piezas por avalúo. Pero el
interés se guarda aparte (`inventory_item.capitalized_interest`, 00063) porque **la base de costo en el
resultado es el capital prestado**: al vender la pieza, el costo de ventas descuenta solo el capital y el
interés que el contrato adeudaba se reconoce **dentro de la utilidad bruta**, informado como
`auction_interest_realized`. Si se sumara aparte, se contaría dos veces. El valor del inventario sí es el costo
completo. Publicar el artículo (con precio y, en piezas únicas, foto) emite su código.

La **prenda en garantía** (`contract_item`: categoría, descripción, peso o serial, avalúo; estados custodia,
devuelta, transferida, rematada) y el **artículo de inventario** (código, precio, stock) son entidades distintas;
`contract_item.inventory_item_id` solo las enlaza al rematar, para poder recorrer la cadena hacia atrás. El remate es
**asistido**: el sistema lista los candidatos, una persona con permiso decide, y la ejecución es automática.

### 2.5 Contratos que vienen de otro sistema

`POST /contracts/import` (`contracts.import`, especial). **Se migra la foto financiera al corte, no la
historia**: el cuerpo trae hechos (capital actual, `interest_paid_until`, condiciones pactadas en su momento) y
el backend deriva todo lo demás (número, vencimiento, estado) con la misma lógica de siempre. No exige caja ni
genera `cash_movement` (el desembolso ocurrió en el pasado). `interest_paid_until` debe caer en un múltiplo
exacto de meses desde el inicio. No se migran abonos viejos (son inmutables y consumen consecutivos) ni
contratos ya pagados o rematados. **El interés parcial ya pagado** en el sistema viejo se lleva al último mes
completo y el excedente se reconoce en el primer abono como descuento con motivo. Es también el único camino
para **sembrar** contratos en cualquier estado (útil en QA). Checklist de corte: [`OPERACION.md`](OPERACION.md) §7.

## 3. Ampliar el préstamo («recargo»)

`POST /contracts/{id}/extend-loan` (`contracts.extend_loan`). El cliente vuelve dentro de una ventana y retira
parte del cupo que su prenda tiene sin usar: `avalúo × LTV − saldo` (`rules.quote_extension`).

**No es un `UPDATE` del capital:** el interés se cobra en meses completos anclados a `interest_paid_until` y
toda la máquina de estados cuelga de esa ancla; y **el papel que el cliente firmó dice un capital**. Por eso el
contrato se **sucede**: el viejo queda `superseded` (sus prendas `transferred`, nunca salieron de la bóveda) y
nace uno nuevo con `parent_contract_id`/`root_contract_id`, principal = saldo viejo + monto, y las mismas
condiciones (ampliar no renegocia lo pactado).

Las invariantes, cada una con su test:

- **La ventana se mide desde la RAÍZ de la cadena** (`extension_window_days`, snapshot, default 28; 0 apaga la
  función). Medida desde el contrato actual, un recargo de $1 el último día reiniciaría el reloj para siempre.
- **A la caja sale solo el delta**: el capital viejo ya salió el día del contrato original.
- **El interés vencido nunca se suma al capital** (anatocismo): con meses adeudados se rechaza
  (`CONTRACT_INTEREST_OVERDUE`) y hay que abonar primero.
- **El sucesor hereda el ancla** (00053): `start_date` de la raíz, `interest_paid_until`/`due_date` del padre. La
  fecha de cobro del cliente no se mueve y no hay "mes en curso" que prorratear (prorratear rompería la regla de
  meses completos que sostiene todo lo demás).
- **Por eso el sucesor puede quedar antedatado**, y **antedatar un documento que alguien firma hoy es un
  problema legal**: cuándo se entregó la plata vive en `extended_on`/`extension_amount`, y la pantalla y el
  impreso muestran las dos fechas.
- Pasarse del cupo exige `contracts.override_ltv`, igual que al crear. **La cadena no tiene límite de
  eslabones** (la ventana ya la acota); `GET /contracts/{id}/chain` la muestra entera y dice dónde vive la deuda
  hoy. El sucesor de un eslabón es el que lo tiene como `parent_contract_id`, no "el siguiente de la lista".

## 4. Caja y cuentas

Código: `app/modules/accounts/`, `app/modules/cashbox/` (`integration.resolve_account_for_movement` decide cuenta
y sesión para todo movimiento).

### 4.1 La cuenta es dónde está la plata; el medio es cómo se cobró

`payment_method` (`cash`/`transfer`/`other`) es un dato del **documento** y se conserva: el comprobante impreso
no debe cambiar porque alguien renombró una cuenta. La **cuenta** dice a dónde entró y cuánto hay. El caso que
lo exigió fue Sistecrédito: el cliente sale con el artículo y el convenio paga después, menos una comisión; eso
no es plata que entró, es plata que te deben.

| Tipo | Qué es | ¿Efectivo físico? | ¿Operativa? (una venta o préstamo la elige) |
|---|---|---|---|
| `cash` | el cajón | sí | sí |
| `vault` | caja fuerte, fondo de menudos (00049) | sí | **no**: solo entra y sale por traslado |
| `bank` | banco, Nequi, Daviplata | no | sí |
| `settlement` | convenio que te debe (Sistecrédito) | no | recibe ventas; **no puede financiar salidas** |

- **Una sola cuenta `cash` activa por empresa** (`CASH_ACCOUNT_ALREADY_EXISTS`): un arqueo que mezcla dos
  cajones es incuadrable por construcción. Multi-caja es una fase aparte ([§12](#12-sucursales-y-multi-caja)).
- La `vault` se rechaza como origen **y** destino de cualquier operación de negocio (`ACCOUNT_NOT_OPERATIONAL`):
  una venta cobrada "a la caja fuerte" saltaría el arqueo del cajón sin que nada lo note.
- **Nada se configura**: "¿esta empresa tiene caja fuerte?" se responde con "¿existe esa cuenta?". Una empresa
  consigna todo, otra la mitad, otra el martes lo del lunes: son traslados con su fecha real, y ninguna variante
  necesita existir en el código.
- El alta de una empresa crea sus cuentas iniciales junto con los roles semilla y la caja principal.

### 4.2 El saldo se deriva

**Todas las cuentas, incluido el cajón, valen `opening_balance` + la suma de sus movimientos desde siempre**
(00048). El saldo existe con la caja cerrada. No hay ningún campo donde escribir un saldo, así que no puede haber
un número inventado: el saldo de apertura de un turno era el único número de la app que aparecía sin documento,
y dejó de digitarse. `account_balance()` delega en `list_accounts()`: dos formas de calcular el mismo saldo
terminan divergiendo (ya pasó).

### 4.3 El turno y el arqueo

- **El turno es una ventana de responsabilidad, no un contenedor de plata**: dice quién respondía por el cajón
  entre dos horas y qué se movió en esa ventana. Una sesión abierta por registradora (`uq_session_open`).
- **Quién exige turno abierto es el TIPO DE CUENTA, no la operación**: todo movimiento contra una cuenta `cash`
  lo exige (`CASH_SESSION_NOT_OPEN`); una venta por transferencia o por Sistecrédito no pasa por el cajón y no
  queda bloqueada porque nadie abrió caja. Postgres no admite subconsultas en un `CHECK`, así que la regla vive en
  el servicio, en un solo lugar.
- **Abrir hereda el saldo.** Contar al abrir es opcional; si difiere, motivo obligatorio y un **ajuste**
  (`adjustment`) con responsable — el faltante queda atribuido al turno donde apareció.
- **Cerrar**: el backend calcula `expected_cash` (efectivo del turno por tipo de cuenta, no por medio de pago: un
  gasto pagado por transferencia no salió del cajón) y el desglose módulo × concepto × medio; el usuario registra
  lo contado; **toda diferencia exige justificación, sin tolerancia**; el cierre emite su ajuste y el cajón pasa a
  valer lo contado. Sesión cerrada = inmutable.
- Los ajustes de arqueo llevan **`session_id = NULL` a propósito** (corrigen la cuenta, no son operaciones del
  turno: dentro, `expected_cash` los contaría dos veces y el acta siempre cuadraría); la trazabilidad va por
  `reference_type`/`reference_id`.
- **Reabrir** (`cashbox.reopen`, especial, motivo, auditado, alerta A4) **revierte el ajuste que emitió el
  cierre**: deshacer una operación es deshacer sus efectos, no su registro (F21-32).
- **Una venta es un documento; el movimiento de caja es el libro del dinero**, generado automáticamente desde cada
  documento (venta, abono, préstamo, compra, gasto), etiquetado por módulo (`pawn`/`store`/`general`), medio y
  referencia. Nada se digita dos veces.
- **Gastos** (`cashbox.expense`): documento con cuenta y medio; es el único movimiento "manual" junto con los
  ajustes.
- **Una sesión abierta durante días** ensucia el acta y los reportes por fecha de sesión; es un hábito que el
  cliente debe corregir, no un bug.

### 4.4 Traslados y liquidaciones

- **Traslado** (`accounts.transfer`, especial): documento numerado con dos movimientos y fecha propia, **no atado
  al cierre**. Tocar el cajón exige turno abierto. Valida saldo del origen.
- **Liquidar un convenio** (`POST /accounts/{id}/settle`, `accounts.settle`, especial): mueve el saldo de la
  `settlement` a la cuenta que recibió la plata; es documento propio (`account_settlement`, 00061) para poder ser
  idempotente. **La comisión se deriva** (`liquidado − recibido`) y no genera movimiento: no es plata que salió,
  es plata que nunca llegó. Aparece en el estado de resultados como «Comisiones de convenios».
- Toda salida que valida saldo **bloquea la cuenta** antes de leerlo ([`ARQUITECTURA.md`](ARQUITECTURA.md) §6.1).

## 5. Capital del dueño

`app/modules/capital/` (00054). Aportes y retiros en **un solo documento** `capital_movement` con `direction`
(son el mismo concepto en dos sentidos, como un traslado) y conceptos de caja propios
(`owner_contribution`/`owner_withdrawal`), no `adjustment` (un ajuste significa "el sistema no cuadra"; aquí
hubo un hecho real).

- **No pasan por el estado de resultados** (lee documentos de venta, abono, gasto, egreso y liquidación; este no
  es ninguno). No hizo falta partida doble.
- **Se rechaza**: retirar más de lo que hay en la cuenta; usar una cuenta `settlement` (ese saldo todavía no
  existe); efectivo con la caja cerrada; retiro sin motivo; fecha futura (contra el hoy de la empresa).
- **Solo se advierte**: retirar por encima de la utilidad. `GET /capital/position` muestra dónde está la plata —
  disponible (cajón + bóveda + bancos, **sin** cuentas por cobrar), prestado, inventario **al costo** — y lo sin
  repartir, que puede salir negativo a propósito: en una compraventa retirar "lo que hay en caja" es
  descapitalizar. La utilidad se pide a `reports` por integración, no se recalcula.
- `kind` (`profit`/`capital_return`) existe con default y sin pantalla, para el contador.
- Permisos solo del Admin de fábrica: `capital.view`, `capital.contribute`, `capital.withdraw` (especial; alerta A3).

## 6. Inventario

`app/modules/inventory/` (`rules.py` códigos y repartos; `units.py` unidades).

### 6.1 Producto + lote, y el código

El **producto** es lo que se vende (nombre, precio, fotos de mercancía fungible); el **lote** es cada compra o
ingreso, con su costo real. Dos compras del mismo producto son dos lotes con dos costos: **el costo nunca se
promedia**. Las cantidades admiten fracción (`NUMERIC(14,3)`: se vende por gramos).

Código: `[letra cat1][cat2][cat3][consecutivo de 4 dígitos del producto]` y el lote
`-[2 dígitos][letra de origen]` → producto `JOC0007`, lote `JOC0007-01I`. Consecutivo atómico por
(empresa, prefijo) con `next_counter()`. **Se emite al publicar y es inmutable.**

La **letra de origen** se deriva de los punteros del lote, nunca se digita (los punteros son excluyentes):

| Letra | Origen | Puntero |
|---|---|---|
| la del proveedor | compra | `supplier_id` |
| `R` | remate | `source_contract_id` |
| `T` | transformación: fundir, despiezar, armar (00039) | `source_transformation_id` |
| `P` | propio: inventario inicial o sobrante de conteo (00033) | ninguno |
| `D` | devolución de cliente cuyo lote original ya no se podía reabrir (00044) | `source_return_id` |

`R`, `P`, `T` y `D` están **reservadas**: un proveedor no puede tomarlas (se valida al escribir, no hacia atrás:
hay códigos impresos). *Un documento de traspaso del 14/08 describía un modelo de "pieza única" (`JOC0001I`) que
ya no existe y produjo una guía equivocada: la fuente es este módulo.*

### 6.2 Movimientos de stock

- **El stock solo cambia por documentos**: ingreso (`purchase`, `initial_stock`, `adjustment_in`, `other`, y
  `customer_return` desde una devolución), egreso, venta, anulación, devolución, transformación. Kardex por
  producto.
- **Egresos** (`inventory.exit`, especial, motivo): `adjustment`, `damage`, `loss`, `internal_use`
  (cuentan como **mermas y bajas** en el resultado, al costo sin interés capitalizado) y `supplier_return` (no es
  pérdida; hoy no toca cuentas por pagar).
- **Transformaciones** (`inventory.transform`, especial): consumen lotes y producen lotes nuevos con letra `T`;
  el costo se reparte entre lo producido y puede sumar un costo de proceso pagado. Destruyen inventario de forma
  irreversible, por eso son especiales.
- **Compras a crédito**: el ingreso queda por pagar; pagar la factura (`inventory.pay_purchase`, especial) sale
  una sola vez (bloqueo + idempotencia). `GET /reports/payables` las lista por proveedor.
- Publicar exige precio, y foto **solo en piezas únicas** (en el remate la foto es la evidencia de qué prenda
  dejó el cliente); en mercancía fungible la foto vive en el producto.

## 7. Ventas

`app/modules/sales/` (`settlement.py` reparte devoluciones).

- **Cliente opcional.** Confirmar = una transacción: valida stock y estado, emite número, descuenta stock,
  **congela el costo** en la línea (`unit_cost` y `unit_cost_interest`, 00019/00063: un reporte de un período
  cerrado no se mueve si alguien corrige un costo después) y el precio publicado (`list_price`), movimiento de
  caja `module=store`, comprobante interno (sin DIAN).
- **Descuento** (`sales.apply_discount`, especial): motivo obligatorio, auditado, alerta A2 por encima del umbral
  de la empresa. **Vender por debajo del precio publicado ES un descuento**, llegue como `discount_amount` o como
  un `unit_price` menor (decisión del dueño, F6-05): exige lo mismo. Por encima del precio publicado es libre.
- **Vender por debajo del COSTO del lote** también exige `sales.apply_discount`
  (`SALE_BELOW_COST_REQUIRES_PERMISSION`) aunque no esté bajo el precio publicado (un producto puede estar
  publicado bajo costo). Al costo exacto es libre.
- **Anular** (`sales.void`, especial, motivo, auditada, alerta A1): repone stock y emite el contra-movimiento por
  la **misma cuenta** por la que entró. No se anula una venta con devoluciones (`SALE_HAS_RETURNS`) ni una
  pagada con nota crédito (`SALE_PAID_WITH_CREDIT_NOTE`): la nota no es reversible si ya se redimió en otra venta.
  Hoy anular exige caja abierta aunque la venta haya entrado por banco (hallazgo abierto).
- **Devolución** (`sales.return`, especial): dentro de `return_window_days` (default 30) o con
  `sales.return_override_time_limit`. **Se devuelve lo pagado, no el precio de lista** (neto del descuento
  prorrateado). Con reingreso, la pieza vuelve a su lote si sigue intacto o a un lote nuevo `D` al costo
  congelado; sin reingreso, su costo no se descuenta del costo de ventas (la pieza no volvió). La liquidación se
  parte: **lo pagado con nota crédito vuelve como nota crédito nueva, lo pagado en plata vuelve por el medio
  elegido**, en proporción (`settlement.split_return_settlement`; "primero la nota" perjudicaría al cliente,
  "primero la plata" al negocio).
- **Nota crédito** (00043): saldo a favor de un cliente, **no transferible**; se redime en ventas de ese cliente
  y reduce lo que hay que cobrar sin cambiar el total de la venta.

## 8. Reportes: una sola definición por concepto

`app/modules/reports/` — `schemas.py` documenta cada campo; el nombre de un número significa lo mismo en todos
los endpoints. Todo sale de **documentos** en la zona de la empresa; las devoluciones caen en el período de la
**devolución**, así un mes cerrado no se reescribe.

### 8.1 Estado de resultados (`GET /reports/income-statement`)

| Línea | Definición |
|---|---|
| Ventas (`sales_revenue`) | ventas `completed` netas de descuento, **brutas** de devoluciones |
| Devoluciones (`sales_returns`) | contra-ingreso con línea propia, neto del descuento prorrateado |
| Intereses (`interest_revenue`) | interés cobrado en abonos **neto** de descuentos de interés |
| Ingresos totales | ventas − devoluciones + intereses |
| Costo de ventas | costo congelado de lo vendido (base = capital en piezas rematadas) neto del costo de lo devuelto con reingreso |
| Utilidad bruta | ingresos totales − costo de ventas |
| Gastos operativos | documentos de gasto |
| Mermas y bajas | egresos `loss`/`damage`/`adjustment`/`internal_use` al costo sin interés, en la fecha del egreso |
| Comisiones de convenios | `liquidado − recibido` de cada liquidación, en su fecha |
| Descuadres de caja | ajustes de apertura, cierre y reversa al reabrir, **con signo** (sobrante suma); por eso no coincide con la diferencia de los cierres, que solo cuenta el arqueo |
| **Utilidad operativa** | bruta − gastos − mermas − comisiones + descuadres. **Esto es "cuánto ganó el negocio"** |

Informativos que **no** se vuelven a restar: descuentos de interés, descuentos de venta totales (cabecera + bajo
precio publicado), interés de remate realizado. Contexto que **no es resultado** y va aparte para que nadie lo
busque: capital prestado y recuperado (cartera moviéndose), compras causadas (por fecha del ingreso, crédito
incluido) y pagos de compras (por fecha del pago — la diferencia es información, no error), costos de
transformación pagados.

### 8.2 Los demás números

- **Dashboard** (`/reports/dashboard`): ventas de hoy y del mes **netas de devoluciones** (= ventas − devoluciones
  del estado de resultados para ese período; una anulada nunca cuenta), con el bruto y las devoluciones aparte;
  conteo de contratos por estado y cartera; inventario disponible al costo; estado de la caja.
  Contra el **mes anterior completo** (no los mismos días): intereses cobrados netos (= `interest_revenue` del
  estado de resultados, misma función), ventas netas con el criterio de `month_total`, y los remates del mes por
  la fecha de su documento (el ingreso de inventario `auction`), porque `contract` no guarda cuándo se remató.
- **Rentabilidad del empeño** (`/reports/pawn-performance`): «Intereses cobrados» es el **neto**
  (`interest_revenue`, la misma cifra del estado de resultados); capital prestado = contratos nuevos + delta de
  cada ampliación (un importado no suma); contratos abiertos = préstamos nuevos, ni sucesores ni importados;
  rendimiento sobre la cartera **actual** (no hay histórico de saldos).
- **Utilidad de tienda** (`/reports/profit`): bruta, con descuentos, devoluciones y costo neto.
- **Flujo de ventas** (`/reports/closings-breakdown` → `sales_flow`): es **caja**, no resultado: filtra por tipo de cuenta
  (lo cobrado con Sistecrédito no entra hasta liquidarse).
- **Inventario** (`/reports/inventory-valuation`, `/stale-inventory`): al costo y al precio publicado.
- **Rangos**: `INVALID_DATE_RANGE` si está invertido, `DATE_RANGE_TOO_LONG` si excede el tope.
- **Un arreglo propuesto es una hipótesis**: "netear las devoluciones en el agregador" sonaba obvio y era
  imposible (la mitad de lo devuelto no pasa por caja; habría producido una cuarta definición de ingreso). Se
  mide antes de implementar.

## 9. Notificaciones por correo

`app/modules/notifications/`. Todo desplegado; **los avisos al cliente nacen apagados** y cada empresa los
enciende en Configuración → Notificaciones (interruptor general + casilla por aviso).

### 9.1 Qué se avisa (`catalog.py`, espejo exacto de la tabla que siembra 00058)

| Familia | Eventos | Destinatario | Por defecto |
|---|---|---|---|
| Comprobantes C1–C7 | contrato creado, abono, paz y salvo, ampliación, nota crédito, venta (con cliente), anulación/devolución | cliente | apagado |
| Recordatorios R1–R4 | cuota por vencer (3 días antes), cuota vencida (mora), entró en prórroga, la prórroga vence pronto | cliente | apagado |
| R5 | la prenda está lista para remate — **aviso de cortesía**, no la notificación formal (esa la fija el contrato) | cliente | apagado |
| Resúmenes | diario (solo si hubo actividad o alertas) y semanal (lunes) | usuarios con `notifications.receive_digest` | encendido |
| Alertas A1–A4 | venta anulada, descuento sobre el umbral, retiro de capital, caja reabierta | usuarios con `notifications.receive_alerts` (sin el autor) | encendido |
| P1 | invitación de usuario (sale siempre, por Resend) | la persona invitada | siempre |

**Qué NO se notifica:** casi nada de lo que hace la app. La regla: se avisa lo que cambia la relación del
cliente con su deuda o su compra, o lo que el dueño necesita saber ya.

### 9.2 Reglas

- **La restricción que manda: el cliente casi nunca da correo** (medido: 2 de 16 en el primer cliente; en una
  compraventa colombiana se da el celular). La empresa sí tiene siempre correo, por eso los avisos a la empresa
  existen sin depender de nada.
- **Un aviso es consecuencia de un hecho ya registrado**: nunca tumba la operación ([`ARQUITECTURA.md`](ARQUITECTURA.md) §5.1).
- **La llave de idempotencia se construye** (evento + destinatario + día objetivo), nunca es aleatoria: el job
  puede correr dos veces o tarde sin duplicar, y el rezago marca `skipped_stale` lo que ya no es noticia.
- **Un envío no se audita** en `audit_log` (vive en su propia tabla de entregas con estado); lo auditable es el
  hecho que lo originó.
- **Remitente = la plataforma, autor = la empresa**: sale de un dominio verificado de Prendo con el nombre de la
  compraventa.
- **Base legal por FINALIDAD** (Ley 1581): cada evento tiene `purpose` (`service`/`marketing`, sin default); cada
  cliente guarda su `email_basis` (`contract` o `consent`), que se **escribe** (no se deduce) para conservar la
  base que había el día del envío. Servicio sale con cualquier base; mercadeo solo con consentimiento (hoy no
  hay eventos de mercadeo). Por encima: sin dirección, baja pedida o correo inválido, no sale nada. La base
  «contrato» se apoya en una **cláusula de autorización de avisos** dentro del contrato firmado (insertable desde
  el editor de plantillas). *Esto es criterio del dueño, no un concepto de abogado; se recomienda revisión legal
  antes de encender recordatorios en una empresa real.*
- **Ley 2300 de 2023** (`limits.py`, `preferences.py`): todo mensaje sobre un pago pendiente es cobranza (R1–R5).
  Ventana: lunes a viernes 7:00–19:00, sábados 8:00–15:00, sin domingos ni festivos colombianos; **un contacto
  por semana por canal**. Es un **piso**: la empresa puede endurecerlo, no aflojarlo (`clamp_to_legal_floor`,
  `legal_floor_violations`). Fuera de horario la entrega no se pierde, se corre al próximo momento hábil.
- **Los comprobantes no son cobranza**: no cuentan para el tope semanal ni para el diario (el cuarto abono del
  día no puede quedarse sin su recibo). Siguen dentro de la ventana horaria. Si un abogado dice lo contrario, es
  un parámetro (`transactional_in_weekly_cap`).
- **Un recordatorio frenado por el tope se reprograma**, no se pierde: vuelve a `pending` con `deferred_at` para
  el primer momento permitido, salvo que para entonces ya no diga la verdad; al enviarlo se re-verifica el hecho
  (si el cliente pagó, `suppressed`).
- Baja de un clic por enlace firmado ([`ARQUITECTURA.md`](ARQUITECTURA.md) §5.2).
- **El comprobante que se pide en el mostrador sale** (F8-07, decisión del dueño, como Shopify POS o Square):
  al cobrar una venta o un abono el mostrador pregunta «¿se lo mando al correo?» (`send_receipt_email`). Si
  dice que sí, ESE comprobante sale aunque el cliente no tenga base general y aunque la empresa tenga apagado
  ESE aviso: la base de esa única entrega es su pedido (`legal_basis = request`, con `requested_by` = quien
  cobró). **El interruptor general sí manda**: con los correos de la empresa apagados no sale nada —apagarlo
  significa «esta empresa no envía correos», y un pedido no lo cambia; el mostrador no ofrece la casilla. No toca `customer.email_basis`: recordatorios y cobranza siguen exigiendo contrato o
  consentimiento. Baja, rebote y la falta de correo siguen ganando. Si dice que no, no sale aunque tenga
  base (`suppressed`, con el motivo). Sin el campo, lo de siempre. Vive en `service.customer_gate`
  (`requested`), y el despachador lo vuelve a mirar al enviar como todo lo demás.

## 10. Usuarios, empresas y suscripciones

- **No hay registro público**: alta solo por invitación (`identity`), y la empresa la crea el super-admin con sus
  roles semilla, cuentas, caja principal e invitación del primer admin (que devuelve el enlace).
- Estados de un usuario: `invited` (existe, **todavía no entró con contraseña propia**), `active` (ya entró con
  su contraseña), `inactive` (desactivado a propósito; el backend le niega todo). Un estado que el sistema muestra
  tiene que ser el estado real.
- Salvaguardas: siempre ≥1 admin activo; nadie se desactiva a sí mismo; el último admin no pierde
  `identity.manage_roles`; un usuario no puede darse ni dar un rol con más permisos que los suyos
  (`ROLE_EXCEEDS_ACTOR_PERMISSIONS`) ni cambiar su propio rol (`CANNOT_CHANGE_OWN_ROLE`).
- **Suscripciones manuales**: el super-admin amplía `expires_at`; el job marca `expired` y eso bloquea el acceso
  (`402 SUBSCRIPTION_EXPIRED`). Precios fuera del sistema. **Suspender o vencer nunca borra datos.**

## 11. Roles y los 43 permisos

RBAC dinámico por empresa; permisos solo vía rol. Roles semilla (`platform/service.py`): **Admin** (todos),
**Moderador** (todos menos lo que mueve plata de la caja, excepciones a políticas comerciales, usuarios, roles,
auditoría, configuración, capital y correos a la empresa), **Asesor** (operación de mostrador), **Bodega**
(inventario y catálogos). Clonables, no eliminables. Especial = mueve plata, cambia un estado irreversible o es
una excepción a una política; siempre auditado.

| Módulo | Permisos (★ = especial) |
|---|---|
| accounts | `view` · `manage` · `settle`★ · `transfer`★ |
| audit | `view` |
| capital | `view` · `contribute` · `withdraw`★ |
| cashbox | `view` · `view_history` · `expense` · `open_close`★ · `reopen`★ |
| catalogs | `view` · `manage` |
| company | `configure` |
| contracts | `view` · `create` · `edit` · `extend_loan` · `auction`★ · `import`★ · `override_ltv`★ |
| customers | `view` · `create` |
| identity | `manage_users` · `manage_roles`★ |
| inventory | `view` · `create` · `exit`★ · `transform`★ · `pay_purchase`★ |
| notifications | `receive_digest` · `receive_alerts` |
| payments | `create` · `apply_discount`★ |
| reports | `view` |
| sales | `view` · `create` · `apply_discount`★ · `void`★ · `return`★ · `return_override_time_limit`★ |

Fuente: `supabase/seed.sql` y las migraciones que agregan permisos (el catálogo vive en base). **Un permiso que
se otorgó a todos no protege a nadie todavía**: 00051 dio `override_ltv` a todo rol que podía crear contratos, y
la rama "pídeselo a un responsable" no la ve nadie hasta que una empresa apriete el rol.

## 12. Sucursales y multi-caja

**Aplazado.** Hoy: una cuenta `cash` operativa por empresa, una registradora, sin ubicación en el inventario. Se
hicieron tres adecuaciones para que los datos de hoy sigan siendo utilizables el día que llegue (cada cajón ligado
a su registradora en `account.register_id`, la registradora activa ya no se adivina, y un guardián). **El
disparador no es el volumen: es el primer cliente con un segundo local.** La sede es una dimensión (mismo NIT) que
se **estampa** en el documento. Diseño completo: [`diseno/SUCURSALES.md`](diseno/SUCURSALES.md). Al dar de alta
una empresa: `python scripts/qa/verificar_sedes.py` (sale con 1 si la premisa se rompió).

## 13. Fuera de alcance, por decisión

- **PDFs** (contrato firmado, acta de caja): el front imprime con CSS y plantillas editables por empresa.
- **Facturación electrónica DIAN**: el comprobante de venta es interno.
- **Costo promedio / FIFO**: identificación específica, siempre.
- **Partida doble y cierre de ejercicio**: la utilidad se mide por período consultado.
- **WhatsApp** como canal de avisos; **correo certificado** para el aviso de remate (anotado como mejora).
- Socios con porcentajes, aportes en especie, impuestos.

## 14. Las especificaciones retiradas

Este documento reemplazó a las especificaciones por módulo (`NOTIFICACIONES.md`, `RECARGOS.md`,
`CAJA_TRAZABILIDAD.md`, `CAPITAL_DEL_DUENO.md`, `MIGRACION_CONTRATOS.md`, `CONTEXTO.md`) y a los registros
(`QA_AUDITORIA.md`, `PENDIENTES_BACKEND_INFRA.md`, `CONTINUAR.md`, `STORAGE_PENDIENTE.md`). Varios comentarios del
código y de los tests todavía los citan por sección: esas citas son **historia**, no la regla vigente. Para leer el
original: `git show 3b6b409:docs/NOTIFICACIONES.md` (mismo commit para los demás). Si una cita histórica y este
documento no coinciden, manda el código y después este documento.
