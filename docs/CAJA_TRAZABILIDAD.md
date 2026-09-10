# CAJA_TRAZABILIDAD.md — El modelo de efectivo (spec)

> **Estado:** el **Paso 1 está hecho** (migración `00048`, 10/09/2026) — el saldo del cajón ya se deriva de sus movimientos, abrir hereda en vez de digitar, y los arqueos de apertura y cierre emiten su ajuste. Faltan los Pasos 2, 3 y 4 de §6. Pedido por Mateo el 09/09/2026 probando con el cliente: *"trazabilidad de todo y sin números inventados"*.
>
> **Corrección de una primera versión de este documento.** El primer diseño proponía un *cierre guiado* que preguntaba "¿cuánto consignás, cuánto a la fuerte, cuánto de base?". Mateo lo rechazó con la razón correcta: **esto es un SaaS**. Una empresa tiene caja fuerte y otra no; una consigna todo, otra la mitad, otra reparte en tres; otra consigna el martes lo del lunes. Un producto que codifica *un* ritual de cierre le queda mal a todas menos a una.
>
> Este documento describe el modelo que **no** tiene ritual: ninguna de esas variantes se configura, porque ninguna necesita existir en el código.

---

## 1. El diagnóstico, en una frase

**El saldo del cajón es propiedad de la sesión de caja, y debería ser propiedad del cajón.**

Ese es el error de modelo del que sale todo lo demás. Hoy:

- `cash_session.opening_balance` es un número **digitado a mano** al abrir el turno.
- El saldo de una cuenta de efectivo **se deriva de esa sesión**, no de sus propios movimientos ([accounts/repository.py](../app/modules/accounts/repository.py)).
- Sin sesión abierta, una cuenta de efectivo **reporta cero**: la plata deja de existir para el sistema entre las 8 de la noche y las 8 de la mañana.
- Nada compara el `counted_cash` de anoche con el `opening_balance` de hoy.

Por eso el saldo de apertura es el **único número de toda la aplicación que aparece sin documento**. Todo lo demás se deriva de un hecho registrado — el stock solo cambia por ingreso, egreso o venta; el estado del contrato solo lo calcula el servicio; los movimientos de caja nunca se crean a mano. La regla 5 de `CLAUDE.md` es tajante: *"nunca editables a mano"*. El efectivo es la excepción, y es exactamente donde se pierde la trazabilidad.

## 2. Cómo lo resuelve un sistema financiero moderno

No es un invento de este documento: es el modelo de libro mayor que usan los POS y los ERP serios, y se sostiene en cinco ideas. Ninguna es nueva; lo que hace falta es aplicarlas al efectivo, que es la única parte de esta app donde todavía no rigen.

### 2.1 · El efectivo vive en **ubicaciones**, y son cuentas como cualquier otra

Un cajón, una caja fuerte, un fondo de menudos, el cajón de la segunda sucursal. Todas son cuentas. **Cuántas hay es asunto del negocio, no del producto**: cero, una o siete.

Esto es lo que contesta la pregunta de la caja fuerte sin configurar nada. *¿Esta empresa tiene caja fuerte?* → **¿existe esa cuenta?**. No hay una casilla "usa caja fuerte" en ningún lado, no hay un plan que la habilite, no hay una rama del código que la contemple. Una empresa sin caja fuerte simplemente nunca la crea, y el producto se comporta igual que hoy.

### 2.2 · El saldo se **deriva**, nunca se declara

El saldo de cualquier ubicación es la suma de sus movimientos desde siempre. Punto. Es exactamente lo que la app ya hace con las cuentas `bank`, y lo que no hace con las `cash`.

De acá sale la propiedad que Mateo pidió: **no hay ningún campo donde escribir un saldo, así que no puede haber un número inventado.** No es una validación que se pueda olvidar — es que el campo no existe.

Corolario incómodo pero correcto: el saldo del cajón **existe siempre**, haya turno abierto o no. La plata no deja de estar en el cajón porque sean las 11 de la noche.

### 2.3 · Contar no reescribe el saldo: genera un **ajuste**

Es la pieza que más cambia y la que hace que la trazabilidad sea real.

Hoy contás 292.000, el sistema esperaba 300.000, y la diferencia se guarda como un **campo del acta**. El saldo sigue diciendo 300.000 hasta que la próxima apertura lo pise con otro número escrito a mano. Los 8.000 que faltaron no están en ninguna parte consultable.

En el modelo correcto, el arqueo emite un `cash_movement` de concepto `adjustment` por −8.000, con su motivo y su autor. El saldo derivado pasa a 292.000 **porque hubo un movimiento**, no porque alguien lo reescribió.

```
saldo derivado    300.000
contado           292.000
                  ───────
ajuste de arqueo   −8.000   ← una línea en el libro, con motivo y responsable
saldo derivado    292.000
```

Es el mismo patrón que el kardex de inventario ya usa para el sobrante de conteo, y el mismo que el proyecto ya eligió para las correcciones: **los movimientos son inmutables y se corrigen con un contra-movimiento**, no editándolos. El trigger `forbid_change` sobre `cash_movement` ya lo impone.

Y de regalo, el faltante se vuelve reportable: *"cuánto se perdió en descuadres este mes"* pasa a ser una consulta, no una lectura de actas una por una.

### 2.4 · Mover plata es siempre lo mismo, y tiene **fecha propia**

Consignar en el banco, guardar en la fuerte, traer de la fuerte al cajón: **un solo verbo, el traslado**, con su documento numerado y su fecha. Ya existe (`account_transfer`), ya es idempotente, ya genera sus dos movimientos.

Lo importante es lo que **no** debe pasar: el traslado **no está atado al cierre**. Se consigna cuando se consigna. El martes se puede consignar lo del lunes, y ese traslado lleva fecha del martes porque eso fue lo que ocurrió.

Por eso el "cierre guiado" del primer diseño estaba mal: forzaba a destinar el efectivo en el momento del cierre, que es justamente lo que no todas las empresas hacen.

### 2.5 · El turno es una **ventana de responsabilidad**, no un contenedor de plata

La sesión sigue existiendo y sigue sirviendo para lo que sirve: quién respondía por el cajón entre estas dos horas, qué se movió en esa ventana, y el acta del turno. **Pero deja de ser dueña del saldo.**

Abrir un turno no declara cuánta plata hay: el saldo ya se sabe. Abrir solo dice *"desde ahora respondo yo"*. Si al abrir el cajero quiere contar —y debería—, ese conteo es un arqueo como el de la noche (§2.3), y si no cuadra genera su ajuste con su responsable. Que es precisamente el punto: **el faltante queda atribuido al turno donde apareció**, no al siguiente.

## 3. Todos los escenarios que nombraste, sin una sola configuración

| Lo que hace la empresa | Cómo se expresa | Qué se configura |
|---|---|---|
| No tiene caja fuerte | Esa cuenta no existe | **Nada** |
| Consigna todo el efectivo del día | Un traslado por el total | **Nada** |
| Consigna una parte y deja el resto | Un traslado parcial. Lo que queda, queda — y aparece solo mañana, porque el saldo es continuo | **Nada** |
| Consigna una parte, otra a la fuerte, otra queda | Dos traslados | **Nada** |
| Hace todo eso en días distintos | Cada traslado con su fecha real | **Nada** |
| No consigna nunca | Ningún traslado | **Nada** |
| Tiene dos cajones y una fuerte | Tres cuentas de efectivo | **Nada** (ver §5) |
| Deja siempre una base fija de vueltas | Consigna todo menos esa base. La base no es un ajuste: es lo que no se movió | **Nada** |

Esa columna de la derecha es el punto entero del modelo. **La flexibilidad no sale de opciones: sale de que el modelo no asuma un proceso.**

## 4. Qué cambia, concretamente

| | Hoy | Modelo propuesto |
|---|---|---|
| Saldo del cajón | Sale de `cash_session.opening_balance` + movimientos de esa sesión | Suma de sus propios movimientos, desde siempre |
| Sin turno abierto | El cajón reporta **0.00** | Reporta lo que hay |
| Abrir turno | Se **digita** un saldo libre | No se digita nada. Opcionalmente se cuenta (§2.3) |
| Cerrar turno | Guarda `counted_cash` y la diferencia como campos del acta | Además emite el **ajuste** que reconcilia el saldo |
| Diferencia de arqueo | Un campo, no consultable | Una línea del libro, con motivo, autor y fecha |
| Caja fuerte | No se puede representar | Una cuenta más |
| Consignar | Traslado (ya funciona) | Igual, sin cambios |

Lo que **no** cambia: el traslado sigue exigiendo turno abierto cuando toca el cajón, y sigue teniendo que ir **antes** del cierre — una sesión cerrada es inmutable y meterle un movimiento después invalidaría un acta ya firmada. Eso está bien decidido y no se toca.

## 5. Los dos tipos de cuenta que hacen falta

Hoy `account.type` mezcla dos preguntas independientes:

| | ¿Es efectivo físico?<br>(se cuenta a mano) | ¿Es operativa?<br>(una venta o un préstamo la pueden elegir) |
|---|---|---|
| Cajón — `cash` | Sí | Sí |
| **Caja fuerte** | **Sí** | **No** |
| Banco — `bank` | No | No |
| Convenio — `settlement` | No | No (y no puede financiar salidas) |

La caja fuerte es efectivo que **nadie opera directamente**: no se vende ni se presta desde la fuerte, la plata tiene que pasar por el cajón. Ese es el rasgo que la distingue, y el enum no lo puede expresar.

```sql
alter type account_type add value 'vault';
```

- Cuenta como **efectivo** en reportes y se puede arquear.
- **Solo recibe y entrega por traslado.** Ninguna operación de negocio la ofrece como origen ni destino.
- **No exige turno abierto** ni entra al arqueo del cajón — se arquea con su propia frecuencia, que cada empresa decide simplemente contándola cuando quiera.

### Y una guarda que el código promete y no cumple

`00024_accounts.sql` afirma en un comentario: *"Solo una cuenta `cash` por empresa entra al arqueo diario. **El índice parcial de abajo lo asegura**"*. El índice de abajo asegura **una cuenta por defecto por tipo**, no una cuenta de efectivo por empresa — y `create_account` tampoco valida nada. Por eso LA GRAN LEGAL tiene tres.

**Con el modelo de este documento el problema se disuelve**, y ese es el mejor argumento a su favor: si el saldo de cada ubicación sale de sus propios movimientos, tener tres cajones deja de ser un problema — cada uno tiene su saldo y se arquea por separado. Lo que hoy es incuadrable por construcción pasa a ser el caso normal.

Mientras el modelo siga como está, la guarda hay que ponerla igual: **impedir la segunda cuenta `cash`**, con un `409` que explique la alternativa (*"para tener más efectivo disponible, traslada desde otra cuenta"*).

## 6. Ruta de migración

El cambio es de modelo y hay contratos, ventas y una caja real operando. Va por partes, y **cada paso deja el sistema mejor que antes**.

### Paso 1 — El saldo del cajón deja de depender de la sesión — **HECHO (00048)**

El `opening_balance` de cada sesión histórica se convierte en movimientos:

- La **primera** sesión de la empresa → un movimiento `adjustment` de entrada por su `opening_balance`: es el saldo con el que la empresa arrancó en el sistema.
- Cada apertura **siguiente** → un `adjustment` por la **diferencia** contra el `counted_cash` de la sesión anterior. Si coinciden, no se emite nada. Si no, queda registrado como lo que siempre fue: un descuadre que nadie miró.
- Cada cierre con diferencia → su `adjustment` de arqueo (§2.3).

Reconstruye la cadena hacia atrás y deja el saldo derivado cuadrando con el último conteo real. **Y de paso revela cuántos descuadres silenciosos hubo**, que es información que hoy no existe.

`list_accounts` pasa a calcular el saldo de una `cash` igual que el de una `bank`.

### Paso 2 — Abrir deja de pedir el número — **HECHO en el backend**, falta la pantalla

El diálogo muestra el saldo que hay y ofrece **contar** (opcional pero recomendado). Si se cuenta y difiere → motivo obligatorio y ajuste, con el responsable del turno que empieza.

### Paso 3 — Cerrar emite el ajuste — **HECHO**

`close_session` ya calcula la diferencia y ya exige justificación. Solo falta que además escriba el movimiento. Es aditivo: el acta sigue mostrando lo mismo.

### Paso 4 — `vault`, y levantar el límite de una sola cuenta de efectivo — pendiente

Ya sin la dependencia de la sesión, varias ubicaciones dejan de ser peligrosas.

> **Nota operativa:** `alter type ... add value` no corre dentro de una transacción en Postgres. Va en su propia migración, antes de la que use el valor. Y el orden de despliegue del proyecto aplica igual — expandir, desplegar, contraer.

## 7. Lo que este modelo NO resuelve, y hay que arreglar igual

**La sesión que queda abierta días.** Es independiente de todo lo anterior y hoy está pasando: la sesión de LA GRAN LEGAL sigue abierta **desde el 03/09**. Seis días de movimientos en un solo turno, un acta que va a salir fechada el 03/09 con operaciones del 09/09, y reportes por `session_date` atribuyendo al día equivocado. Está registrado como F9-01 y el fix es barato — mostrar la fecha en el banner cuando la sesión no es de hoy, dato que ya viaja en la respuesta.

Con el modelo nuevo el daño es menor (el saldo ya no depende del turno), pero el acta y los reportes se siguen ensuciando. Va aparte y va primero, porque es de un día de trabajo.

## 8. Lo que sigue siendo decisión del negocio

Y son pocas, que es la señal de que el modelo está bien puesto:

1. **¿Contar al abrir es obligatorio u opcional?** Obligatorio da la mejor atribución de faltantes (el descuadre cae en el turno donde apareció); opcional es más ágil. Se puede dejar opcional y que la app lo sugiera.
2. **¿Quién puede declarar un descuadre?** Hoy `cashbox.open_close` alcanza para abrir. Si el ajuste de arqueo va a mover el saldo del libro, quizá merezca el trato de la reapertura, que tiene permiso propio (`cashbox.reopen`).
3. **¿Hay tope para un ajuste sin autorización?** Un faltante de 2.000 y uno de 2.000.000 no son el mismo hecho. Se puede dejar sin tope (el proyecto ya eligió *"advertir sin bloquear"* en otros lados) o pedir un permiso extra por encima de cierto monto.

Ninguna de las tres bloquea el Paso 1.
