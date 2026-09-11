# SUCURSALES.md — Multi-caja y multi-sucursal (fase 2)

> **Estado: APLAZADO por decisión de Mateo (10/09/2026).** No se trabaja nada de multi-caja ni de multi-sucursal por ahora. Este documento es el análisis previo y el lugar donde se retoma el día que haga falta.
>
> **Lo que sí se hizo** es adecuar la arquitectura para que esa puerta no se cierre: que los datos que se crean hoy sigan sirviendo cuando llegue. Verificado contra dev el 10/09/2026 (§4) y aplicadas las tres adecuaciones de §5 — **ninguna construye la función**.
>
> **Falta desplegar el backend** (`fly deploy`) para que la Acción B valga en dev. La A ya está aplicada en las dos bases.
>
> **Parte I** es el estado de hoy y por qué aplazar es seguro. **Parte II** es la guía de implementación completa para el día que se construya: qué cubre, cómo funcionaría, qué falta y en qué orden.

---

## 1. Multi-caja y multi-sucursal no son lo mismo

El proyecto viene tratándolas como una sola cosa y **son dos trabajos de tamaño muy distinto**. Conviene separarlas antes de estimar nada.

| | **Multi-caja** (multi-mostrador) | **Multi-sucursal** |
|---|---|---|
| Qué resuelve | Dos cajeros cobrando en el mismo local | Dos locales |
| Qué separa | El **cajón** — para que un faltante tenga dueño | El **inventario, la bóveda, la gente y la contabilidad** |
| Qué existe hoy | Casi todo el modelo; falta trabajo de aplicación | **Nada** |
| Tamaño | Días | Semanas, y toca los 13 módulos |
| Dónde está descrito | [`CAJA_TRAZABILIDAD.md`](CAJA_TRAZABILIDAD.md) §6 | Este documento |

**Multi-caja ya está a medio camino:** `cash_register` existe desde `00007`, `cash_session` cuelga de `register_id`, el índice de sesión abierta ya es **por registradora** (o sea que la base ya admite dos turnos abiertos a la vez) y `account.register_id` quedó puesta y vacía en `00049`.

**Multi-sucursal no empieza ahí.** Empieza en una pregunta que el modelo no puede responder: *¿dónde está esta cadena de oro?*

## 2. Corrección: lo que `CONTEXTO.md` promete no existe

`docs/CONTEXTO.md` §3 dice:

> *"Sucursales: sin sedes hoy; **diseño listo para activar multi-sucursal en F2 sin migración** (tabla branch + branch_id nullable en cash_register y app_user; consecutivos siguen por empresa)."*

Verificado contra el esquema real el 10/09/2026, y **es falso en dos puntos**:

- **La tabla `branch` no existe.** No aparece en ninguna de las 51 migraciones. Lo único que hay es un comentario en `00007_cashbox.sql` que la anuncia.
- **"Sin migración" no puede ser cierto.** Crear una tabla y una columna es una migración. Lo que el texto quiere decir es *"sin migración de DATOS"*, y eso sí es verdad (§4).

Es el tercer caso del mismo patrón, y ya está escrito como principio del proyecto: **un comentario puede estar mintiendo; verificar lo que el SQL hace, no lo que promete.** Los dos anteriores fueron el índice de `00024` y la racionalización de `ARCHITECTURE §12`.

Lo que sí es cierto de esa frase: **"consecutivos siguen por empresa"** es una decisión tomada y sigue siendo la correcta (§12).

---

# Parte I — Hoy

## 3. La pregunta correcta

No es *"¿cuándo construimos sucursales?"*. Es:

> **¿Los datos que se están creando hoy van a servir el día que existan dos sedes, o van a quedar sin poder atribuirse?**

La respuesta depende de una sola cosa: **mientras haya un solo lugar físico, todo lo que se registra pertenece a ese lugar sin ambigüedad.** El backfill futuro es *"todo lo existente es Sede principal"*, y es correcto por construcción. No hay que adivinar nada.

El riesgo no es el modelo. Es que esa premisa deje de ser cierta **sin que nadie lo note**.

## 4. Qué se verificó (dev, 10/09/2026)

Consulta de solo lectura contra la base de dev:

| Empresa | Registradoras | Cuentas `cash` | Activas | Con `register_id` | Movimientos |
|---|---|---|---|---|---|
| Compraventa de Prueba QA | 1 | 1 | 1 | 0 | 0 |
| Empresa Demo Front | 1 | 1 | 1 | 0 | 47 |
| **LA GRAN LEGAL** | **1** | **1** | **1** | **0** | **14** |
| ZZ Pruebas — auditoría identidad | 1 | 1 | 1 | 0 | 0 |
| ZZ Pruebas — repro 03/09 | 1 | 1 | 1 | 0 | 5 |
| ZZ QA — auditoria 08/09 | 1 | 2 | 1 | 0 | 43 |
| ZZ QA-B — aislamiento 08/09 | 1 | 1 | 1 | 0 | 0 |

**Tres conclusiones, y las tres son buenas:**

1. **Una registradora por empresa, sin excepción.** Y no puede haber otra: **ningún endpoint crea un `cash_register`** — solo `platform.create_company_defaults` al dar de alta la empresa. Verificado con grep sobre todo el backend. El riesgo de una segunda registradora es hoy un `insert` a mano, no un camino de la aplicación.
2. **Una sola cuenta de efectivo activa por empresa.** El único caso con dos es el laboratorio de QA (`Cajon mostrador 2`, **inactiva**, con 2 movimientos que se anulan entre sí) — el fixture deliberado que documenta por qué dos cajones hacen incuadrable el arqueo. **LA GRAN LEGAL quedó con una sola** (`Caja N°1`): las tres que el cliente había creado ya no están.
3. **`account.register_id` estaba vacía en las 7 empresas**, tal como `00049` la dejó. **Ya no**: la migración `00052` la pobló (§5, Acción A). Esta tabla es la foto de **antes**, que es la que justifica por qué se hizo.

**Los 18 movimientos sin `session_id` no son un hueco.** Todos son `adjustment` con `reference_type = 'cash_session'` — exactamente el diseño de `00048` (el ajuste es de la *cuenta*, no del turno; la trazabilidad va por la referencia). Siguen siendo atribuibles a una registradora a través de la sesión que los produjo.

> **Veredicto: la ventana está abierta y los datos de hoy están a salvo.** Un backfill hecho hoy sería determinista y sin pérdida. No hay nada que reparar.

## 5. Las tres adecuaciones — HECHAS (10/09/2026)

Ninguna construye multi-caja ni multi-sucursal. Las tres son baratas, reversibles y **no cambian ningún comportamiento visible para un usuario**. Lo que hacen es que los datos de hoy sigan siendo migrables y que se sepa si eso deja de ser cierto.

| | Qué | Estado |
|---|---|---|
| **A** | `account.register_id` poblado, y las empresas nuevas nacen ligadas | ✅ migración `00052`, aplicada en **local y dev** |
| **B** | `get_active_register` falla fuerte en vez de tomar "la más antigua" | ✅ código y test — **falta `fly deploy`** |
| **C** | El guardián: un test para el código, un script para los datos vivos | ✅ |

**Suite: 372 tests en verde** (371 previos + 1 nuevo). `ruff` y `mypy` limpios.

### Acción A · `account.register_id` poblado

**El hueco:** `insert_cash_register` e `insert_default_accounts` corrían seguidas en `create_company_defaults` y **no se hablaban**, así que ninguna cuenta de efectivo del sistema sabía a qué caja pertenecía. La columna existía vacía desde `00049`.

| Archivo | Qué cambió |
|---|---|
| `supabase/migrations/00052_account_register_link.sql` | El `UPDATE` de backfill |
| `platform/repository.py` | `insert_cash_register` **devuelve el id**; `insert_default_accounts` lo exige como parámetro |
| `platform/service.py` | Los conecta |
| `tests/integration/test_platform.py` | Que una empresa nueva nazca con su cajón ligado |

`register_id` es un parámetro **obligatorio**, no un `None` por defecto: es lo que hace imposible volver a olvidarlo.

**Aplicada en las dos bases** — local (284 filas, las empresas acumuladas de los tests) y dev remota (7 filas). Solo cuentas `cash` **activas**: la `Cajon mostrador 2` del laboratorio se queda en `NULL`, que es lo correcto para una cuenta desactivada.

**No habilita nada.** Nadie lee esa columna todavía.

### Acción B · `get_active_register` ya no adivina

**El hueco:** `order by created_at limit 1` devolvía **la más antigua en silencio**. Con una registradora es correcto; con dos, la mitad de las operaciones de dinero se registrarían contra una caja al azar sin que nada fallara.

| Archivo | Qué cambió |
|---|---|
| `cashbox/repository.py` | `get_active_register` → **`list_active_registers`**, sin `limit` |
| `cashbox/service.py` | **`_resolve_active_register`**: los cuatro sitios que repetían las mismas tres líneas ahora usan un helper único |
| `core/errors.py` | `MultipleRegistersNotSupportedError` (409) |
| `docs/API_GUIDE.md` §15 | El código, documentado — si no, `test_error_catalog.py` se pone rojo |
| `tests/integration/test_cashbox.py` | Test nuevo, **visto fallar sin el fix** |

Que la regla viva en **un** lugar es el punto: el día que llegue multi-caja se cambia ahí, no en cuatro sitios de los que uno se queda con la versión vieja.

> **Falta desplegar.** La acción A ya está en dev (es de datos); la B es código y **necesita `fly deploy --config fly.dev.toml --app compraventa-backend-dev`** para valer. Mientras no se despliegue, dev sigue con el comportamiento viejo — que hoy es inofensivo porque todas las empresas tienen una registradora.

### Acción C · El guardián, que son dos cosas

**Corrección de una versión anterior de este documento:** se había planteado como "un test guardián". **Un test de CI no puede vigilar esto** — corre contra un Postgres local efímero con fixtures, así que nunca vería que una empresa real creció una segunda registradora. Son dos piezas distintas:

| Pieza | Qué vigila | Dónde corre |
|---|---|---|
| `tests/integration/test_platform.py` · `test_cashbox.py` | Que el **código** mantenga la invariante | CI, en cada PR |
| **`scripts/qa/verificar_sedes.py`** | Los **datos vivos**: cualquier empresa con ≠1 registradora activa, ≠1 cajón activo, o un cajón sin ligar | A mano, contra dev |

```
python scripts/qa/verificar_sedes.py
```

Sale con código 1 si encuentra algo, así que sirve en un cron o en un pipeline. Verificado en vivo: detectó las 7 empresas sin ligar **antes** de la migración y quedó en verde después.

**Lo que el script NO detecta:** dos locales operando sobre UNA sola caja y UN solo cajón. Eso es indistinguible de un local con mucho movimiento, y ninguna consulta lo va a ver. Esa parte depende de que el cliente avise — ver §6, R1.

### Hallazgo incidental: un test que solo fallaba de noche

Corriendo la suite apareció `test_abrir_sin_contar_hereda_el_saldo_del_cajon` en rojo. **No lo rompió este trabajo** (se comprobó con `git stash`): envejecía una sesión con `session_date = current_date - 1`, y `current_date` en Postgres es la fecha del **servidor (UTC)** mientras la sesión se creó con el "hoy" de la **empresa** (America/Bogota).

```
postgres current_date : 2026-09-11   (UTC)
hoy en Bogotá         : 2026-09-10
```

Entre las 7pm y medianoche esas dos fechas no coinciden, así que `current_date - 1` daba **exactamente la fecha que la sesión ya tenía**: el envejecido no hacía nada y el test fallaba con `CASH_SESSION_ALREADY_CLOSED_TODAY`. De día pasaba.

Es **la misma ventana de 5 horas** que el backend ya había arreglado en su día con `tenant_time`/`get_company_today`, reaparecida dentro de un test. Corregido a `session_date - 1`, que es independiente de la zona. Y deja una regla: **la disciplina de "hoy es la fecha de la empresa" vale también en los tests** — un `current_date` en un fixture es el mismo bug con otra ropa.

### Lo que deliberadamente NO se hizo

- **No se creó la tabla `branch`.** Sin un segundo local, una tabla con una fila por empresa es ceremonia: no responde ninguna pregunta y hay que mantenerla.
- **No se tocó `_expected_cash` ni la guarda de un solo cajón.** Funcionan, y su forma actual es justamente la que mantiene los datos atribuibles.
- **No se agregó `branch_id` a ninguna tabla.** Es barato agregarlo cuando exista el concepto; agregarlo vacío hoy es una columna que nadie llena y que la próxima persona no sabe si debe llenar.
- **No se desplegó.** Ver la nota de la Acción B.

## 6. Riesgos

Ordenados por probabilidad × daño. **El principal no es técnico.**

### R1 · La ventana se cierra en silencio — ALTO

**El escenario:** el cliente abre un segundo local (o pone un segundo mostrador) y sigue operando sobre el mismo sistema. Nada falla. Las ventas de los dos sitios entran a la misma lista, el inventario se mezcla, y el arqueo del día pide un número que ya no corresponde a ningún cajón.

**Por qué es el peor:** no hay error, no hay alerta y el sistema sigue "funcionando". Cuando alguien pregunte *"¿cuánto vendió Chapinero el mes pasado?"*, la respuesta va a ser **que ese dato no existe y no se puede reconstruir** — porque nunca se registró de dónde venía cada operación.

**Mitigación:** la Acción C lo detecta del lado del cajón, pero **no cubre el caso de dos locales operando sobre una sola caja**, que es indetectable desde el software. La mitigación real es de comunicación: que Mateo sepa que *el momento de avisar es antes de abrir el segundo local, no después.*

### R2 · Alguien inventa un rodeo — MEDIO

Sin la función, los rodeos naturales son tres, y dos ya están cerrados:

| Rodeo | ¿Está cerrado? |
|---|---|
| Crear una segunda cuenta `cash` | **Sí** — `409 CASH_ACCOUNT_ALREADY_EXISTS` desde `00049` |
| Crear una segunda registradora | **Sí** — no hay endpoint (§4) |
| **Poner la sede en texto libre** (`account.name`, `notes`, `reference`) | **No.** "Caja Chapinero" es legible para un humano y no parseable para una migración |

El tercero es el que queda abierto, y no tiene arreglo técnico razonable: prohibir texto libre sería peor. Es otro caso de comunicación, no de código.

> **Vale nombrar algo que no es obvio:** la guarda de una sola cuenta de efectivo (`00049`) se construyó para que el arqueo cuadre. Pero además es **lo que mantiene los datos atribuibles a futuro**. Conviene saberlo antes de que a alguien le parezca una restricción molesta y la quite.

### R3 · Un rodeo mayor: una empresa por sede — MEDIO

Es tentador y funciona para algunas cosas, pero rompe tres: el **cliente** queda duplicado (y su historial cruzado partido en dos), el **catálogo** hay que mantenerlo dos veces, y **no hay reporte consolidado** — que es justo lo que quiere un dueño con dos locales. Además, las suscripciones se cobran por empresa. Si alguien lo propone como atajo, esto es lo que está comprando.

### R4 · Lo que no sería reconstruible si R1 ocurre — ALTO, pero condicionado a R1

Si se opera con dos sitios sobre un solo registro, esto es lo que **sí** se podría reconstruir y lo que **no**:

| Entidad | ¿Atribuible después? | Por qué |
|---|---|---|
| `cash_session` | **Sí** | `register_id` es `NOT NULL` desde `00007` |
| `cash_movement` | **Sí** | Cuelga de una cuenta (`NOT NULL` desde `00027`) y, con la Acción A, la cuenta cuelga de una registradora |
| `contract`, `sale`, `expense` **en efectivo** | **Sí** | Vía su movimiento de caja → sesión → registradora |
| `sale` **por Sistecrédito o transferencia** | **No** | No toca el cajón: su cuenta es `bank`/`settlement`, que no pertenece a ninguna registradora |
| **`inventory_item`** | **No** | Un lote no tiene ningún vínculo con una sesión ni una registradora. `initial_stock`, `adjustment_in` y los de remate ni siquiera tocan caja |

**El inventario es el que no se recupera**, y es coherente con §8: es el hueco estructural del modelo, no un descuido de registro.

### R5 · Que este documento envejezca — BAJO, y ya mordió una vez

`CONTEXTO.md` afirma desde agosto que esto está listo (§2). El antídoto es el mismo que el proyecto ya usa: que la afirmación tenga **fecha y forma de comprobarse**. Por eso §4 trae la consulta y no una descripción.

## 7. Cómo detectar que la ventana se está cerrando

Tres señales, en orden de anticipación:

1. **Mateo avisa que el cliente va a abrir otro local.** Es la única señal *anticipada* que existe, y por eso es la que más vale.
2. **El script de §5 (Acción C) sale en rojo:** apareció una segunda registradora, un segundo cajón activo, o un cajón sin ligar.
3. **Síntomas tardíos**, cuando ya pasó: un `MULTIPLE_REGISTERS_NOT_SUPPORTED` en los logs, descuadres de arqueo que nadie explica, o alguien pidiendo *"el reporte pero solo de la otra sede"*.

```bash
cd backend-starter && python scripts/qa/verificar_sedes.py
```

Sale con código **1** si encuentra algo, así que sirve tal cual en un cron o en un pipeline. Conviene correrlo **cada vez que se dé de alta una empresa nueva** y, si algún día hay muchas, dejarlo programado.

Y si se prefiere a mano, la consulta equivalente:

```sql
select c.name,
       (select count(*) from cash_register r where r.company_id=c.id and r.active) as registradoras,
       (select count(*) from account a where a.company_id=c.id and a.type='cash' and a.active) as cajones
from company c order by c.name;
```

Cualquier fila con un número distinto de `1|1` es la ventana cerrándose.

---

# Parte II — El diseño, el día que se construya

> **Decisiones tomadas con Mateo el 10/09/2026** (no hay fecha de construcción — es previsión):
>
> 1. **Mismo NIT, varios locales.** Un solo juego de libros. La sede es una **dimensión**, no una entidad legal.
> 2. **El alcance de acceso es del usuario**, restrictivo por defecto (§8.3).
> 3. **No se construye todavía.** Solo las tres acciones de §5, que no son la función.

## 8. El modelo: cómo lo resuelven los sistemas contables serios

### 8.1 · Entidad legal ≠ dimensión

Es la distinción que hay que hacer primero, y donde casi todo el mundo se equivoca:

| | **Entidad legal** | **Dimensión** |
|---|---|---|
| Qué es | Quien tiene NIT y declara impuestos | Un corte de la misma contabilidad |
| SAP | *Company Code* | *Plant / Storage Location*, *Profit Center*, *Segment* |
| NetSuite | *Subsidiary* | *Location*, *Department*, *Class* |
| Odoo | *Company* | *Warehouse*, *Analytic Account* |
| Dynamics 365 | *Legal entity* | *Site / Warehouse*, dimensiones financieras |
| Libros contables | Propios | **Compartidos** |

**Dos locales de la misma compraventa bajo un mismo NIT son una dimensión.** Es lo que NIIF 8 llama *segmentos de operación*, y es lo que permite el reporte consolidado — que es justamente lo que quiere un dueño con dos locales.

**Una empresa por sede es el camino contrario** y hay que descartarlo explícitamente: duplica clientes, parte el catálogo, impide consolidar y en este SaaS además se cobra por empresa.

### 8.2 · La sede se ESTAMPA en el documento, no se deriva

Va contra la intuición y es la decisión de diseño más importante:

> En un sistema contable serio, cada asiento lleva sus dimensiones **escritas en el momento de registrarse**. No se infieren de por dónde pasó la plata.

Tres casos que ya existen y que una derivación desde la caja **no cubre**:

- Una venta por **Sistecrédito** no toca ningún cajón — y sin embargo es de una sede.
- El **arriendo de Chapinero** se paga por transferencia desde el banco de la empresa — y es gasto de Chapinero.
- Un **traslado** toca dos sedes a la vez.

Por eso `branch_id` va en `contract`, `sale`, `expense`, `inventory_entry/exit`, `cash_session` y `audit_log`, no solo en la caja (§11).

### 8.3 · El acceso: tres capas, no una

El error es tratar "¿quién ve qué?" como una sola pregunta. Son tres, con respuestas distintas:

| Capa | Qué incluye | ¿Se parte por sede? |
|---|---|---|
| **Datos maestros** | Clientes, catálogo, productos, proveedores | **Nunca.** Un cliente va al local que le quede cerca, y su historial cruzado tiene que seguir siendo uno solo |
| **Datos operativos** | Caja, stock, contratos, ventas, gastos | **Sí** — alcance del usuario, su sede por defecto |
| **Reportes** | Consolidado y comparativo entre sedes | **Detrás de un permiso propio** (`reports.view_all_branches`) |

**Los sistemas grandes restringen por defecto y otorgan el alcance amplio, no al revés.** SAP lo hace con objetos de autorización por unidad organizativa; NetSuite con *"Restrict to Location"* en el rol; Odoo con `allowed_companies` + *record rules*. **"Todos ven todo" es la respuesta barata, no la profesional** — y conviene dejarlo escrito porque una versión anterior de este documento la recomendaba.

Lo que se pierde con "ven todas", medido honestamente: sobreexposición de datos personales (Ley 1581), **ruido operativo diario** —la cola de remate mezclada, donde el asesor ve 8 contratos de los cuales 5 no son suyos—, y rendición de cuentas más difusa. Y apretarlo después cuesta, no por técnica sino porque quitar un acceso que la gente ya tiene genera fricción.

**Decisión: el alcance es del USUARIO, no del rol.** `app_user` con sus sedes permitidas y una por defecto; los roles siguen globales, para que la matriz de 38 permisos no se multiplique por local.

### 8.4 · Dónde se hace cumplir — y por qué NO hay que decidirlo ahora

> **El modelo de datos es independiente del mecanismo de acceso.** Con `branch_id` poblado en todas partes, se puede arrancar con filtro en el servicio y endurecer a RLS después **sin tocar una sola tabla**.

| | **Filtro en el servicio** *(recomendado para empezar)* | **RLS** |
|---|---|---|
| Claim en el JWT | No hace falta | `branch_id` en el token hook |
| Policies | 0 | ~14 tablas |
| Tests de aislamiento | 0 nuevos | La suite de `tests/rls/` se duplica en concepto |
| Si falla | **Muestra** datos de otra sede de la misma empresa | **Esconde** datos propios |

**Empezar por el servicio**, porque una fuga entre sedes de la misma empresa es una violación de política, no un escape entre clientes distintos — que es para lo que RLS está puesto acá, y ahí está bien. Y el proyecto tiene la disciplina para sostenerlo: cada endpoint con su guard, y un test que verifica que ninguno se quede sin él.

**Con una condición innegociable: un solo punto de verdad para el alcance**, el equivalente de `current_company_id()` en la capa de aplicación. Un filtro repetido en cuarenta consultas es un `where` olvidado esperando — y es exactamente el error que RLS existe para no cometer.

## 9. El hueco más grande, y no está en la caja

**`inventory_item` no tiene ubicación.** Sus columnas son `company_id`, código, categorías, origen, costo, precio, cantidad, estado, fotos y fecha de entrada. Ni una dice dónde está la pieza.

- *"¿Cuántas cadenas tengo?"* deja de tener una sola respuesta correcta.
- Una venta en Kennedy puede **descontar stock que está en Chapinero**: la validación es `quantity >= 0` sobre la fila, no sobre la fila *de esa sede*.
- **No existe el traslado de mercancía entre sedes.** Sí existe el de **plata** (`account_transfer`, `00032`), y es el molde exacto: documento numerado, inmutable, con fecha propia. Hoy mover un anillo solo se puede expresar como un egreso y un ingreso — inventando un costo y rompiendo la trazabilidad.
- **Valorización** y **mercancía sin rotación** dan un número de la empresa. Y "qué no rota" es una pregunta *de vitrina*: lo muerto en Kennedy puede venderse en Chapinero.

### La buena noticia: el modelo producto + lote ya encaja

`00021`–`00023` separaron **qué es** (producto: nombre, categoría, precio, SKU) de **el hecho de compra** (lote: costo, proveedor, fecha, cantidad). La sede cuelga del **lote**:

```
producto   Cadena de oro 18k · precio $250.000        ← de la EMPRESA
  lote 01  Chapinero · costo 100.000 · 3 unid          ← de la SEDE
  lote 02  Kennedy   · costo 105.000 · 2 unid          ← de la SEDE
```

El precio sigue siendo uno para toda la empresa, el costo sigue siendo por identificación específica, y el stock pasa a ser sumable por sede sin tocar ninguna regla de costeo. **Ese trabajo ya está hecho y es el que vuelve esto viable.**

### Cómo construirlo: ubicación en el lote + traslado como documento

Los sistemas profesionales **no guardan "el stock de la sede"**: lo derivan de los movimientos (`stock.quant` en Odoo, *material + plant + storage location* en SAP). Este proyecto ya tiene ese principio escrito —*"los saldos se derivan, nunca se guardan"*— y ya construyó el **kardex**, que une las tres tablas de líneas. Agregarle la dimensión de ubicación es la extensión natural, no un diseño nuevo.

La forma concreta, respetando lo que ya existe:

| Pieza | Qué es | Molde que ya existe |
|---|---|---|
| `inventory_item.branch_id` | **Dónde está el lote ahora.** La consulta rápida, la que responde *"¿dónde está esta cadena?"* | — |
| **`branch_transfer`** | **El historial.** Documento numerado, inmutable, idempotente, con fecha propia | `account_transfer` (`00032`), calcado |

**El costo viaja y no toca la utilidad.** Un traslado no es venta ni compra: es la misma mercancía en otra vitrina — idéntico al principio que ya rige la plata (*"un traslado no es ingreso ni egreso"*) y al que rige la transformación (*"el costo viaja"*).

Sin ese documento, mover un anillo solo se puede expresar como un egreso en un lado y un ingreso en el otro: **inventando un costo y rompiendo la trazabilidad** que hoy llega hasta el contrato del cliente que dejó la prenda.

Y tiene un beneficio contable que conviene nombrar: como el traslado va **al costo y sin impacto en resultados**, la **eliminación** en el consolidado es trivial (§10, `reports`). Es el argumento técnico para no inventar precios internos entre sedes.

## 10. Módulo por módulo

### `cashbox` — lo más avanzado, y ya diagnosticado

| Dónde | Qué hace hoy | Por qué rompe con dos cajas |
|---|---|---|
| `get_active_register` | `order by created_at limit 1` | Elige una en silencio (ver Acción B) |
| `_expected_cash` | Suma **todas** las cuentas `cash` de la empresa | El arqueo mezcla dos cajones |
| `_assert_single_operational_drawer` | Una cuenta `cash` activa **por empresa** | Impide que la segunda sede tenga cajón |

Los tres pasan de *por empresa* a *por registradora*, vía `account.register_id`. El propio docstring de la guarda ya lo dice.

### `contracts` — la prenda está en una bóveda física

- **¿En qué sede quedó la prenda?** Hoy no se puede saber, y el cliente que vuelve puede ir a cualquier local.
- **El desembolso sale de un cajón concreto.**
- **El remate crea inventario**, que nace en alguna sede (§9).
- **El paz y salvo y la devolución** ocurren donde está la prenda.

La ventana de mora, la prórroga y el snapshot legal **no se ven afectados**: son del contrato, no de la sede.

### `sales` — dónde se vendió

Sin sede no hay *"ventas por sucursal"*, que es la primera pregunta de un dueño con dos locales. Y `credit_note` abre una pregunta propia: **una nota emitida en Kennedy, ¿se redime en Chapinero?** (recomendación: sí — es deuda de la empresa con el cliente).

### `identity` — la gente trabaja en un lugar

¿Un usuario pertenece a una sede o a varias? ¿Los roles se multiplican por sede? **Recomendación: la sede es del usuario (`app_user.branch_id`, nullable = todas), no del rol** — así la matriz de 38 permisos no crece.

### `reports` — tres vistas, no una

Los diez endpoints agregan por empresa. Ninguno rompe, pero **todos responden la pregunta equivocada**. Lo que hace un sistema serio son tres vistas:

1. **Por sede** — el estado de resultados de Chapinero.
2. **Consolidado** — la empresa entera, detrás de `reports.view_all_branches` (§8.3).
3. **Eliminaciones** — los traslados entre sedes no pueden contarse dos veces. Trivial si el traslado va al costo y sin impacto en resultados (§9).

En el front, el filtro de `/reportes` pasa de una dimensión (Todo/Empeño/Tienda) a dos.

`payables` es la excepción deliberada: **la deuda con un proveedor es de la empresa**, aunque la mercancía haya entrado por un local. Conviene escribir por qué, para que nadie lo "complete" por simetría.

### `audit` — sin sede no se responde *"¿qué pasó ayer en Kennedy?"*

### `catalogs`, `customers`, `company`, `platform` — no se tocan

Catálogo compartido. Un cliente no es "de una sede". Es una decisión, no un olvido.

## 11. El reparto de tablas

Dos tablas **nuevas**: `branch` (la sede) y `branch_transfer` (el traslado de mercancía, §9). Y de las **37 que ya existen**:

| Grupo | Cuántas | Cuáles |
|---|---|---|
| **Llevan `branch_id`** | ~14 | `cash_register`, `cash_session`, `cash_movement`, `account`, `account_transfer`, `inventory_item`, `inventory_entry`, `inventory_exit`, `inventory_transformation`, `sale`, `sale_return`, `contract`, `expense`, `app_user`, `audit_log` |
| **Heredan del documento padre** | 7 | `contract_item`, `contract_payment`, `sale_line`, `inventory_entry_line`, `inventory_exit_line`, `sale_return_line`, `credit_note_redemption`. **No llevan columna propia** — sería una segunda fuente de verdad |
| **Catálogo de empresa** | ~9 | `customer`, `category`, `supplier`, `product`, `expense_category`, `document_template`, `role`, `role_permission`, `credit_note` |
| **Plataforma / global** | ~6 | `company`, `plan`, `subscription`, `subscription_event`, `permission`, `code_counter` |

## 12. Numeración: series por sede, no contadores nuevos

Los sistemas serios usan **series de documento** por unidad organizativa (SAP las llama *number ranges*), no una llave de contador distinta. En Colombia la numeración por establecimiento es además lo habitual en documentos legales.

Traducido acá: **`CHP-000045`, no un segundo "#45"**.

- `next_counter(p_company, p_prefix)` **no se toca**: sigue numerando por (empresa, prefijo), así que el número es único en la empresa. La sede va como **prefijo visible**, impreso en el papel.
- Dos contratos "#45" en la misma empresa, distinguibles solo por algo que no está impreso, es un problema esperando. Un número de contrato es una **referencia legal**.
- El **código de inventario** (`JOC0002-01U`) **no se toca**: ya usa todas sus posiciones y la última es la letra de **origen** (proveedor / `R` / `T` / `P` / `D`). No hay lugar para la sede sin romper etiquetas ya impresas y pegadas a la mercancía. La sede del lote vive en su columna y en el traslado (§9), no en el código.

## 13. Las pruebas

Hoy: **371 tests backend**, 34 archivos, en `unit/`, `integration/` y `rls/`.

| Qué | Impacto |
|---|---|
| `tests/conftest.py` | Las fixtures crearían una sede, y una segunda para lo que importa |
| `tests/rls/test_tenant_isolation.py` | **Sin cambios** con la decisión de §8.4 (alcance en el servicio, no en RLS). Solo se duplicaría si algún día se endurece a RLS |
| `integration/` (caja, contratos, ventas, inventario) | Los que asumen *una* caja necesitan sede explícita. No es reescribirlos |
| `test_endpoint_guards.py` | Sin cambios |
| `test_error_catalog.py` | Crece con los códigos nuevos (§14) |
| **Tests nuevos que valen la pena** | Que una venta **no consuma stock de otra sede**; que el arqueo de una sede no incluya movimientos de la otra; que el traslado de mercancía conserve el costo; y que un usuario **sin alcance a una sede no la lea por ningún endpoint** — el equivalente por sede del barrido de permisos que ya existe |

La regla del proyecto aplica igual: **cada test nuevo hay que verlo fallar sin el fix.**

## 14. Códigos de error previsibles

Van al catálogo de `API_GUIDE.md` §15 el día que existan, y `test_error_catalog.py` los va a exigir documentados en las dos direcciones:

| Código | Cuándo |
|---|---|
| `MULTIPLE_REGISTERS_NOT_SUPPORTED` | Acción B — hay más de una registradora activa y todavía no hay multi-caja |
| `BRANCH_REQUIRED` | Operación de dinero o stock sin sede resoluble |
| `ITEM_NOT_IN_BRANCH` | Vender o egresar un lote que está en otra sede |
| `BRANCH_MISMATCH` | El cajón elegido no pertenece a la sede de la operación |
| `BRANCH_HAS_ACTIVITY` | Desactivar una sede con stock, cartera o caja abierta |

## 15. El frontend

- **Selector de sede en el shell**, y **ojo dónde**: `PageHeader` y la topbar son donde reventó el desborde a 360 px (F6-03, `/caja` se salía 59 px). Un control más ahí se mide antes de darlo por hecho.
- **`GET /me` devuelve la sede**, mismo bootstrap, un campo más.
- **Toda lista y todo reporte** ganan el filtro: 14 features.
- **`lib/dates.ts`** usa la zona de la **empresa**. Colombia es una sola zona, así que hoy da igual — pero la zona es de la **sede**. Anotado, no urgente.
- **Distinguir "mi sede" de "todas"** en los KPIs: mezclarlos sin decirlo es el error que ya se cometió dos veces con ingresos y capital.

## 16. Orden de construcción

Siete pasos, y del 2 al 6 **cada uno entrega valor solo** — no hay que terminar todo para que sirva algo:

| # | Qué | ¿Entrega valor solo? |
|---|---|---|
| 1 | `branch` + `branch_id` nullable + backfill a "Sede principal" | No, pero es la base |
| 2 | Caja y cuentas por sede (usa `register_id`, que ya existe) | **Sí** — arqueo por sede |
| 3 | Inventario por sede + `branch_transfer` (§9) | **Sí** — es el grueso |
| 4 | Contratos y ventas con sede estampada (§8.2) | **Sí** — ventas por sucursal |
| 5 | Reportes: por sede, consolidado y eliminaciones (§10) | **Sí** |
| 6 | Alcance por usuario + `reports.view_all_branches` (§8.3) | **Sí** |
| 7 | Contraer a `NOT NULL` | Cierre |

**El paso 2 es el más barato de todos** porque el modelo ya está: `cash_session` cuelga de `register_id`, el índice de sesión abierta ya es por registradora, y `account.register_id` existe. Si algún día hay que empezar por algo, es por ahí.

### Ruta de despliegue

El patrón que ya usó producto+lote (`00021`→`00023`): **expandir → migrar → contraer**, y las que contraen van **después** del deploy.

1. **`branch` + `branch_id` nullable** en las ~14 tablas. Aditiva.
2. **Backfill:** una "Sede principal" por empresa, todas las filas apuntan ahí. Trivial **mientras la premisa de §3 siga siendo cierta**.
3. **Deploy del backend**, con la sede resuelta por defecto cuando nadie la manda (misma red de seguridad que `resolve_account_for_movement`).
4. **Front**, con `gen:api` contra el backend ya desplegado — nunca antes.
5. **Contraer:** `NOT NULL` donde corresponda.

Recordatorio que ya costó una vez: `supabase db push` aplica **todas** las migraciones pendientes de golpe, así que "aplicar A → deploy → aplicar B" necesita `psql` para el paso A.

## 17. Lo que NO hay que hacer

- **No poner `branch_id` en las tablas de líneas.** Heredan de su documento — dos fuentes de verdad es el bug que `00022`–`00023` cerraron con el precio del lote.
- **No cambiar la llave de `next_counter`** (§12).
- **No meter la sede en el código de inventario.** Los códigos impresos son inmutables.
- **No convertir la sede en parte del rol.** Multiplica la matriz de permisos.
- **No construir esto hasta que exista una segunda sede real.** Mismo criterio con que se pospuso el multi-mostrador: *se separan cajones para que un faltante tenga dueño, no para tener más plata disponible.* La versión de sedes: **se separan sedes cuando hay dos locales, no para tener un reporte más.**

## 18. Preguntas de negocio

### Respondidas (10/09/2026)

| Pregunta | Respuesta |
|---|---|
| ¿Entidades legales separadas o una sola? | **Una sola, mismo NIT.** La sede es una dimensión (§8.1) |
| ¿La sede aísla o solo agrupa? | **Restringe por defecto**, pero el alcance es del **usuario** y se hace cumplir en el servicio, no en RLS — ampliable después sin tocar tablas (§8.3, §8.4) |
| ¿Cuándo se construye? | **Sin fecha.** Es previsión; hoy solo las tres acciones de §5 |

### Todavía abiertas

1. **¿El cliente y su nota crédito son de la empresa o de la sede?** Recomendación: **de la empresa, los dos** — una nota emitida en Kennedy se redime en Chapinero, porque es deuda de la empresa con el cliente.
2. **¿Se puede prestar en una sede y pagar en otra?** Si sí —y para un cliente es lo esperable—, el abono entra en un cajón distinto del que desembolsó. Eso es **correcto**: la cartera es de la empresa. Pero hay que decirlo antes de que alguien lo lea como un descuadre.
3. **¿La prenda se devuelve solo donde está?** Hoy no hay dónde registrar en qué bóveda quedó. Con `branch_id` en el contrato se sabe — falta decidir si el sistema **obliga** a trasladarla antes de entregarla en otra sede, o solo lo advierte.
4. **¿Un gasto puede ser "de la empresa" y no de una sede?** El arriendo es de Chapinero; la contabilidad o el software son de la empresa. Recomendación: permitir `branch_id` nulo en `expense` con el significado explícito de *"gasto general"*, y que el consolidado lo reparta o lo muestre aparte — nunca que se lo coma una sede.

## 19. Definición de Hecho (cuando se implemente)

- **Un solo punto de verdad para el alcance** (§8.4), y ningún listado resolviéndolo por su cuenta.
- La sede **estampada** en cada documento, nunca derivada de por dónde pasó la plata (§8.2).
- Cada endpoint que mueve stock o plata resuelve la sede, y rechaza con código propio cuando no puede.
- **Traslado de mercancía entre sedes** como documento inmutable con el costo viajando — mismo molde que `account_transfer` y que la transformación.
- Reportes con dimensión de sede, y los que deliberadamente **no** la tienen (`payables`) documentados con su porqué.
- `API_GUIDE.md` §15 con los códigos nuevos y `test_error_catalog.py` en verde en las dos direcciones.
