# RECARGOS.md — Ampliación de préstamo sobre un contrato vivo (spec)

> **Estado: IMPLEMENTADO** (migración `00051`, backend y frontend desplegados el 10/09/2026); **la fecha del sucesor cambió el 11/09/2026 — leer §4-bis antes que §5 y §8.2, que quedaron superadas** (migración `00053`). Pedido por Mateo el 09/09/2026 tras probar con el cliente; las dos decisiones que lo bloqueaban se respondieron en §8.
>
> Verificado en vivo, no solo en tests: contrato #28 (1.000.000 sobre una prenda de 2.000.000 al 70 % → 400.000 de cupo) ampliado a #29 con capital 1.400.000, el viejo `superseded` con sus prendas `transferred`, interés mensual de 50.000 a 70.000, y a la caja salieron **solo los 400.000**. La pantalla comprobada con un navegador real (`scripts/qa/ui_recargo.js`): la cadena se ve en los dos sentidos, el panel no aparece en el contrato cerrado, y en el sucesor —que ya agotó el cupo— explica por qué no se puede en vez de esconderse.
> **Qué resuelve:** una prenda avaluada en 2.000.000 sobre la que se prestó 1.000.000 tiene 1.000.000 de cupo sin usar. El cliente vuelve a los pocos días y quiere retirar parte de ese sobrante.
> **Principio de diseño:** un recargo **no modifica** el contrato: lo **sucede**. Mismo espíritu que `MIGRACION_CONTRATOS.md` — reusar lo que ya existe (máquina de estados, snapshot, consecutivos, caja) en vez de abrir una excepción dentro de las reglas de plata.

---

## 1. Por qué no puede ser un `UPDATE` del capital

Es la conclusión a la que Mateo ya llegó, y conviene dejar escrito **por qué** es forzosa y no una preferencia.

El interés de este sistema es `tasa × saldo_capital_actual`, cobrado en **meses completos** anclados a `interest_paid_until` (`CLAUDE.md` → "Intereses y abonos"). Toda la máquina de estados —`months_owed`, mora, prórroga, remate— cuelga de ese ancla.

Subir `capital_balance` a mitad de mes rompe el ancla: el mes en curso quedaría a medio cobrar sobre un capital que ya cambió, y no hay forma de expresar eso en un modelo que solo entiende meses enteros. Habría que prorratear, y prorratear obliga a tocar `quote_payment_options`, `compute_status`, el job nocturno y el remate — es decir, reescribir el núcleo del producto para un caso de borde.

**Y hay una razón legal además de una técnica:** el contrato firmado dice un capital. Si el capital cambia, el papel que el cliente firmó ya no describe la deuda. El documento nuevo no es burocracia: es la obligación.

## 2. El flujo: liquidar y suceder, en una sola transacción

`POST /contracts/{id}/extend-loan` — permiso nuevo **`contracts.extend_loan`**, `Idempotency-Key` obligatorio (es una operación de dinero).

```jsonc
{
  "amount": 800000,          // lo que se le entrega HOY (solo el delta)
  "payment_method": "cash",
  "account_id": "uuid|null", // como en cualquier desembolso
  "items": []                // OPCIONAL: prendas adicionales que deja en garantía
}
```

En **una** transacción (regla 4 de `CLAUDE.md`: una operación de negocio = una transacción):

1. **Validar** ventana, estado y cupo (§3, §4).
2. **Exigir los intereses al día.** Si `months_owed > 0` → `409 CONTRACT_INTEREST_OVERDUE`, hay que abonar primero por el camino normal. **El interés adeudado nunca se suma al capital nuevo**: capitalizar interés es anatocismo, y además volvería el saldo imposible de auditar contra los recibos.
3. **Contrato viejo** → `status = 'superseded'`; sus `contract_item` → `status = 'transferred'`.
4. **Contrato sucesor**, con `number` propio de `next_counter(company, 'CONTRACT')`:

   | Campo | Valor |
   |---|---|
   | `principal` | `capital_balance` del viejo **+** `amount` |
   | `capital_balance` | igual al `principal` recién calculado |
   | `start_date` | hoy (zona de la empresa) |
   | `interest_paid_until` | hoy — ver §5 |
   | `due_date` | `hoy + term_months` |
   | tasa / plazo / ventana / prórroga | **copiados del viejo**, no de la config actual: ampliar no renegocia lo pactado |
   | `appraisal_value` | la del viejo + la de las prendas nuevas si las hay |
   | `parent_contract_id` | el viejo |
   | `root_contract_id` | el `root` del viejo, o el viejo si era el primero |
   | `signed_photo_url` | **null** — hay que imprimirlo y firmarlo (§6) |

5. **Re-crear los `contract_item`**: mismas prendas, mismas tasaciones, mismas fotos, más las nuevas. Son filas nuevas porque `contract_item` cuelga de `contract_id`; las viejas quedan como evidencia de lo que respaldaba el contrato anterior.
6. **`cash_movement(loan_disbursed, out, pawn, amount)`** referenciando el contrato **nuevo** — solo el delta. El capital viejo ya salió de la caja el día del contrato original; volver a moverlo lo contaría dos veces en `/reports/pawn-performance`.
7. **Auditar** `extend_loan` con `before` (contrato viejo, su capital) y `after` (contrato nuevo, su capital y el monto entregado).

> **El precedente ya existe:** `POST /contracts/import` crea un contrato cuyo `principal` no sale de la caja. Acá es el caso intermedio —parte del principal ya se desembolsó antes, parte sale hoy— y el modelo lo soporta sin inventar nada.

## 3. La ventana de tiempo

Mateo la pidió explícita: **se define al crear el contrato, por defecto 28 días**, y pasada no hay recargo.

Campo nuevo en `contract`, **SNAPSHOT** como todo lo demás:

```sql
extension_window_days int not null default 28 check (extension_window_days >= 0)
```

Digitable en el formulario de creación (con 28 precargado). Snapshot y no configuración de empresa por la misma razón que la tasa: cambiar el default no puede alterar contratos ya firmados.

**La ventana se mide desde `root_contract_id.start_date`, nunca desde el contrato actual.** Sin esto, un recargo de $1 el día 27 reinicia el reloj y el cliente puede encadenar recargos para siempre. Con el ancla en la raíz de la cadena, 28 días son 28 días haya habido uno o cinco recargos.

`0` = sin recargos (el negocio que no quiera la función la apaga por contrato).

## 4. El cupo, y una trampa de configuración

El cupo natural es el sobrante de la tasación:

```
disponible = appraisal_value × (max_ltv_pct / 100) − capital_balance
```

**Ojo con el ejemplo de Mateo:** "avaluado en 2 millones, prestó 1 millón, puede retirar el otro millón" asume LTV del 100 %. Pero el sistema ya tiene `max_ltv_pct` heredado de la categoría — y en LA GRAN LEGAL **está en 10 %**, que daría cupo negativo siempre. Antes de implementar esto hay que revisar ese 10 % (ver §9), o el recargo nace inutilizable.

Sin `appraisal_value` no hay techo que calcular: el recargo se rechaza con `409 CONTRACT_WITHOUT_APPRAISAL` (§9).

> **Decidido — ver §8.1.** No es advertir siempre ni bloquear siempre: depende del permiso **`contracts.override_ltv`**. Quien no lo tiene queda bloqueado; quien lo tiene recibe la advertencia y queda auditado como quien autorizó. Y aplica también a `POST /contracts`, para que la misma regla no se comporte distinto en dos pantallas.

## 4-bis. La fecha del sucesor — **cambiado el 11/09/2026** (migración `00053`)

> Esta sección corrige lo que dicen §5 y §8.2, que quedan como registro de lo que se decidió antes y por qué se cambió.

**Lo que reportó Mateo probando con el cliente:** presta 1.000.000 el día 1, el cliente recarga 500.000 el día 25, y el sucesor nacía con `start_date = interest_paid_until = hoy`. Resultado: la próxima cuota se cobraba el **25 de octubre** en vez del 1. El cliente tenía una fecha de pago que se le movía sola cada vez que volvía por plata.

**La respuesta no es una cuarta política: es la que no necesita política.** El sucesor **hereda el ancla**:

| Campo | De dónde sale |
|---|---|
| `start_date` | de la **raíz** de la cadena — la fecha del papel original, que no se mueve nunca |
| `interest_paid_until` | del contrato **padre** — si el cliente abonó meses en el medio, el ancla ya avanzó, y volver a la raíz le cobraría meses que ya pagó |
| `due_date` | del padre — el plazo tampoco se reinicia: es el mismo préstamo con más capital |

**Esto disuelve la pregunta de §5 en vez de contestarla.** Ya no hay "pedazo de mes corrido sobre el capital viejo" que perdonar, cobrar o prorratear: el mes en curso se cobra entero al capital nuevo cuando venza. Y le gana a `forgive` por los dos lados — hoy un recargo el día 27 perdonaba ~45.000 **y además** corría la próxima fecha de pago 27 días.

**El filo, dicho en voz alta:** un recargo dos días antes del aniversario hace que el cliente pague un mes completo sobre el capital nuevo casi de inmediato. No es anatocismo —no se capitaliza interés, es plata que se entregó— y es lo que hace la mayoría de compraventas. Pero la pantalla lo dice **antes** de confirmar: *"Próxima cuota: 1 de octubre · $75.000"*. Un cobro correcto que el cliente no vio venir se reclama igual que uno equivocado.

### La palanca ya estaba puesta

`extension_interest_policy` existía desde `00051` con dos valores y **nada la exponía** — §8.2 la dejó ahí para "el día que aparezca una regla". Este es ese día. Se le agregó `keep_anchor`, que pasa a ser el default:

| Valor | Qué hace |
|---|---|
| `keep_anchor` *(default desde 00053)* | El sucesor hereda la fecha del original. La fecha de cobro no se mueve |
| `forgive` | El reloj se reinicia; los días corridos se perdonan |
| `charge_month` | Exige el mes de interés pagado antes de ampliar |

Los contratos **ya firmados conservan su `forgive`**: la columna es SNAPSHOT y cambiar el default no puede alterar lo pactado, igual que con la tasa.

### La trazabilidad, que con este cambio deja de ser un extra

Antedatar `start_date` rompe las dos cosas que respondían "¿cuándo se hizo el recargo?":

- El detalle del contrato decía *«Sucede a un contrato anterior, ampliado el {start_date}»* — pasaría a mentir con semanas de diferencia.
- El impreso dice `Fecha: {start_date}`. **El papel que el cliente firma el 25 saldría fechado el 1, sin nada más: un documento antedatado, que es peor que el problema que se resolvió.**

Por eso `00053` agrega dos columnas, ambas `NULL` en un contrato que no nació de un recargo:

```sql
extended_on      date            -- el día REAL, en la zona de la empresa
extension_amount numeric(14,2)   -- el DELTA entregado, no el capital total
```

**Por qué columnas y no derivarlo de `created_at`:** `created_at` es un `timestamptz` y el "día" del negocio es el de la zona de la **empresa** — convertirlo en cada lectura es exactamente el cálculo que a este proyecto ya le costó el bug de las 5 horas dos veces. Además `created_at` no distingue un sucesor de un contrato importado, y **el monto no está en ninguna columna**: vive en el `cash_movement` y en el `audit_log`. Para escribir *"recargo de $500.000 el 25/09"* en la pantalla y en el papel había que cruzar tablas.

De regalo: `extended_on is not null` responde *"¿este contrato es un sucesor?"* sin mirar la cadena.

### Qué muestra la aplicación

- **Detalle del contrato:** *«Sucede a un contrato anterior — recargo de $500.000 entregado el 25/09/2026. Conserva la fecha del contrato original (01/09/2026), así que el interés se sigue cobrando el día de siempre — ahora sobre el capital ampliado.»*
- **Impreso:** un recuadro propio con las dos fechas y el monto del recargo, para que nadie pueda leer el documento como antedatado.
- **Antes de confirmar:** la fecha y el monto de la próxima cuota.

---

## 5. El interés del mes en curso — la pregunta de fondo

> **Superada por §4-bis (11/09/2026).** Con el ancla heredada no hay mes en curso que resolver. Se conserva porque explica por qué `prorate` no existe y por qué el modelo solo entiende meses completos.


Al momento del recargo el cliente casi siempre está **dentro** de un mes ya empezado y no vencido (la ventana son 28 días). Ese pedazo de mes corrido sobre el capital viejo hay que resolverlo. Tres respuestas, y la tercera no es viable:

| | Qué hace | Costo | Veredicto |
|---|---|---|---|
| **(a) El reloj se reinicia** — **la elegida (§8.2)** | `interest_paid_until = hoy` en el sucesor; los días corridos sobre el capital viejo se perdonan | Acotado por la ventana: ≤28 días. Sobre 1.000.000 al 5 %, ≤46.000 | **Recomendada.** No rompe ninguna regla existente y no castiga al cliente por volver |
| **(b) Cobrar un mes completo** del capital viejo como condición del recargo | El cliente paga un abono normal de 1 mes antes de ampliar | Cobra 30 días por 5. Duro, pero es lo que hacen muchas compraventas | Viable, cero código nuevo (es un abono normal) |
| **(c) Prorratear** los días corridos | Cobrar la fracción exacta | Rompe "solo meses completos", que es la regla que sostiene abonos, estados, prórroga y remate | **Descartar** |

La diferencia entre (a) y (b) es una decisión de negocio, no de arquitectura: las dos se implementan igual de fácil. (a) es un `interest_paid_until = hoy`; (b) es (a) más una precondición de que el contrato venga con el mes pagado.

**Después del recargo no hay ambigüedad:** el sucesor arranca limpio, con su capital nuevo y su ancla en hoy. El interés del mes siguiente es `tasa × (capital_viejo + recargo)`, calculado por el mismo código de siempre. Ninguna fórmula nueva.

## 6. Qué pasa con el contrato y la foto anteriores

- **El contrato viejo no se toca ni se borra.** Queda `superseded`, con su `signed_photo_url`, sus abonos y sus recibos intactos. Es la evidencia de lo que se firmó ese día, y `contract_payment` es inmutable por diseño.
- **El sucesor nace sin foto firmada.** Esa es exactamente su razón de ser: hay un capital nuevo, hay que imprimirlo y que el cliente lo firme. El flujo de impresión que ya existe sirve tal cual.
- **En pantalla, la cadena tiene que verse.** El viejo: *«Ampliado el 09/09/2026 → contrato #28»*. El nuevo: *«Sucede al contrato #22»*. Los dos con link. Sin eso, un contrato `superseded` parece un contrato abandonado.
- **El paz y salvo sigue exigiendo `paid`.** Un `superseded` no lo genera: el cliente sigue debiendo, solo que en otro documento. `get_settlement_info` ya compara contra `'paid'` literal, así que funciona sin tocarlo — pero hay que dejar un test que lo fije.

## 7. Los campos y estados nuevos (una migración)

```sql
alter type contract_status      add value 'superseded';
alter type contract_item_status add value 'transferred';

alter table public.contract
  add column extension_window_days int not null default 28
    check (extension_window_days >= 0),
  add column parent_contract_id uuid references public.contract(id),
  add column root_contract_id   uuid references public.contract(id);

create index ix_contract_root on public.contract (company_id, root_contract_id)
  where root_contract_id is not null;
```

`superseded` es **terminal**: hay que agregarlo a `_TERMINAL_STATUSES` en `contracts/rules.py`, o el recálculo en lectura y el job nocturno lo devolverían a `in_arrears` en cuanto pase un mes.

> **Ojo operativo:** `alter type ... add value` no corre dentro de una transacción en Postgres. Va en su propia migración, antes de la que use el valor.

## 8. Las decisiones, tomadas (10/09/2026)

Mateo respondió las dos que bloqueaban. Quedan escritas con su porqué para que no se vuelvan a discutir.

### 8.1 · El cupo: un permiso, no una advertencia fija ni un interruptor

Mateo propuso una casilla por empresa ("advierte" / "bloquea"). Se descartó por tres razones: nadie sabe responder esa pregunta al dar de alta una empresa; parte el producto en dos comportamientos que hay que documentar, soportar y testear; y contradice al propio sistema, donde **crear** un contrato por encima del LTV advierte — la misma regla se comportaría distinto en dos pantallas.

**La forma que el proyecto ya tiene para esto es un permiso**, y el precedente funciona: `sales.return_override_time_limit` rechaza la devolución fuera de plazo *salvo* que lo tengas.

**`contracts.override_ltv`** (permiso nuevo):

| Quién | Al pasarse del cupo |
|---|---|
| Sin el permiso | **Bloqueado**, con un mensaje que nombra a quién pedírselo |
| Con el permiso | **Advertencia** (`ltv_warning`) + auditado quién autorizó |

Lo que gana sobre el booleano: **la casilla sigue siendo expresable** —quien quiera "siempre advertir" se lo da a todos, quien quiera "siempre bloquear" a nadie— y encima cubre el caso que un booleano no puede: que el asesor no pueda y el dueño sí, que es lo que va a querer la mayoría. Y deja auditado no solo *que* se pasó del LTV, sino **quién lo autorizó**.

**Aplica también a `POST /contracts`**, no solo al recargo: si no, volvemos a la misma regla con dos comportamientos. Eso cambia el comportamiento actual, así que **la migración otorga el permiso a todo rol que hoy pueda crear contratos** — nadie pierde acceso el día del despliegue, y la empresa que quiera apretar se lo quita al Asesor. Mismo criterio que usó `00029` con los permisos de cuentas.

### 8.2 · El interés del mes en curso: perdonar, con la palanca puesta

> **Revertido el 11/09/2026 — ver §4-bis.** El default pasó a `keep_anchor`: el sucesor hereda el ancla en vez de reiniciarla. Lo que sigue queda como registro de por qué se eligió `forgive` primero, y de que la palanca que se dejó puesta acá fue justo la que hizo falta tres días después.

**Se perdona** (opción (a) de §5): el sucesor arranca con `interest_paid_until = hoy`.

Mateo pidió dejarlo abierto a cobrarlo según reglas futuras, con la intuición de que *"si hizo el recargo al día siguiente del contrato, no tendría sentido perdonarlo"*. **Los números van al revés**, y conviene dejarlo escrito porque es contraintuitivo. Sobre un capital de 1.000.000 al 5 % mensual:

| Recargo el… | Interés corrido perdonado |
|---|---|
| día 1 | **1.667** — nada |
| día 14 | ~23.000 |
| día 27 | **~45.000** — casi un mes entero |

Al día siguiente no hay nada que perdonar. **El caso que duele es el recargo al final de la ventana**, donde el cliente se lleva plata nueva *y* un mes de interés casi completo del capital viejo. Y hay un segundo efecto en la misma dirección: el reloj se reinicia, así que un recargo el día 27 además corre la próxima fecha de pago 27 días.

**La palanca**, snapshot en el contrato igual que `extension_window_days`:

```sql
extension_interest_policy text not null default 'forgive'
  check (extension_interest_policy in ('forgive', 'charge_month'))
```

| Valor | Qué hace |
|---|---|
| `forgive` *(default)* | El reloj se reinicia; los días corridos se perdonan |
| `charge_month` | Exige el mes de interés pagado antes de ampliar |

Una columna, un default, **cero UI el día uno**. El día que aparezca una regla: se cambia el default o se expone el campo.

**`prorate` no está y no va a estar.** Prorratear rompe la regla de meses completos que sostiene abonos, mora, prórroga y remate — habría que reescribir `quote_payment_options`, `compute_status`, el job nocturno y el remate para un caso de borde.

### 8.3 · Reglas candidatas para cuando haya datos

Ninguna se puede elegir hoy: **hasta que no haya recargos reales no hay con qué medir cuál duele.** Por eso el campo y no la regla.

1. **Umbral de días** *(la más probable)* — perdonar en los primeros N días, cobrar el mes después. Sigue la curva del costo real de §8.2.
2. **Umbral de monto** — perdonar si el interés corrido es menor a cierto % del recargo entregado. Se autorregula sin fechas.
3. **Un recargo gratis** — el primero perdona, los siguientes cobran. Es la que corta el encadenamiento de recargos chicos.
4. **Proporcional al recargo** — si el cliente saca mucho, perdonar sale barato porque el negocio gana con el capital nuevo.

## 9. Preguntas que siguen abiertas

1. **¿Se puede ampliar un contrato en mora?** Recomendación: sí, pero pagando primero los meses adeudados — que es lo que el paso 2 del flujo ya exige.
4. **¿Se pueden dejar prendas nuevas en el recargo, o solo sacar plata sobre las mismas?** El diseño lo soporta (`items` opcional); es decidir si la pantalla lo ofrece.
5. **¿Sin tasación se puede ampliar?** Sin `appraisal_value` no hay cupo que calcular.
6. **¿Cuántos recargos encadenados?** Recomendación: sin límite — la ventana anclada a la raíz (§3) ya los acota sola.

## 10. Lo que hay que revisar de arrastre al implementar

- **`max_ltv_pct = 10 %` en LA GRAN LEGAL.** Con ese valor el cupo es negativo para cualquier contrato y el recargo no sirve. Casi seguro es un dedazo (un LTV del 10 % significa prestar 100.000 sobre una prenda de un millón); hoy ya hace que 17 de 22 contratos salgan con `ltv_warning`.
- **Filtros y badges** de `/contratos`: el estado nuevo necesita etiqueta en español y color propio.
- **`ready-for-auction`** no se ve afectado: filtra por `status = 'in_extension'`, y `superseded` nunca lo es.
- **Reportes.** `pawn-performance` y `/profit` cuentan `loan_disbursed`; como solo se mueve el delta, los números no se inflan. "Contratos activos" contará el sucesor y no el viejo, que es lo correcto.
- **El historial del cliente** debe leer la cadena como una sola historia, no como contratos sueltos — es lo que hace `root_contract_id`.
- **El nombre en pantalla.** "Recargo" es la palabra del cliente. Para un producto que se le vende a cualquier compraventa, **"Ampliar préstamo"** dice lo que hace sin jerga de una sola casa. Vale usar "recargo" como sinónimo visible si el cliente lo pide, pero la API y los docs deberían hablar de `extend_loan`.

## 11. Definición de Hecho (cuando se implemente)

- **Unitarios:** cupo con y sin `max_ltv_pct`; ventana medida desde la raíz de la cadena (incluido el caso de tres recargos encadenados); `superseded` es terminal y `compute_status` no lo mueve.
- **Integración:** recargo sin caja abierta → `409 CASH_SESSION_NOT_OPEN`; con meses adeudados → `409 CONTRACT_INTEREST_OVERDUE`; fuera de ventana → `409`; el `cash_movement` es **solo** el delta; las prendas viejas quedan `transferred` y las del sucesor `in_custody`; reintento con la misma `Idempotency-Key` → el mismo contrato sucesor; `GET /settlement` sobre un `superseded` → 404.
- **Permiso:** rol sin `contracts.extend_loan` → 403 (y el endpoint aparece en el mapa de `scripts/qa/map_endpoints.py`).
- **Auditoría:** verificada en test, con el código de error en `API_GUIDE.md` §15 — el catálogo se compara con el código en las dos direcciones (`tests/unit/test_error_catalog.py`), así que un código nuevo sin documentar rompe la suite.
