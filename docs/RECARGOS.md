# RECARGOS.md — Ampliación de préstamo sobre un contrato vivo (spec)

> **Estado:** análisis y diseño, **sin implementar**. Pedido por Mateo el 09/09/2026 tras probar con el cliente.
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

Sin `appraisal_value` no hay techo que calcular: el recargo se rechaza (`409 CONTRACT_WITHOUT_APPRAISAL`) o se permite sin tope, según §8.

**Recomendación: advertir, no bloquear** — es el precedente que el propio proyecto ya tomó con `ltv_warning` al crear un contrato, y el que QA recomendó para los desembolsos sin efectivo (`DECISIONES_PENDIENTES.md` §3). Pasarse del cupo deja `ltv_warning = true` en el sucesor y sigue. Si el negocio prefiere tope duro, es un `if` — pero entonces las tres operaciones deberían comportarse igual, no dos advirtiendo y una bloqueando.

## 5. El interés del mes en curso — la pregunta de fondo

Al momento del recargo el cliente casi siempre está **dentro** de un mes ya empezado y no vencido (la ventana son 28 días). Ese pedazo de mes corrido sobre el capital viejo hay que resolverlo. Tres respuestas, y la tercera no es viable:

| | Qué hace | Costo | Veredicto |
|---|---|---|---|
| **(a) El reloj se reinicia** | `interest_paid_until = hoy` en el sucesor; los días corridos sobre el capital viejo se perdonan | Acotado por la ventana: ≤28 días. Sobre 1.000.000 al 5 %, ≤46.000 | **Recomendada.** No rompe ninguna regla existente y no castiga al cliente por volver |
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

## 8. Preguntas que solo puede responder el negocio

1. **¿Cupo con tope duro o advertencia?** (§4 — recomendación: advertencia, por consistencia con el resto del sistema)
2. **¿El interés del mes en curso se perdona (a) o se cobra completo (b)?** (§5)
3. **¿Se puede ampliar un contrato en mora?** Recomendación: sí, pero pagando primero los meses adeudados — que es lo que el paso 2 del flujo ya exige.
4. **¿Se pueden dejar prendas nuevas en el recargo, o solo sacar plata sobre las mismas?** El diseño lo soporta (`items` opcional); es decidir si la pantalla lo ofrece.
5. **¿Sin tasación se puede ampliar?** Sin `appraisal_value` no hay cupo que calcular.
6. **¿Cuántos recargos encadenados?** Recomendación: sin límite — la ventana anclada a la raíz (§3) ya los acota sola.

## 9. Lo que hay que revisar de arrastre al implementar

- **`max_ltv_pct = 10 %` en LA GRAN LEGAL.** Con ese valor el cupo es negativo para cualquier contrato y el recargo no sirve. Casi seguro es un dedazo (un LTV del 10 % significa prestar 100.000 sobre una prenda de un millón); hoy ya hace que 17 de 22 contratos salgan con `ltv_warning`.
- **Filtros y badges** de `/contratos`: el estado nuevo necesita etiqueta en español y color propio.
- **`ready-for-auction`** no se ve afectado: filtra por `status = 'in_extension'`, y `superseded` nunca lo es.
- **Reportes.** `pawn-performance` y `/profit` cuentan `loan_disbursed`; como solo se mueve el delta, los números no se inflan. "Contratos activos" contará el sucesor y no el viejo, que es lo correcto.
- **El historial del cliente** debe leer la cadena como una sola historia, no como contratos sueltos — es lo que hace `root_contract_id`.
- **El nombre en pantalla.** "Recargo" es la palabra del cliente. Para un producto que se le vende a cualquier compraventa, **"Ampliar préstamo"** dice lo que hace sin jerga de una sola casa. Vale usar "recargo" como sinónimo visible si el cliente lo pide, pero la API y los docs deberían hablar de `extend_loan`.

## 10. Definición de Hecho (cuando se implemente)

- **Unitarios:** cupo con y sin `max_ltv_pct`; ventana medida desde la raíz de la cadena (incluido el caso de tres recargos encadenados); `superseded` es terminal y `compute_status` no lo mueve.
- **Integración:** recargo sin caja abierta → `409 CASH_SESSION_NOT_OPEN`; con meses adeudados → `409 CONTRACT_INTEREST_OVERDUE`; fuera de ventana → `409`; el `cash_movement` es **solo** el delta; las prendas viejas quedan `transferred` y las del sucesor `in_custody`; reintento con la misma `Idempotency-Key` → el mismo contrato sucesor; `GET /settlement` sobre un `superseded` → 404.
- **Permiso:** rol sin `contracts.extend_loan` → 403 (y el endpoint aparece en el mapa de `scripts/qa/map_endpoints.py`).
- **Auditoría:** verificada en test, con el código de error en `API_GUIDE.md` §15 — el catálogo se compara con el código en las dos direcciones (`tests/unit/test_error_catalog.py`), así que un código nuevo sin documentar rompe la suite.
