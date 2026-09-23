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
| **7** · Regresión | Convertir lo encontrado en suite automatizada | ✅ 08/09/2026 |
| **8** · Documentos y archivos | Storage y fotos, impresión, plantillas de documentos | ✅ 08/09/2026 |
| **9** · Los caminos de entrada | Alta de usuario, contraseñas y panel de plataforma, en navegador | ✅ 09/09/2026 |
| **10** · Concurrencia y volumen | Dos sesiones sobre el mismo stock y la misma caja; paginación y topes | ✅ 09/09/2026 |

**Principios de método** (los mismos del proyecto, aplicados a probar):

- **Toda aserción de error va contra el `code`, nunca contra el status solo.** Un test que mira el status y no el código no cubre nada — le costó once días de trabajo a un cliente.
- **Cada permiso se prueba dos veces:** en la pantalla (¿oculta?) y en la API pelada con el JWT de ese rol (¿403?). La UI oculta, no protege.
- **Un test que pasa no prueba nada hasta que se ve fallar sin el fix.** Todo test nuevo de esta auditoría se ejecutó con el arreglo revertido, para confirmar que falla con el error exacto.












---

## Cierre: los hallazgos aplicados (09/09/2026)

Tras las diez fases, se tomó la lista de hallazgos abiertos y se aplicó lo que era **código**, dejando fuera solo lo que necesita una decisión de negocio o de diseño. Cada fix con su test, y **cada test visto fallar sin él**.

### Backend

| Hallazgo | Qué se hizo |
|---|---|
| **F5-01** · El descuento de interés no bajaba el ingreso | Se resta, igual que el de una venta. Estaban en dos líneas contiguas: `ventas = gross_revenue - discounts` frente a `intereses = interest_collected`. Corregido también en `/reports/series`, que usaba la misma definición |
| **F10-01** · Los conflictos de concurrencia devolvían 500 | Un handler traduce lo que la BASE detecta a errores de negocio: la violación del `UNIQUE(idempotency_key)` estrena código propio, **`IDEMPOTENCY_IN_PROGRESS`** (el reintento llegó mientras la original seguía en vuelo — justo el caso para el que existe la clave), y el `CHECK (quantity >= 0)` pasa a ser el `400` de stock. Solo se traduce lo que sabemos nombrar; el resto sigue subiendo como 500 |
| **F2-01** · «No hay plata» cuando lo que falta es la caja | Reordenado: la sesión se comprueba antes que el saldo. Sin sesión, una cuenta `cash` reporta `0.00`, así que al revés ganaba el error equivocado |
| **F8-01** · Se podía activar una plantilla vacía | Guardarla sigue siendo legítimo (un borrador a medias); activarla da **`TEMPLATE_IS_EMPTY`** |
| **F8-02** · Activar era irreversible | `POST /company/document-templates/{id}/deactivate` — hay camino de vuelta al documento de fábrica |
| **F7-01** · `CREDIT_NOTE_INSUFFICIENT_BALANCE` documentado y no emitido | Corregido durante la Fase 7 |

> El test de auditoría del propio proyecto cazó que la acción nueva no seguía la convención de nombres ni estaba registrada — otra vez hizo su trabajo.

### Frontend

| Hallazgo | Qué se hizo |
|---|---|
| **F6-02** · 12 combinaciones bajo WCAG AA | Los seis tokens semánticos pasan a valores calculados contra los **tres** fondos donde viven (`--bg-app`, `--bg-surface` y su propio `-soft`, el más exigente por compartir tono), conservando el matiz. **El teal de marca no se tocó** |
| **F6-03** · `/caja` desbordaba 59px a 360px | `flex-wrap` + `min-w-0` en el `PageHeader` **y en los tres contenedores reales**: los botones de `/caja` no viven en el header sino en una card propia, `/contratos` tenía otro `flex` anidado dentro de sus acciones, y en `/cuentas` era la fila de cada cuenta. Verificado a 360px: las 12 pantallas sin desborde |
| **F9-01** · El turno de ayer no se distinguía | La franja se pone ámbar y dice la fecha y qué hacer. El dato (`session_date`) ya viajaba en la respuesta |
| **F6-01** · El error más arriba quedaba fuera de vista | `EntryFormPage` usa `revealFirstError`, el helper que ya existía |
| **F8-03 · F9-03** · Etiquetas en inglés | `completed`/`voided` en Ventas y `sale_return` en el acta. `CONCEPT_LABELS` cubre ahora los 13 valores del enum |

**Los dos tests de contraste marcados con `it.fails` dejaron de estarlo.** Al corregir los tokens empezaron a fallar por *«pasó cuando se esperaba que fallara»* — que es exactamente para lo que servía la marca, y por lo que se eligió sobre un `skip`.

> **Nota de método, y es la más útil de esta tanda.** El primer fix de F6-03 fue al `PageHeader` porque parecía el sospechoso obvio. Al **volver a medir** tras desplegarlo, `/caja` seguía saliéndose los mismos 59px: sus botones no estaban ahí. El fix del componente compartido es correcto y previene el caso general, pero no era donde estaba el problema medido. Sin esa segunda medición, esto se habría reportado como arreglado sin estarlo — que es exactamente el tipo de cosa que esta auditoría existe para no hacer.

### Configuración

**F9-02** · `FRONTEND_URL` pasa a la URL que usa el cliente. Los enlaces de invitación y recuperación llevaban el nombre interno del proyecto y del dueño (`…-git-dev-mateos-projects-85710491…`) — un enlace así, pidiendo crear una contraseña, se lee como phishing. La razón documentada para mantenerlo en preview había caducado: se comprobó pidiéndole a `generate_link` la URL de producción y hoy la respeta.

### La verificación, que es la mitad que importa

Ningún fix se dio por bueno con el commit. Todos se volvieron a medir **contra el entorno desplegado**, con los mismos scripts que los encontraron:

| Qué se midió | Antes | Después |
|---|---|---|
| Cinco ventas simultáneas de la última unidad | `[500, 500, 201, 500, 500]` | `[400, 400, 201, 400, 400]` — los cuatro que pierden reciben el error de stock |
| Cinco requests con la misma clave de idempotencia | `[500, 500, 500, 201, 500]` | `201` + cuatro `IDEMPOTENCY_IN_PROGRESS` |
| Ingreso por intereses con un descuento de 10.000 | 300.000 | 290.000, y `/reports/series` con el mismo número |
| Activar una plantilla vacía | activaba | `TEMPLATE_IS_EMPTY` |
| Volver al documento de fábrica | no había camino | `deactivate` y vuelve |
| `FRONTEND_URL` en los enlaces de invitación | el nombre interno del proyecto | `la-legal-front-end.vercel.app` |
| Contraste WCAG AA | 12 combinaciones por debajo | 3, todas del teal de marca que se decidió no tocar |
| Desborde horizontal a 360px | `/caja` 59px · `/contratos` 14px · `/cuentas` 15px | las 12 pantallas en cero |

Las dos pantallas que a 360px todavía tienen contenido más ancho que el viewport —la tabla de desglose de `/reportes` y las pestañas de `/inventario`— lo tienen **dentro de un contenedor con scroll propio**, que es el patrón correcto: el documento no se mueve.

**Suites: 337 tests en el backend, 165 en el front, todo en verde.**

### Lo que se dejó a propósito

| | Por qué |
|---|---|
| **H-04** · Descuento sobre intereses sin pantalla | Decisión de negocio — `DECISIONES_PENDIENTES.md` §1 |
| **F3-01** · Prestar sin efectivo en el cajón | Decisión de negocio — `DECISIONES_PENDIENTES.md` §3 |
| **F2-02** · Gasto por transferencia con la caja cerrada | Decisión de negocio: cambiarlo pide hacer `expense.session_id` opcional y definir a qué corte pertenece un gasto sin sesión |
| **El teal de marca** | El botón primario relleno (blanco sobre `--brand-500`) está en 2.70 y también incumple, pero oscurecerlo cambia la identidad visual |
| **F10-02** · `fetchAllPages` corta en silencio | El tope es correcto; falta devolver que truncó y que la UI lo diga. Toca las cuatro exportaciones, mejor como su propia tanda |
| **H-05** · El inicio vacío del Asesor | Oportunidad de producto, no defecto |
| **F2-03** · Idempotencia con otro cuerpo | Menor: devuelve el original, que es el comportamiento seguro |

---

## Hallazgos sueltos — 21/09/2026 (al escribir la guía de usuario)

Salieron al verificar, **contra el código**, las secciones de Caja y Ventas recién escritas para la guía.
Los tres primeros son defectos del front que un usuario sí sufre.

| # | Hallazgo | Dónde | Gravedad |
|---|---|---|---|
| F21-01 | **El buscador de artículos de la venta dice «(Enter agrega)» y es falso.** No hay handler de teclas, y el input vive dentro del `<form onSubmit>`: presionar Enter **intenta registrar la venta**, no agregar el artículo. El texto de ayuda induce justo la acción peligrosa | `SaleFormPage.tsx:151` (placeholder) · `ItemPicker.tsx:36-60` · `SearchInput.tsx:39-47` | **Alta** — el mensaje empuja a disparar una venta a medio armar |
| F21-02 | **Anular una venta exige caja abierta y el aviso no lo dice.** El backend lanza `CASH_SESSION_NOT_OPEN` antes de tocar nada, sin importar el medio de pago; el front no mapea ese código y muestra *«No se pudo anular la venta. Intenta de nuevo.»* | `sales/service.py:384-386` vs `SaleReceiptDialog.tsx:73-75` | **Media** — el usuario queda sin saber qué hacer |
| F21-03 | **Abrir y cerrar caja tapan el mensaje del backend con un genérico.** `CASH_SESSION_ALREADY_OPEN` y `CASH_SESSION_ALREADY_CLOSED_TODAY` traen texto útil, pero el diálogo pinta *«No se pudo abrir la caja. Intenta de nuevo.»* | `OpenSessionDialog.tsx:135-139` · `cashbox/api.ts:52-76` (sin `onError`) | **Media** — relacionado con F20-01 |
| F21-04 | **La cantidad de una línea de venta con fracciones es un input no controlado.** Se puede escribir 50 y verlo en pantalla aunque el valor quede acotado a 3. El total de arriba sí muestra lo correcto, pero la línea miente | `SaleFormPage.tsx:179` (`defaultValue`) | Baja |
| F21-05 | **`deactivate_document_template` existe en el catálogo de auditoría pero ningún botón de la UI lo dispara** | `audit/labels.ts:67` vs `DocumentTemplatesPage.tsx` | Baja — verificar si quedó solo en el backend |

| F21-06 | **El nombre del proveedor se le muestra al usuario.** `INVITE_RATE_LIMITED` responde *«Supabase limitó el envío de correos»*, y el front no lo traduce: `errors.ts` solo cataloga el código, no hay handler, y el diálogo pinta el `message` crudo. Un admin de una compraventa no tiene por qué saber qué es Supabase | `identity/auth_admin.py:212-214` · sin handler en `InviteUserDialog.tsx:64-66` | Baja — cosmético, pero filtra un detalle de infraestructura |
| F21-07 | **El aviso de caja cerrada del traslado es el único distinto.** Las otras diez operaciones abren `CashSessionRequiredDialog`, con botón «Abrir caja». El traslado pinta un texto rojo dentro del diálogo y **sin botón**, así que quien conoce el recuadro lo busca y no aparece | `TransferDialog.tsx:130-137` vs. las otras diez | Baja — inconsistencia de UX |

| F21-08 | **La auditoría muestra los movimientos de capital sin traducir.** `capital/service.py:193` escribe `action=direction` (`contribution`/`withdrawal`), y esos códigos no están en `AUDIT_ACTION_LABELS`. Además `accounts` y `capital` faltan en `BUSINESS_MODULE_LABELS`, así que la matriz de permisos y la auditoría los muestran en inglés. Un aporte del dueño se lee literalmente `contribution · capital` | `audit/labels.ts:17-78` · `lib/businessModules.ts:16-29` · `capital/service.py:193-199` | Baja — dos líneas de arreglo, pero se ve en dos pantallas |
| F21-09 | **`contracts.override_ltv` se reparte automáticamente a todo rol con `contracts.create`**, incluido el Asesor. Es un permiso `is_special` que autoriza prestar por encima del tope de la categoría; si lo tiene todo el mostrador, el LTV deja de ser un límite | `00051_contract_extend_loan.sql:113-119` · `platform/service.py:27-43` | **Media** — decisión de producto, no defecto técnico |

### ✅ F21-10 — El job nocturno resucitaba contratos reemplazados (21/09/2026 · causa, datos y diseño cerrados)

**El más grave de toda esta tanda, y el único que dañó datos de verdad.** Causa arreglada, **4 contratos
reparados y verificados**, hallazgo de diseño cerrado con test, y guardián puesto. Queda abierto un solo
punto, al final: la Machine del job sigue sin process group.

`fly.dev.toml` y `docs/ARCHITECTURE.md:221-237` ya advertían que la Machine programada del job nocturno
**no se actualiza con `fly deploy`**: queda clavada a la imagen con la que se creó. La de
`compraventa-backend-dev` se creó el **08/09/2026**.

El **10/09** entró el commit `87ce644` (ampliar el préstamo) con este cambio en
`app/modules/contracts/rules.py:18`:

```diff
- _TERMINAL_STATUSES = {"paid", "auctioned"}
+ _TERMINAL_STATUSES = {"paid", "auctioned", "superseded"}
```

`superseded` es el estado del contrato viejo cuando se amplía un préstamo. Y la consulta que alimenta el
job **no lo excluye**:

```sql
-- repository.list_active_contracts_for_recompute
where status not in ('paid', 'auctioned')
```

O sea: el job **sí toma** los contratos `superseded`, y lo único que impedía recalcularlos era la guarda de
`compute_status` — que es exactamente lo que la imagen del 08/09 no tenía.

**Consecuencia:** desde el 10/09, cada noche el job tomó los contratos reemplazados por una ampliación y los
recalculó a `active` / `in_arrears` / `in_extension`, **como si siguieran vivos**. Eso infla la cartera y
puede hacer que un contrato ya sustituido aparezca en «Listos para remate».

**Arreglado el 21/09:** la Machine se actualizó a la imagen desplegada ese día
(`fly machine update 805747f63d17d8 --image …`), verificando que el `schedule: daily` sobreviviera — si se
pierde, el job deja de correr y **su ausencia es silenciosa**.

**✅ MEDIDO Y REPARADO el 21/09/2026. Hubo daño: 4 contratos, el 100 % de las ampliaciones que existen.**

**El borrador de esta consulta tenía la columna equivocada.** `superseded_contract_id` **no existe**. La que
enlaza sucesor → padre es **`parent_contract_id`** (`supabase/migrations/00051_contract_extend_loan.sql:74`);
`root_contract_id` es la raíz de la cadena y **no sirve** para este conteo — en un sucesor apunta al abuelo.
La consulta buena, de solo lectura:

```sql
-- contratos que tienen un sucesor (fueron ampliados) pero NO están en superseded
select c.company_id, count(*)
from public.contract c
where exists (select 1 from public.contract s where s.parent_contract_id = c.id)
  and c.status <> 'superseded'
group by c.company_id;
```

| Empresa | Nº | status hallado | `extension_ends_at` | capital |
|---|---|---|---|---|
| Empresa Demo Front | 1 | `in_extension` | **2026-10-16** | 1.000.000 |
| Empresa Demo Front | 20 | `active` | — | 2.000.000 |
| **LA GRAN LEGAL** | 28 | `active` | — | 1.000.000 |
| ZZ QA — auditoría 08/09 | 9 | `active` | — | 1.000.000 |

**El dato que cierra el caso:** había **cero** contratos `superseded` en toda la base y **4** ampliaciones en
total. No fue daño parcial — **no hubo ni una ampliación sana**. La función nació el 10/09 y el bug nació el
mismo día, así que la hipótesis optimista de este hallazgo ("si da cero, nadie la usó") quedó descartada por
el lado contrario. De los cuatro, **uno solo es de un cliente real**: el Nº 28 de LA GRAN LEGAL.

**La bomba con fecha que tenía, y que era lo que apuraba.** El Nº 1 quedó `in_extension` con prórroga hasta
el **16/10**: a partir del **17/10 entraba solo a «Listos para remate»** sin que nadie tocara nada — un
contrato ya sustituido, con sus prendas en `transferred`, ofrecido para rematar.

**Cartera inflada: 5.000.000 COP**, y contada **doble**, porque el sucesor también estaba vivo (20,5 % de la
cartera de Empresa Demo Front; 4,7 % de la de LA GRAN LEGAL).

**Lo que el daño NO alcanzó**, verificado: el job escribe solo `status` y `extension_ends_at`
(`repository.update_contract_status`), no capital ni fechas ni ancla de interés; **no hubo un solo abono
registrado sobre ninguno de los cuatro padres** después del recargo, así que nunca se propagó a plata; las
prendas ya estaban en `contract_item.status='transferred'` y la foto firmada del Nº 1 quedó intacta.

**La reparación:** `scripts/qa/reparar_f21_10.sql` — acotada a los 4 ids (el predicado es el que hay que
**vigilar**, no el que se ejecuta a ciegas sobre datos reales), en una transacción, poniendo `status =
'superseded'` y `extension_ends_at = null`. El `null` no era opcional: dejarlo mantenía la bomba del 17/10
aunque el status ya dijera `superseded`, y dejaba una fila contradiciendo la invariante de que un estado
terminal no tiene prórroga viva. Va con **4 filas de `audit_log`** (`action='correct_contract_status'`,
`user_id` NULL a propósito: no lo hizo un usuario de la empresa), porque ningún servicio las iba a generar y
la regla 6 de `CLAUDE.md` exige auditar toda acción sensible; su etiqueta se agregó a
`frontend-starter/src/features/audit/labels.ts` o la pantalla la mostraría en crudo.

**Verificado después de aplicarla:** los 4 en `superseded`, las tres invariantes en cero (contrato con
sucesor fuera de `superseded`; terminal con prórroga viva; en cola de remate con sucesor) y la cartera de las
tres empresas bajando exactamente a los valores reales (11.637.222 / 20.250.000 / 12.450.000).
**La base local no necesitó reparación** — verificado, no supuesto: sus 9 contratos con sucesor están todos
en `superseded`, porque ahí no corre ningún job y los datos los crea el código actual, ya con la guarda.

**⚠️ Corrección al relato de este hallazgo: el job nocturno NO era el único vector.** `get_contract`
(`service.py:474-499`) también recalcula y **persiste** el status en cada lectura de detalle, así que durante
esos once días un simple `GET /contracts/{id}` bastaba para resucitar un contrato reemplazado, sin esperar a
la medianoche — y la app servida venía sin la guarda hasta el deploy del 21/09. **No se puede saber cuál de
los dos vectores causó cada fila:** el job no escribe en `audit_log` (`app/jobs/nightly.py`), así que no dejó
rastro forense. Los dos están cerrados hoy por la guarda de `compute_status`.

**El guardián:** `scripts/qa/verificar_cadenas.py`. Esto fue invisible once días porque **nada avisaba**;
es la misma forma de `verificar_sedes.py` — una invariante sobre datos reales que un test de CI contra base
efímera nunca vería. Vigila tres: sucesor ⇒ `superseded`; `contract_item` en `transferred` ⇒ contrato
`superseded`; terminal ⇒ sin `extension_ends_at`. Sale con **código 1** si alguna se rompe.
Los estados terminales salen de `rules.TERMINAL_STATUSES`, **no de una lista escrita a mano** — que es
exactamente el error que costó los once días. Solo lectura verificada, no asumida (`SET TRANSACTION READ
ONLY` por transacción, porque bajo Supavisor en modo transacción la sesión no es nuestra, más `rollback()`
explícito), y el reporte no imprime datos personales: id, número, empresa y estado, nada más.

**La detección se ejerció de verdad**, que es lo que separa un guardián de un archivo que siempre dice que
sí: como la remota ya estaba reparada, se fabricaron las tres roturas en la base **local** (`QA_DATABASE_URL`
permite apuntarlo a otra base; por defecto va a la dev remota) y el script las cazó las tres con exit 1.
Sembrado limpiado después; hoy sale en verde contra las dos bases.

**Puesto en automático, en parte (21/09/2026).** Y la parte que NO se automatizó es una decisión, no un
olvido:

- ✅ **`scripts/qa/verificar_job_nocturno.py` + `.github/workflows/guardianes.yml`** — un guardián nuevo, que
  vigila lo que era la causa y no el daño: que la Machine `nightly-job` **exista**, que conserve su
  **`schedule`** y que **su imagen coincida con el release actual de la app**. Esa tercera es exactamente lo
  que F21-10 rompió y lo que nadie estaba mirando. Corre todos los días a las 13:00 UTC (8 a.m. Bogotá,
  después de la corrida del job). **Tiene que correr desde AFUERA de Fly:** si la Machine se borra o pierde
  el `schedule`, un vigilante que viviera dentro sería justamente lo que no corre. Sale con **1** si algo
  está roto y con **2** si no pudo verificar — *"no se pudo verificar" no es "está sano"*, y confundirlos
  sería repetir el error que el script existe para evitar. Necesita el secret `FLY_API_TOKEN`; hasta que
  exista falla a propósito con un mensaje que dice qué agregar.
  Las tres rutas de detección se ejercieron el 21/09: Machine inexistente → exit 1, sin `schedule` → exit 1,
  y la comparación de imágenes verificada aparte.
- 🔴 **`verificar_cadenas.py` sigue corriéndose a mano, y NO se puso en GitHub Actions a propósito.**
  Necesitaría `DATABASE_URL` de la dev remota como secret de un tercero, y esa base tiene **datos personales
  reales de clientes** (Ley 1581). Exportar esa credencial para leer tres invariantes amplía el radio de
  exposición mucho más de lo que aporta. Su lugar es dentro del perímetro que ya tiene la base: lo más
  barato es meterlo en `app/jobs/nightly.py`. Las dos opciones, con sus contras, en
  `scripts/qa/README.md`.

**Sobre el process group, que sigue vacío a propósito.** La causa común del borrado del 27/08 y de F21-10 es
que `nightly-job` no tiene process group, así que toda operación de `flyctl` que itere por grupo la saltea
—`fly deploy` y también `fly secrets set`— y a ojo parece basura. **No se le puso uno porque el arreglo
puede causar el problema:** ponerle `fly_process_group=nightly` sin declararlo en `fly.dev.toml` puede hacer
que el próximo `fly deploy` la trate como huérfana de un grupo inexistente y la borre; y declararlo en el
toml hace que `fly deploy` la gestione y pueda recrearla **sin** el `schedule`. Así que se vigila en vez de
tocarse, y el guardián imprime el aviso para que nadie lo tome por un descuido.

**Cuatro invariantes más, propuestas y no implementadas** (hoy las cuatro dan cero, medido):
(1) la inversa — un `superseded` **sin** sucesor, que sería plata prestada desaparecida del sistema si el
recargo fallara a mitad; es la más preocupante. (2) Un `superseded` con prendas que **no** estén
`transferred`: una prenda en `in_custody` bajo un contrato reemplazado no la reclama nadie. (3) **Bifurcación
de cadena** — dos hijos con el mismo `parent_contract_id`, o sea dos deudas vivas sobre la misma prenda con
el cupo LTV calculado una sola vez. (4) Coherencia de `root_contract_id` (que sea
`coalesce(padre.root_contract_id, padre.id)`, nunca NULL en un sucesor, y que la cadena no cruce
`company_id`): un `root` mal puesto mueve la ventana de 28 días, que es lo que `00051` más protege.

**Y un riesgo estructural que sigue abierto:** la Machine `nightly-job` **no tiene process group** (campo
vacío en `fly machine list`). Esa es exactamente la característica por la que el 27/08 alguien la borró
creyéndola "máquina huérfana" — el borrado que dejó las suscripciones sin expirar nunca. El job nocturno es
hoy indistinguible de basura a simple vista, y ya lo borraron una vez por eso.

**El hallazgo de diseño — ✅ RESUELTO el 21/09/2026.** La consulta filtraba por lista negra
(`not in ('paid','auctioned')`) en vez de por `_TERMINAL_STATUSES`: **cualquier estado terminal nuevo iba a
repetir este bug exacto.** Ahora la consulta y la constante son la misma fuente:

- `rules._TERMINAL_STATUSES` pasó a ser **pública** — `rules.TERMINAL_STATUSES` (`frozenset`) — porque dejó
  de ser un detalle interno de `compute_status`: es el criterio que comparten la guarda y la consulta.
- `repository.list_active_contracts_for_recompute` la usa como parámetro expandido
  (`where status not in :terminal_statuses` + `bindparam(..., expanding=True)`, el mismo patrón que
  `identity.set_role_permissions` e `inventory.list_items`), leyéndola **en cada llamada** — no una copia al
  importar, para que monkeypatchearla en un test y agregarle un estado sean lo mismo.
- Agregar un estado terminal nuevo a la constante ahora **alcanza**: no hay un segundo lugar que tocar.

**El test de regresión:** `tests/unit/test_contract_recompute_query.py`. Corre la consulta contra una sesión
espía (sin Postgres, así no se salta donde no hay Docker) y saca del SQL el conjunto que el `not in` deja
afuera. No repite la lista de estados — la deriva de la constante; repetirla reintroduciría el mismo
acoplamiento. El test central **inventa un cuarto estado terminal** vía `monkeypatch` y exige que la consulta
lo excluya sin que nadie haya tocado el SQL.

Verificado a la inversa, que es lo que lo vuelve un test:

| Versión de la consulta | Resultado |
|---|---|
| La vieja, `not in ('paid','auctioned')` | **3 failed** — `assert {'auctioned','paid'} == {'auctioned','paid','superseded'}` |
| Lista a mano pero hoy completa, `('paid','auctioned','superseded')` | **2 failed** — el estado inventado se cuela igual |
| La arreglada, derivada de la constante | 3 passed |

El caso del medio es el que importa: una lista escrita a mano **aunque hoy esté completa** sigue fallando,
porque lo que se prueba es el invariante ("agregar un estado terminal basta"), no los tres valores de hoy.

Suite completa con Docker arriba: **425 passed** (422 + los 3 nuevos), `ruff check` / `ruff format --check`
limpios y `mypy app` sin hallazgos.

**Lo que NO se tocó, a propósito** (mismo patrón, otra decisión de negocio — no es el filtro del job):
`service.py:643` rechaza abonos con `status in ("paid", "auctioned")` —  sin `superseded`, así que un
contrato ya reemplazado todavía admitiría un abono— y `service.py:1004` repite los tres a mano para el
cupo de ampliación. Ninguno de los dos es "los terminales" en el sentido de la constante (uno es "cerrado
para abonos"), así que colapsarlos contra `TERMINAL_STATUSES` cambia comportamiento y pide su propia tanda.

---

### ✅ F21-11 — Un contrato ya reemplazado por una ampliación admitía un abono (21/09/2026 · cerrado)

**Es "su propia tanda": la que el último párrafo de F21-10 dejó anotada y sin hacer.** Nace de ahí, pero es
un defecto distinto y con daño propio, así que va como hallazgo aparte (§F21-10 queda como está).

`service.py:643` filtraba los abonos con una lista escrita a mano:

```python
if m["status"] in ("paid", "auctioned"):   # le falta "superseded"
```

Al ampliar un préstamo el contrato viejo pasa a `superseded` y nace un sucesor que carga la deuda real
(capital viejo + recargo). Con ese filtro, **el contrato viejo seguía admitiendo abonos**: la plata entraba a
la caja con su recibo, el sucesor seguía debiendo todo, y quedaba registrado un abono que **no bajaba ninguna
deuda viva**. Medido, no supuesto — con el código viejo el test de integración nuevo recibe `201`, recibo
Nº 1, `new_capital_balance: 900000.00` **sobre el contrato `superseded`**.

Es la forma exacta de F21-10 (una lista negra que se desincroniza de `rules.TERMINAL_STATUSES`) en otro
punto del mismo módulo. La diferencia es que acá no hizo falta un job: bastaba con que alguien abonara sobre
el número de contrato del papel que el cliente trae en la mano — que es el papel viejo.

**La decisión de diseño: se reusó `rules.TERMINAL_STATUSES`, no se abrió una constante paralela.** Los dos
conceptos no son idénticos ("de acá no se sale" vs. "cerrado para abonos") y hoy coinciden en los tres
estados, así que la pregunta fue cuál de las dos opciones **falla mejor** el día que aparezca un estado
terminal que sí admita abonos (el candidato plausible: una cartera castigada que todavía recibe
recuperaciones):

- Con **dos constantes de valor idéntico**, un estado terminal nuevo nace **abierto** para abonos. Se acepta
  plata contra un documento que no debe moverse y **nadie se entera** — el defecto que se está arreglando.
- Derivándola de `TERMINAL_STATUSES`, nace **cerrado**. El rechazo se ve el primer día, lo reporta quien
  atiende, y ahí se parte la constante con el caso real en la mano.

**Cerrado de más se nota; abierto de más no.** Y dos constantes con los mismos tres valores no divergen por
decisión, divergen por omisión: ningún test puede distinguirlas.

**`service.py:1004`** (el cupo de ampliación, `quote_extension`) repetía los tres estados a mano. **No era un
defecto** —la lista estaba completa— pero era el tercer lugar con la lista escrita, así que entró en el mismo
arreglo y por la misma razón. Su `blocked_reason` sigue siendo `CONTRACT_CLOSED` también para `superseded`:
acá no hay un sucesor "sobre el que ampliar" (ampliar el sucesor es su propia decisión, con su cupo y su
ventana), y `ExtendLoanPanel.tsx:62` ya oculta la tarjeta con ese motivo. Cambiarlo habría movido el `enum`
de `blocked_reason` en el OpenAPI y el comportamiento de esa pantalla, sin ganar nada.

**Código de error nuevo: `CONTRACT_SUPERSEDED` (409).** No se reusó `CONTRACT_CLOSED` (400), y la razón es
la regla del proyecto —*«un error tiene que nombrar la acción que falta, no solo negar la que se intentó»*—:

- `CONTRACT_CLOSED` dice *«el contrato ya está cerrado; no admite abonos»*. Sobre un `superseded` eso es
  engañoso: **no hay nada terminado**, la deuda se mudó de documento. Manda a quien atiende a buscar un pago
  que no existe.
- `CONTRACT_SUPERSEDED` dice *«Este contrato fue reemplazado por una ampliación. El abono va sobre el
  contrato Nº 41, que es el que carga la deuda.»* — y trae
  `details: {successor_contract_id, successor_number}` para que la pantalla pueda enlazarlo.

El sucesor se busca por **`parent_contract_id`** (no `root_contract_id`, que en un sucesor apunta al abuelo:
el mismo error que hubo que corregir en la consulta forense de F21-10), con
`repository.find_successor_contract`. Si no hay sucesor —un `superseded` huérfano, que no debería existir y
que `verificar_cadenas.py` vigila— el abono **se rechaza igual y con el mismo código**, pero sin `details`:
no se inventa un número de contrato que nadie va a encontrar.

El código entró a los dos catálogos, que es la mitad que importa: `docs/API_GUIDE.md` §15 y
`frontend-starter/src/lib/api/errors.ts`. Cae al banner genérico del front (el `message` del backend ya trae
el texto accionable), igual que los otros códigos del recargo. **`tests/unit/test_error_catalog.py` lo cazó
sin documentar en la primera corrida de la suite** — el test de regresión funcionando como debe.

**Los tests: 7 nuevos, y los 3 que importan fallan con el código viejo.**

`tests/unit/test_contract_payment_gate.py` (5, sin Postgres — el rechazo pasa antes de tocar la base, con el
repositorio monkeypatcheado, así que corren también donde la integración se salta por falta de Docker):
el rechazo de `superseded` **por código** y con el número del sucesor en el mensaje; el caso sin sucesor;
`paid`/`auctioned` siguen dando `400 CONTRACT_CLOSED` (el contrato con el front no se rompe); y **el
invariante**: un cuarto estado terminal inventado por `monkeypatch` tiene que quedar cerrado para abonos
**sin tocar `service.py`**. Si el abono se cuela, el test falla con un mensaje que lo dice y nombra el
estado, no con un `AttributeError` de plomería — el centinela es `get_company_today`, lo primero que el
servicio consulta después de la puerta.

`tests/integration/test_contracts.py` (2, de punta a punta contra Postgres): ampliar de verdad y abonar
sobre el viejo → `409 CONTRACT_SUPERSEDED`, `details` con el sucesor, cero abonos registrados y la deuda del
sucesor intacta; y la otra mitad, **que el sucesor sí acepta ese abono** — un rechazo que manda a un sitio
que tampoco acepta sería peor que el bug.

Verificado a la inversa:

| Versión de la puerta | Resultado (unitarios) |
|---|---|
| La vieja, `in ("paid", "auctioned")` | **3 failed** — *«La puerta de los abonos dejó pasar un contrato en `superseded`»* |
| Lista a mano pero hoy completa, `("paid", "auctioned", "superseded")` | **3 failed** — el `superseded` se rechaza con el código equivocado y el estado inventado se cuela |
| La arreglada, derivada de la constante | 5 passed |

El caso del medio es el que justifica las dos mitades del arreglo a la vez: con la lista completa el bug de
plata ya no está, pero el mensaje sigue siendo un callejón sin salida **y** el invariante sigue roto.
El de integración con el código viejo devuelve `201` y emite el recibo, que es la evidencia del daño.

**Suite completa con Docker arriba: 432 tests** — 431 passed + el fallo de `test_error_catalog` antes de
documentar el código; documentado, 432 passed (425 previos + 7). `ruff check` / `ruff format --check`
limpios y `mypy app` sin hallazgos.

**Sin migración, sin despliegue y sin tocar datos** más allá de la Postgres local de los tests. No hace falta
reparar nada en la remota: F21-10 ya verificó que **no hubo un solo abono registrado sobre ninguno de los
cuatro contratos padres** después de su recargo, así que este defecto nunca llegó a mover plata en la base
real. Lo que cambia es que ahora tampoco puede.

---

### Pendiente operativo que ningún agente puede cerrar

✅ **Resuelto el 21/09/2026.** Mateo se autenticó en Fly y el backend quedó desplegado. Verificado sobre lo
servido: `/openapi.json` responde `title: Prendo API` y `/api/v1/health` responde `ok`.

**La lección operativa:** desplegar el backend **no es un solo comando**. `fly deploy` actualiza la app pero
**no la Machine programada del job nocturno** — eso salió a la luz justo en este despliegue y es el origen
de F21-10. Después de cada `fly deploy` que cambie lógica del job (`recompute_all_statuses`,
`expire_overdue_subscriptions` o lo que llamen), hay que actualizar la Machine a mano y **verificar que el
`schedule` sobreviva**.

🔴 **Y no es solo `fly deploy`: `fly secrets set` TAMPOCO la actualiza.** Descubierto el 21/09/2026 al
agregar `CORS_ALLOW_ORIGINS` para el dominio propio. El rolling update dijo, textual,
`Updating existing machines … > Updating 83667db7994948 [app]` — **una sola máquina**. Medido después:
`nightly-job` quedó con `updated_at` en `21:38:06Z` y la máquina `app` en `22:02:37Z`, o sea que la del job
**no recibió el secret**. La causa es la misma que la del borrado del 27/08: `nightly-job` **no tiene process
group**, así que las operaciones que iteran por grupo la saltan.

Para CORS da igual —el job no hace peticiones de navegador—, pero **la próxima rotación de `DATABASE_URL` o
de `SUPABASE_SERVICE_ROLE_KEY` deja al job corriendo con la credencial vieja**, y el job no escribe en
`audit_log`, así que su fallo (o peor, su éxito contra algo que ya no corresponde) no deja rastro.

**La regla que queda:** después de **cualquier** cambio de secrets o de imagen, comprobar las DOS máquinas,
no la salida del comando. `flyctl machine list --app compraventa-backend-dev --json` y comparar
`updated_at`. Y darle un process group a `nightly-job` cerraría de raíz esta familia entera de problemas
—el borrado por "huérfana", el `fly deploy` que la saltea y este— que ya costó dos incidentes.

**Método.** Ninguno de estos se encontró leyendo el código a secas: salieron de **escribir la guía y después verificar cada afirmación contra el código**. Documentar el producto es una forma de auditarlo — la guía obliga a decir qué pasa exactamente, y ahí es donde se ve que el front y el backend no dicen lo mismo.

**Sin aplicar**, según la regla de reportar todo y arreglar solo lo crítico. F21-01 es el que más conviene arreglar: es una línea de texto.

---

## 🔴 F21-30 — El guardián diario nunca habría corrido (22/09/2026)

**El más irónico de todos, y lo encontró Mateo mirando la pantalla, no un test.** Se construyó
`.github/workflows/guardianes.yml` para que una ausencia silenciosa dejara de serlo, y **el guardián mismo
habría fallado en silencio.**

Mateo fue a Actions y **el workflow no aparecía**. La causa:

- La rama por defecto del repo es **`main`**, que tiene **solo el commit inicial del 15/08/2026** y está
  **141 commits atrás** de `dev`. No tiene **ningún** workflow.
- En GitHub Actions, **`schedule` y `workflow_dispatch` solo funcionan desde la rama por defecto.**
- El workflow se commiteó en `dev`. **Por lo tanto no iba a correr nunca. Ni una vez.**

Sin error, sin correo, sin nada: exactamente la clase de ausencia que el guardián venía a combatir.
`ci.yml` sí funciona, pero por una razón distinta —se dispara por `push`, y esos sí corren desde la rama que
se empuja—, y esa asimetría es justo lo que lo vuelve invisible: *hay* workflows funcionando en el repo, así
que nada parece roto.

**La lección, que es la misma de F21-10 con otra ropa:** una pieza cuya única señal de vida es que haga su
trabajo necesita que alguien verifique **que se ejecuta**, no solo que está escrita. Aquí ni siquiera hacía
falta esperar a la medianoche: bastaba con abrir Actions y mirar. **No se miró.**

**Arreglado:** la rama por defecto pasó a **`dev`** (decisión de Mateo, 22/09). Se descartó duplicar el
workflow y el script en `main` por el argumento que este mismo día quedó escrito en `rules.py`: *dos copias
del mismo archivo no divergen por decisión, divergen por omisión*. Y se descartó mergear `dev` a `main`
porque `main` está declarada como rama de producción y producción todavía no existe.

**De paso cierra otra trampa que nadie había mirado:** con `main` como rama por defecto y 141 commits atrás,
**quien clonara el repo se llevaba el código del 15/08** sin que nada se lo dijera.

**Qué verificar cuando se agregue cualquier workflow programado:** que exista en la **rama por defecto**, y
correrlo una vez a mano con **Run workflow** antes de confiar en su horario. Un workflow que nunca se vio
correr no está programado: está escrito.

---

## Hallazgos al corregir la guía para publicarla — 22/09/2026 (cinco)

Salieron de verificar **contra el código** dos afirmaciones que la guía ya hacía, antes de republicarla.
**Las dos estaban mal**, y una de ellas era una corrección mía del día anterior — o sea que el error
sobrevivió a una ronda de revisión. Es exactamente el patrón que este documento ya registra: *el contenido
heredado no se salva por estar escrito*.

### 🔴 F21-25 · MEDIA — «Costo detenido» subestima, y subestimar es la dirección peligrosa

`features/reports/api.ts:224` pide `/reports/stale-inventory` con **`limit: 20`**, y el servicio calcula
`product_count = len(items)` y `total_cost_value` sumando **solo lo que devolvió esa página**
(`app/modules/reports/service.py:332-337`). Verificado por mí.

Con más de 20 productos sobre el umbral, la tarjeta dice *«N productos con $X en costo detenido»* y **las dos
cifras son falsas por debajo**. El dueño mira el número para decidir si liquida mercancía parada: un total
que se queda corto dice «no es tanto» justo cuando sí lo es.

**No falla, no avisa y no se nota**: con pocos productos el número es correcto, así que el error aparece solo
cuando la empresa crece — que es cuando más importa. El arreglo es devolver los totales del universo
completo, no los de la página. Queda como advertencia en la guía mientras tanto.

### F21-26 · BAJA — Un comentario que dice lo contrario del código

El docstring de `PayablesCard` (`frontend-starter/src/features/reports/components/ContablesSection.tsx:17-25`)
afirma: *«El proveedor con la deuda más vieja aparece primero en la lectura, no el que más debe»*. El SQL
ordena `order by sum(e.total_cost) desc` (`app/modules/reports/repository.py:346`): es **exactamente al
revés**.

Otra vez *«un comentario del código puede estar mintiendo»*, que en este proyecto ya costó un `catch` vacío.
La guía quedó escrita con lo que hace el SQL.

### F21-27 · BAJA — Docstring desactualizado en los rankings

`features/reports/rankings.ts:21-26` dice que el ranking va *«sobre TODO el histórico»* porque *«`GET /sales`
no tiene filtro de fecha»*. Desde el **02/09/2026** sí lo tiene, y `useItemSales` manda `from_date`/`to_date`
(`features/reports/api.ts:120`). La UI y la guía dicen «del rango», que es lo correcto; el comentario es el
que quedó atrás.

### F21-28 · BAJA — El Excel de Ventas puede dejar la columna «Cliente» vacía, sin avisar

Resuelve los nombres con `fetchAllCustomers()` (`features/customers/api.ts:26`), **también topado en 2.500**
(`app/modules/customers/router.py:23`). Con más de 2.500 clientes, algunas filas salen sin nombre y **nada lo
dice**. Caso remoto hoy; no se puso en la guía para no cargar un aviso ya denso.

### F21-29 · COSMÉTICA — «más de N días» cuando el filtro es `>=`

`StaleCard` rotula *«Sin venderse hace más de N días»* pero el `having` es `>=`
(`app/modules/reports/repository.py:414`). Un producto con exactamente N días aparece bajo un rótulo que dice
que no debería.

---

## Hallazgos del diseño de notificaciones — 21/09/2026 (seis, y una corrección al relato de F21-10)

Salieron de escribir `docs/NOTIFICACIONES.md`. **Es la quinta vez que documentar algo resulta ser la forma
más eficaz de auditarlo**, y la primera en que el hallazgo sale de diseñar algo que **todavía no existe**:
para decidir a quién se le manda un correo hubo que mirar de dónde sale cada dirección, y ahí aparecieron.

Los tres primeros los verifiqué yo contra el código, no según el informe.

### F21-19 · MEDIA — El backend no valida el formato del correo del cliente

`app/modules/customers/schemas.py:17` y `:32` declaran `email: str | None` **pelado**, mientras
`app/modules/identity/schemas.py:17` sí usa `EmailStr`. La validación vive **solo en el frontend** (`zod`),
así que cualquier otro consumidor de la API —o un script de importación— escribe basura sin resistencia.

Hoy no molesta porque nadie le manda correo a un cliente. **El día que se manden, molesta**: una dirección
inválida no rebota, se la traga el proveedor, y el aviso se da por entregado. Es el insumo directo del
problema de "¿y si el correo está mal escrito y le llega a un tercero?".

### F21-20 · BAJA — `company.settings.grace_days` es configuración muerta

Default `30` desde `00002_platform.sql:22`, y **ningún código la lee**: el `grep` sobre `app/` solo devuelve
un comentario en `company/service.py:72`. Verificado.

Es peligrosa por su nombre: es tentadora para "los días de gracia" de cualquier cosa nueva —por ejemplo los
días de aviso previo de una cuota— y reusarla ataría dos reglas sin relación. **Si se necesita un parámetro
de días para avisos, va uno nuevo.**

### F21-21 · MEDIA — El vencimiento de la suscripción no se avisa: el corte es en seco

`expire_overdue_subscriptions` audita y escribe `subscription_event` (`platform/service.py:400-438`), pero
**nadie le avisó antes al dueño**: la empresa se encuentra la app cerrada. Hay **2 suscripciones ya
`expired`** en dev.

Es el único evento del catálogo de notificaciones que hoy **se rompe en silencio del lado de la plataforma**,
y es de los más baratos de arreglar porque el job que lo detecta ya existe y ya corre.

### F21-22 · INFORMATIVA — Corrección al relato de F21-10: el job **sí** audita, pero la mitad que importa no

En F21-10 quedó escrito que «el job nocturno no escribe en `audit_log`, así que no dejó rastro forense».
**Es cierto a medias, y la mitad correcta importa:** el **segundo** paso del job
(`expire_overdue_subscriptions`) **sí** audita, con `user_id = NULL`. El que **no** audita es el **primero**,
`recompute_all_statuses` — que es exactamente el que causó el daño y por el que no se pudo saber qué vector
escribió cada fila.

O sea: el patrón de auditar desde un job **ya existe en este código**. Agregarlo a `recompute_all_statuses`
no es inventar nada, es copiar lo de al lado.

### F21-23 · BAJA — `company.contact_email` está casi vacío

`00002_platform.sql:16`, nullable. Es el **único** lugar donde hoy vive un correo de contacto de la empresa,
y de él dependería el `Reply-To` de cualquier correo que se le mande a un cliente. Hay que tratar el caso
nulo **desde el primer envío**, no después.

### F21-24 · ALTA SI SE OLVIDA — El diseño de notificaciones carga más peso sobre la Machine más frágil

`NOTIFICACIONES.md` le agrega un **tercer paso** al job nocturno. No es un defecto nuevo: es el riesgo
conocido de F21-10 **creciendo**. La Machine `nightly-job` sigue sin process group (a propósito, ver
§F21-10), así que `fly deploy` y `fly secrets set` la saltean.

**Al implementar notificaciones hay que actualizarla en el mismo despliegue y verificar que el `schedule`
sobreviva.** Para eso está `scripts/qa/verificar_job_nocturno.py`, que ya cazó este caso en vivo el 21/09:
el `fly deploy` de esa tarde dejó la Machine en la imagen anterior y el guardián lo reportó con el comando
de arreglo armado.

---

## Hallazgos de la parte 6 de la guía — 21/09/2026 (siete, uno de dinero)

**Salieron todos de escribir la parte 6 («Reportes y cierre contable») y verificar cada afirmación contra el
código.** Ninguno de leer código a secas. Es la cuarta vez que documentar el producto resulta ser la forma
más eficaz de auditarlo: la guía obliga a decir **qué pasa exactamente**, y ahí se ve que dos capas no dicen
lo mismo.

Los cuatro primeros son de la **misma familia**: el Estado de resultados y los KPI del período **no saben
que existen las devoluciones y las anulaciones**. Verificado: `grep` de `return|sale_return|devol` sobre
`reports/repository.py` y `reports/service.py` no devuelve **nada**. No es que las traten mal — no las
tratan.

### ✅ F21-12 · ALTO — Una devolución no baja el Estado de resultados, y el activo se cuenta dos veces · **RESUELTO 22/09/2026**

`profit_summary` filtra `status = 'completed'` (`app/modules/reports/repository.py:203-206`) y **una
devolución nunca cambia el `status`**: el único `update public.sale set status` de todo el código es a
`'voided'` (`app/modules/sales/repository.py:200`). Verificado por mí, no según informe.

Entonces, después de una devolución con reingreso:

- el **ingreso sigue contado** en el Estado de resultados, porque la venta sigue `completed`;
- su **costo sigue dentro de `cost_of_goods_sold`**;
- y la mercancía **vuelve a `available`** (`app/modules/sales/service.py:598-600`), así que **vuelve a
  sumar** en la valorización del inventario.

**Efecto: ingresos y utilidad sobreestimados por todo lo devuelto, y el mismo activo contado dos veces** —
una vez como costo de algo que se vendió y otra como inventario disponible. Es exactamente la familia de
error que este proyecto ya corrigió cuatro veces (*"ingreso no es ganancia"*, *"el interés es ingreso; el
capital recuperado no"*), reaparecida por el lado de las devoluciones.

**Arreglado el 22/09/2026: los reportes LEEN las devoluciones.** La pregunta abierta ("¿una devolución
parcial deja la venta en `completed`?") se resolvió por el lado contrario al que sugería: **sí la deja**, y
la devolución entra como **contra-ingreso** (*devoluciones en ventas*), registrado en el período de la
**DEVOLUCIÓN**. No se toca `sale.status` y no existe `partially_returned`.

**Por qué esa decisión y no borrar la venta:**

1. **Es lo que este proyecto ya hace.** Su doctrina es *"el estado de resultados sale de los DOCUMENTOS,
   no de los movimientos de caja"*. Una devolución **es un documento** (`sale_return`, 00042), igual que
   `sale`, `contract_payment` y `expense`. Leerla es aplicar la regla que ya existe, no inventar una.
2. **Cambiar `sale.status` sería peor.** Una devolución **parcial** sacaría la venta ENTERA del resultado
   — en el test de prorrateo, los 900.000 de la cadena habrían desaparecido por devolver un anillo de
   100.000. Y reescribiría un mes ya cerrado, que es exactamente el defecto F21-15.
3. **`sale_return.return_date` existe** (y `sale_return` es inmutable por `forbid_change`, así que esa
   fecha es confiable), así que el contra-ingreso cae en su propio período y un mes cerrado no cambia
   hacia atrás.

**El doble conteo se cerró por el lado del COSTO, y eso es deliberado.** Una vez que el costo devuelto sale
de `cost_of_goods_sold`, que el artículo esté de nuevo en `available` y vuelva a valorizarse es
**correcto**: volvió a ser inventario de verdad. **El doble conteo era el síntoma de no registrar la
devolución, no un defecto aparte.** Queda escrito acá porque es lo que evita que alguien "arregle" también
la valorización del inventario y termine restando dos veces. El test
`test_devolucion_total_saca_el_ingreso_y_su_costo_sin_tocar_el_inventario` fija justamente eso: la
valorización tiene que volver **exactamente** al número que tenía antes de vender.

**El prorrateo del descuento.** `discount_amount` vive en la CABECERA de la venta, así que una devolución
parcial solo puede llevarse su parte. Se prorratea por **participación en el bruto** de la venta
(`quantity × unit_price` sobre el bruto total), **no por unidades**: un descuento de 100.000 sobre una
venta de una cadena de 900.000 y un anillo de 100.000 no se reparte 50/50 — al anillo le tocan 10.000, no
50.000. Sin el prorrateo se restaría el bruto devuelto entero y saldría del resultado más plata de la que
entró. Se redondea por línea a 2 decimales (igual que `subtotal` al vender); devolver una venta completa en
varias devoluciones puede dejar un residuo de centavos contra `discount_amount`, y repartirlo exigiría
saber cuál devolución es "la última", dato que no existe al consultar.

**Dónde se ve: línea propia.** «Devoluciones» aparece como su **propia fila** en el estado de resultados
(pantalla y exportación a Excel), no restada en silencio de «Ventas». Un número que baja sin explicación es
lo que hace que nadie confíe en un reporte: si «Ventas» cayera sola, el dueño creería que el sistema perdió
la venta. En la gráfica de tendencia la serie sí se pinta neta, pero se llama **«Ventas netas»** — el
número más bajo tiene nombre, y el desglose está arriba.

**Dónde se aplicó (los TRES lugares que calculan ingreso, para no crear una cuarta definición):**

| Lugar | Qué cambió |
|---|---|
| `reports/repository.py::profit_summary` | CTE `devoluciones` por `return_date`; devuelve `return_count`, `returns_gross`, `returns_discounts`, `returns_cost`. Alimenta `/reports/profit` **y** `/reports/income-statement`. |
| `reports/repository.py::monthly_series` | CTE `devoluciones` por mes de `return_date`; nueva columna `sales_returns` en cada punto de `/reports/series`. |
| `reports/service.py` | `net_revenue = gross − discounts − sales_returns`; `cost_of_goods_sold` neto de `returns_cost`; `total_revenue = sales_revenue − sales_returns + interest_revenue`. |

`sales_revenue` significa lo mismo en los tres (**bruto de devoluciones, neto de descuento**) y
`sales_returns` es el hermano nuevo en todos: el netear ocurre en `net_revenue`/`total_revenue`, nunca
escondido dentro de un campo que ya tenía otro significado.

**Solo devoluciones de ventas `completed`**, igual que el ingreso: si la venta se anula después, su ingreso
desaparece entero de su propio período (F21-15) y restar además la devolución lo descontaría dos veces.

**`sales_kpis` (el dashboard) NO se tocó, a propósito.** `today_total`/`month_total` son actividad de venta
del día ("¿cuánto vendí hoy?"), no el estado de resultados; restarles devoluciones de ventas de otros días
haría que el KPI de hoy dependiera de ventas viejas. Eso es F21-13 (KPI del front brutos de devoluciones y
anulaciones), que sigue abierto y es del front.

**Dos cosas que se vieron al arreglar esto y NO se tocaron** (van como recomendación, no como parte del
arreglo):

- `sales.void_sale` **no verifica si la venta ya tiene devoluciones**. Anular una venta parcialmente
  devuelta repone el stock COMPLETO otra vez (`service.py::void_sale` recorre `sale_line` sin descontar lo
  ya devuelto) y emite un contra-movimiento por el `total` entero. Es un defecto real, pero es del carril
  de las ANULACIONES, no del de las devoluciones.
- Anulación y devolución **siguen siendo cosas distintas**, y así deben quedar: una anulación dice "esta
  venta nunca ocurrió" y sale del resultado retroactivamente (F21-15). Tratarlas igual era tentador al leer
  el código y sería un error: borra la distinción entre corregir un error de digitación y registrar un
  hecho del negocio.

**Tests** (`tests/integration/test_reports.py`, los cuatro **verificados fallando** contra el código
anterior): devolución total (+ la valorización del inventario intacta), devolución parcial con prorrateo del
descuento, devolución en un mes distinto al de la venta (el mes viejo queda idéntico), y la línea propia en
`/income-statement` + la columna en `/series`.

### F21-13 · MEDIO — Las devoluciones y anulaciones no restan de los KPI del período

`REVENUE_CONCEPTS = {interest_payment, sale}` y el revenue exige `direction === 'in'`
(`frontend-starter/src/features/reports/aggregate.ts:46-47, 151-152`). Una anulación emite
`concept='sale'` con `direction='out'` (`app/modules/sales/service.py:407-419`) y una devolución emite
`concept='sale_return'` (`:697-701`): **ninguna de las dos toca «Ventas» ni «Ingresos operativos»**, aunque
sí entran al flujo de caja. Los KPI del período son **brutos** de devoluciones y anulaciones.

### F21-14 · MEDIO — Los descuadres de caja no aparecen en ningún reporte

El ajuste del arqueo se graba con `session_id = None` (`app/modules/cashbox/service.py:385-396`) y
`closings_breakdown` hace **INNER JOIN** con `cash_session` (`app/modules/reports/repository.py:156`).
Consecuencia: el desglose de Reportes **nunca cuadra** contra el saldo de la cuenta de efectivo cuando hubo
descuadres, y los faltantes del mes **solo se ven en el Histórico**, uno por uno.

El `session_id = None` está bien argumentado en el código (si el ajuste colgara de la sesión, el acta
cuadraría sola y el descuadre se volvería invisible). **Lo que falta es el otro lado: nada suma los
descuadres de un período.**

### F21-15 · MEDIO — Un mes ya cerrado cambia hacia atrás

Anular hoy una venta vieja la saca del Estado de resultados de **su** mes (mismo filtro `status='completed'`
sobre `sold_at`). **No existe un reporte congelado** ni forma de reimprimir el resultado tal como se vio el
día del cierre. Mitigado en la guía con «exportá y archivá el día del cierre», que es un parche de
procedimiento, no una solución.

### F21-16 · BAJO — El botón «Exportar a Excel» de Contratos desaparece al buscar

Está dentro del bloque `{!isSearching && …}` junto con las pestañas
(`frontend-starter/src/features/contracts/pages/ContractsListPage.tsx:126, 144`). Sin ningún aviso: parece
que la función se fue. Misma familia que F21-01 (*"afirmar o mostrar algo que no coincide con la pantalla es
peor que no decir nada"*).

### F21-17 · BAJO — El Excel de Ventas no permite notar las devoluciones

La columna `Estado` sale de `sale.status`, que sigue en `completed` tras una devolución
(`frontend-starter/src/features/sales/pages/SalesListPage.tsx:43`), y no hay columna de devoluciones. Quien
concilie con ese archivo **no tiene cómo verlas**. Es F21-12 asomando por la exportación. **Sigue abierto
tras el arreglo de F21-12 (22/09/2026)**, y a propósito: el Estado de resultados ya las resta y las muestra
en línea propia, pero la lista de Ventas es otra pantalla — `sale.status` sigue en `completed` después de
una devolución, que es precisamente la decisión que se tomó. Lo que falta ahí es una columna, no un
cambio de estado.

### F21-18 · BAJO — `inventory_purchased` ignora `paid_at`

`app/modules/reports/repository.py:465-491`. Contablemente correcto (una compra es un activo, no un gasto),
pero la línea «mercancía comprada» del pie del Estado de resultados **no es salida de caja** cuando la
compra quedó por pagar. Puesto como salvedad explícita en la guía, donde se explica por qué la utilidad no
coincide con la plata del cajón.

### Dos cosas que no son defectos del código

- **El texto del §8 de la guía —«las exportaciones tienen un tope de 2.500 filas»— era impreciso, y al
  corregirlo el 22/09 resultó que mi propia corrección también lo era.** Lo medido, camino por camino:
  **Ventas, Contratos e Inventario** sí se cortan en **2.500** (`limit` 50 por defecto del router × `maxPages`
  50, `frontend-starter/src/lib/api/pagination.ts:48`). **Reportes NO se corta**: *Resumen* son 7 filas fijas
  de una consulta agregada, *Desglose* sale de `/reports/closings-breakdown`, que **no tiene parámetro
  `limit`**, y *Rankings* está topada en **16 filas** por `.slice(0, 10)` y `.slice(0, 6)`
  (`features/reports/rankings.ts:53, 68`). El `limit: 100` × 50 páginas que yo había anotado como "5.000" es
  el tope de lo que se **lee** para calcular los rankings, **no de lo que se exporta**. Corregido en la guía
  con una tabla por exportación.
  **Y un hallazgo que cambió el texto:** las tres listas paginan con `order by id` sobre un `uuid` aleatorio,
  así que **un archivo cortado no conserva «las 2.500 más recientes»** — lo que falta queda repartido por
  todo el histórico. El aviso viejo dejaba entender lo contrario. Es el principio que este documento ya tiene
  escrito (*«un listado ordenado por un id aleatorio no está ordenado»*) asomando por la exportación.

### Y un defecto del propio entregable

**La guía desborda 166 px horizontalmente a 390 px de ancho**, en todas sus partes. Medido con Playwright
sobre una copia **sin** la parte 6: idéntico, así que es preexistente. Causa: en
`@media (max-width: 900px)` la `.shell` pasa a `flex-direction: column` pero conserva
`align-items: flex-start`, así que `main` se dimensiona a *fit-content* y el `table { min-width: 520px }`
estira la página entera; las tablas dejan de scrollear dentro de su `.scroller` y se sale el documento
completo. **Arreglado el 21/09 con una línea** (`align-items: stretch` en esa regla): desborde 166 → **0**,
`main` vuelve a 390 px y las tablas scrollean internamente. El escritorio no se toca, porque la regla es
solo ≤900 px.

---

## Hallazgos sueltos — 20/09/2026 (fuera de fase)

Salieron mientras se preparaban los insumos de la guía de usuario leyendo el código pantalla por pantalla.
No son de una fase: son de comparar el catálogo de errores del front contra lo que el backend emite de verdad.
**Ninguno rompe nada visible** — el mensaje del backend igual llega y se muestra — pero los tres impiden que
la UI reaccione *por código*, que es la regla del proyecto (`errors.ts`, regla 9 de `CLAUDE.md`).

| # | Hallazgo | Dónde | Gravedad |
|---|---|---|---|
| F20-01 | **`ALREADY_CLOSED_TODAY` no coincide con lo que emite el backend.** El front cataloga `ALREADY_CLOSED_TODAY`; el backend emite **`CASH_SESSION_ALREADY_CLOSED_TODAY`**. Como `parseApiError` solo tipa lo que está en `KNOWN_CODES`, cae a `UNKNOWN` | `frontend-starter/src/lib/api/errors.ts:19` vs `app/modules/cashbox/service.py:117-119` | Media — ninguna rama de UI puede reaccionar al caso |
| F20-02 | **`IDEMPOTENCY_IN_PROGRESS` no está en el catálogo del front.** El backend lo emite con un mensaje claramente de mostrador: *«Esta misma operación ya se está registrando. No la repitas»*. Es el caso del doble clic en "Vender" | `app/core/errors.py:162-168` | Media — es un error de usuario real, no técnico |
| F20-03 | **`MULTIPLE_REGISTERS_NOT_SUPPORTED` tampoco está** | `app/core/errors.py:76` | Baja — el propio docstring dice que hoy no se llega por la API |

**Por qué importa más de lo que parece.** El proyecto ya tiene escrito que *"los códigos de error son un contrato"*
y que toda aserción de QA va contra el `code`, nunca contra el status. Un código que el backend emite y el
front no cataloga es un contrato roto de un solo lado: el test que lo cubriera pasaría igual.

**Arreglo sugerido** (no aplicado — sigue la regla de reportar todo y arreglar solo lo crítico): agregar los
tres a `KNOWN_CODES` y, para F20-01, decidir cuál de los dos nombres es el bueno y alinear el otro.

### Un hallazgo de método, no de código

La guía de usuario tiene escrita la regla *"cada tabla de campos se escribe leyendo el schema de Zod del
formulario"*. **Esa regla solo se puede cumplir en la mitad de las pantallas:** en todo `features/` hay
**13 schemas de Zod**, y el resto de los formularios valida a mano con `useState` y chequeos en el submit.
Para esas pantallas, "obligatorio u opcional" hay que sacarlo del handler de submit y del backend, no de un
schema que no existe. Conviene corregir la regla antes de escribir las 13 pantallas que faltan, o la guía va
a afirmar cosas que nadie verificó.

---

## Fase 10 — Concurrencia y volumen (09/09/2026)

**Veredicto: la integridad aguanta, el manejo del conflicto no.** Cinco cajeros vendiendo la última unidad al mismo tiempo producen **una sola venta** — pero los cuatro que pierden la carrera reciben un `500`, no un error de negocio. Y la promesa de idempotencia se rompe justo en el caso para el que existe.

Las pruebas se lanzaron **en el mismo instante** (todas esperando un evento común), no en fila.

### F10-01 · Bajo concurrencia, quien pierde la carrera recibe un 500 — MEDIA-ALTA, abierto

**Cinco ventas simultáneas de la última unidad** (claves de idempotencia distintas: cinco intentos legítimos):

```
[500, 500, 201 #5, 500, 500]
ventas creadas: 1           ✓
stock final: 0.000 · sold   ✓
```

**Cinco requests con la MISMA clave** (un reintento de red real, sobre un artículo con stock de sobra):

```
[500, 500, 500, 201 #6, 500]
números de venta distintos: {6}   ✓
stock: bajó 1, no 5               ✓
```

**Lo que está bien y hay que reconocerlo:** la integridad no se rompe en ninguno de los dos casos. Y quien la salva es la base de datos — `CHECK (quantity >= 0)` en `inventory_item` y `UNIQUE(company_id, idempotency_key)` en `sale`. Es exactamente el principio del proyecto: *«la base de datos hace cumplir, aunque haya un bug en la query»*.

**Lo que falla es lo que ve el usuario.** Las dos causas:

1. **Stock.** Las cinco validan «hay 1 disponible» a la vez, las cinco descuentan, y el `CHECK` rechaza a las que dejarían negativo. La excepción sube sin capturar → `500`, en vez de `400 «No hay suficiente cantidad disponible»`.
2. **Idempotencia.** `create_sale` hace `find_by_idempotency_key` y **después** inserta: un *comprueba-y-actúa*. Bajo concurrencia las cinco consultan antes de que ninguna haya insertado, las cinco intentan, y el índice único deja pasar una.

El segundo es el más serio, porque **rompe la promesa justo cuando importa**. `API_GUIDE` §1 dice: *«reenviar el mismo valor en un reintento de red devuelve el resultado ya creado, no duplica»*. El caso típico de reintento es un **timeout**, o sea que el reintento sale *mientras la primera sigue en vuelo* — que es exactamente esta carrera. El front recibiría `500` de una venta que **sí se hizo**, y el cajero, un error genérico sin `code` que mapear. Puede intentar vender otra vez.

**Fix sugerido:** capturar la violación de unicidad y resolverla como el camino que ya existe (devolver la venta creada); y traducir el `CHECK` de stock al `400` de negocio que el usuario espera.

### F10-02 · `fetchAllPages` corta a 10.000 filas sin ninguna señal — MEDIA, abierto

```ts
} while (cursor && pageCount < maxPages)   // maxPages = 50
return items
```

Al llegar a 50 páginas sale del bucle y devuelve lo que lleva. **El llamador no tiene forma de saber si trajo todo o se cortó.** Con `limit ≤ 200`, el techo son 10.000 filas.

El tope en sí es correcto y el comentario del código lo justifica bien (sin él, un catálogo que crece dispararía cientos de requests). El problema es el silencio: lo usan las **cuatro exportaciones a Excel** y la pantalla de Reportes, así que un dueño que exporte su histórico de ventas para el contador puede recibir un archivo truncado **que parece completo**. Ya estaba anotado en `PENDIENTES_FRONTEND.md` («corta en silencio»), sin cuantificar ni proponer salida.

**Fix sugerido:** devolver también si se truncó (`{items, truncated}`) y que la UI lo diga — «mostrando los primeros 10.000 registros».

### Lo que se probó y está bien

| Comprobación | Resultado |
|---|---|
| 5 ventas simultáneas de la última unidad | **Una sola** venta; stock `0.000` y estado `sold` |
| 5 requests con la misma clave de idempotencia | **Una sola** venta; el stock baja 1, no 5 |
| 5 aperturas de caja simultáneas con la caja ya abierta | Las cinco → `409 CASH_SESSION_ALREADY_OPEN`, sin un solo 500 |
| Paginación por cursor en 5 listados, de 3 en 3 | Sin repetidos ni saltos: el total paginado coincide con traerlo de una vez (incluido `audit-log` con 40 páginas y 119 filas) |
| `limit` = 201 · 0 · −5 | `422 VALIDATION_ERROR` los tres |
| Cursor basura · cursor de otro recurso | `400 BAD_REQUEST` |

> **Nota:** la apertura de caja simultánea es el contraste que vale la pena mirar. Ahí la validación ocurre **antes** y el conflicto se resuelve como error de negocio (`409`) en las cinco, sin ningún 500. Es el comportamiento que le falta a la venta.

---

## Fase 9 — Los caminos de entrada (09/09/2026)

**Veredicto: los flujos que históricamente rompieron están sólidos.** El alta de usuario sobrevive a los crawlers, la recuperación funciona, el cambio de contraseña propia exige la actual y el panel de plataforma opera. Los dos hallazgos son de **contexto que la app tiene y no muestra**.

> El cambio de día dio un escenario que no se puede fabricar: la sesión de caja quedó **abierta desde ayer**. Es exactamente lo que pasa cuando alguien olvida cerrarla.

### F9-01 · Una caja abierta desde ayer no se distingue de una abierta hoy — MEDIA, abierto

Con la sesión del **08/09** todavía abierta el **09/09**, la app dice:

```
Caja abierta · desde las 4:38 PM
```

**Sin fecha.** Un cajero que llega a las 8 de la mañana lee «abierta desde las 4:38 PM» y no tiene cómo saber que esa hora es de ayer — de hecho es una hora imposible para la mañana, así que o parece un error o se asume que es de hoy.

El sistema **sí sabe** la fecha: `session_date: 2026-09-08` viene en la respuesta de `/cashbox/sessions/current`. Solo no la muestra.

**La consecuencia, medida:** registré un gasto de 5.000 el 09/09 y entró en el turno del 08/09. Al cerrar, el acta del 08/09 lo incluye — los gastos en efectivo pasaron de 60.000 a **65.000**. Es decir: **el acta de un día contiene movimientos de otro**, el arqueo mezcla el efectivo de dos jornadas, y los reportes por `session_date` atribuyen al día equivocado.

El resto del comportamiento es correcto y coherente con lo documentado: `/sessions/current` devuelve la de ayer (una abierta sigue siendo la sesión en curso), `/sessions/today` da `404`, y abrir una nueva da `409 CASH_SESSION_ALREADY_OPEN` — el sistema obliga a cerrar antes de abrir otra. Lo que falta es decirlo.

**Fix sugerido:** mostrar la fecha en el banner cuando la sesión no es de hoy («Caja abierta desde ayer 08/09, 4:38 PM»), que es dato que ya viaja en la respuesta.

### F9-02 · Los enlaces de acceso mandaban a la URL de preview, no a la del cliente — MEDIA, ✅ CERRADO (verificado el 21/09/2026)

```
el enlace apunta a : https://la-legal-front-end-git-dev-mateos-projects-85710491.vercel.app
la app del cliente : https://la-legal-front-end.vercel.app
```

`FRONTEND_URL` en Fly apuntaba entonces a la URL de preview (confirmado con `fly ssh console -C "printenv FRONTEND_URL"`). Afectaba a **los dos** caminos de alta: invitar y recuperar. *(Estado hoy: corregido — ver el recuadro al final de este hallazgo.)*

**Por qué importa:**

1. El empleado nuevo recibe por WhatsApp un enlace que lleva el nombre interno del proyecto y del dueño (`mateos-projects-85710491`). Un enlace así, pidiendo crear una contraseña, **se lee como phishing**.
2. Tras poner la contraseña queda navegando en un dominio distinto del que le dijeron. Si guarda el marcador, guarda el equivocado.
3. Son dos **orígenes** distintos: la sesión que crea ahí no existe en la URL oficial, así que tiene que volver a entrar.

**Y la razón que lo justificaba ya caducó.** `CONTINUAR.md` dice: *«`FRONTEND_URL` en Fly debe seguir apuntando a la URL de preview de dev»*, porque Supabase descartaba la de producción al no estar en las *Redirect URLs*. Pero Mateo las agregó el 03/09, **y** el fix del `token_hash` eliminó del todo la dependencia del redirect. Comprobado hoy pidiéndoselo a `generate_link`:

```
se pidió  : https://la-legal-front-end.vercel.app/auth/callback
devolvió  : https://la-legal-front-end.vercel.app/auth/callback   ✓ respetado
```

**El cambio era un `fly secrets set FRONTEND_URL=…`, y se aplicó.**

> **Corrección del 21/09/2026.** Este hallazgo decía *«no lo apliqué: es infraestructura»*, y **eso era
> falso**: el secret ya estaba cambiado. Medido contra la app desplegada, no deducido de un commit:
>
> ```bash
> flyctl ssh console -a compraventa-backend-dev -C "printenv FRONTEND_URL"
> # → https://la-legal-front-end.vercel.app
> ```
>
> O sea: el valor en vivo es la URL que usa el cliente, sin el nombre interno del proyecto ni del dueño.
> Los tres motivos de arriba (se lee como phishing · marcador equivocado · dos orígenes distintos) ya no
> aplican.
>
> **Por qué el documento se equivocó y por qué importa.** Un hallazgo de infraestructura no deja rastro en
> el repo: no hay diff que mirar, así que el estado escrito y el estado real se separan **en silencio** y
> nadie se entera hasta que alguien mide. Esa es la forma exacta del error, y la regla que deja: **el estado
> de un hallazgo de infraestructura se cierra leyendo el ambiente, nunca el historial de commits.**
>
> Lo que sigue abierto no es esto: es que `FRONTEND_URL` **no está en `.env.example`** ni en los comentarios
> de `fly secrets set` de `fly.dev.toml` / `fly.prod.toml` — ver `frontend-starter/docs/PLAN_MARCA.md`
> Fase 4.

### F9-03 · `sale_return` sin traducir en el acta de cierre — BAJA, abierto

En el desglose del acta, todos los conceptos salen en español («Abono de interés», «Desembolso de préstamo», «Recibido del convenio», «Consignado / trasladado») menos uno: **`sale_return`**. Mismo patrón que `completed`/`voided` en el listado de Ventas (F8-03): un valor del enum sin etiqueta en el mapa del front, visible en un documento que se imprime y se archiva.

### Lo que se probó y está bien

| Comprobación | Resultado |
|---|---|
| **El alta de usuario completa, en navegador real** | El enlace apunta a la app con `token_hash`; los cuatro crawlers (WhatsApp, Telegram, Slack, Googlebot) reciben `200` **sin quemarlo**; después de ellos, abre «Crea tu contraseña», guarda y **entra a la app**. El fix del 03/09 aguanta |
| Activación `invited → active` | El usuario nuevo quedó `active` tras entrar con su propia contraseña |
| **Recuperación de contraseña**, de punta a punta | Enlace fresco → pantalla de contraseña → entra; y la anterior deja de servir |
| Enlace ya consumido | Pantalla propia: «Este enlace ya se usó. Cada enlace sirve una sola vez…» |
| **Cambio de la propia contraseña** en `/perfil` | Exige la actual; tras el cambio la original ya no entra y la nueva sí. La pantalla explica por qué se pide («para que nadie pueda cambiarla desde tu pantalla si la dejas abierta») |
| **Panel de plataforma** en navegador | Lista 7 empresas con estado, plan y vencimiento; el detalle abre con suspender, extender, monto pagado y notas |
| Caja de ayer: `current` / `today` / abrir otra | Devuelve la de ayer · `404` · `409 CASH_SESSION_ALREADY_OPEN` |
| Cerrar la de ayer y abrir la de hoy | Correcto; tras cerrar, `today` sigue en `404` hasta abrir la del día |
| **Acta de cierre de caja** *(pendiente de la Fase 8)* | Imprime completa: «Acta de cierre — 08/09/2026», saldo inicial, esperado, contado, diferencia, la justificación del descuadre, el desglose módulo×concepto×medio y la hora de cierre |

> **Confirmado en la UI**, la cola de H-14: en el panel, las empresas suspendidas o vencidas muestran plan y vencimiento como «—», indistinguibles de una que nunca tuvo plan.

---

## Fase 8 — Documentos y archivos (08/09/2026)

**Veredicto: Storage está impecable y las plantillas funcionan; los dos hallazgos son sobre lo que el sistema *deja* hacer.** Se puede activar una plantilla vacía y entregarle al cliente un contrato sin cuerpo, y una vez activada cualquier plantilla no hay forma de volver al documento por defecto.

### Storage: cero hallazgos

Era la pieza de más riesgo —ahí viven cédulas, prendas y contratos firmados (Ley 1581), y es la única donde el front habla directo con Supabase sin pasar por el backend. Probado con las sesiones reales de dos empresas:

| Comprobación | Resultado |
|---|---|
| Un usuario sube a la carpeta de **su** empresa | `200` |
| La empresa B sube a la carpeta de la empresa A | `403` — *new row violates row-level security* |
| La empresa B pide URL firmada de un archivo de A | `404 Object not found` — **no revela que existe** |
| La empresa B descarga el archivo directo | `404` |
| Subir un **PDF** o un **HTML con `<script>`** | `415 invalid_mime_type` |
| Subir un PNG de **9 MB** | `413 Payload too large` |
| Subir un WEBP | `200` |
| Acceder como público (bucket abierto) | `404 Bucket not found` — es privado |
| Acceder solo con la anon key | `404` |
| URL firmada propia | `200`, y los bytes descargados son **idénticos** al original |

### F8-01 · Se puede activar una plantilla vacía, y el contrato sale sin cuerpo — MEDIA, abierto

`POST /company/document-templates` acepta `body: {}`. Activándola e imprimiendo un contrato real, esto es **todo** lo que sale en papel:

```
QA Compraventa S.A.S. · ZZ QA — auditoria 08/09 · NIT 900123456-7
Encabezado QA
Contrato de empeño #7
08/09/2026
Aviso legal QA
Pie QA
```

137 caracteres. **Sin cliente, sin prendas, sin monto, sin tasa, sin firmas.** El encabezado y el pie salen porque los pone `PrintLayout`; el cuerpo —que es el contrato— viene de la plantilla, y está vacío.

El caso realista no es exótico: alguien crea una plantilla, borra el contenido para empezar de cero, la guarda, la activa, y **a partir de ahí todos los contratos se imprimen en blanco**. El banner que se agregó el 28/08 avisa «guardada pero inactiva»; nada avisa «activa y vacía». Y un contrato de empeño en blanco no ampara la prenda del cliente.

**Fix sugerido:** rechazar la activación (no la creación — un borrador vacío es legítimo) de una plantilla sin contenido, o advertirlo en el diálogo de activar.

### F8-02 · Una vez activada una plantilla, no hay vuelta al documento por defecto — MEDIA, abierto

```
POST .../{id}/activate        → 200
PATCH .../{id} is_active:false → 200, y la ignora — sigue activa
DELETE .../{id} (la activa)    → 409 TEMPLATE_IS_ACTIVE
```

No existe endpoint de desactivar. El único camino es activar **otra** plantilla, así que el JSX de fábrica —que `API_GUIDE` §4 bis presenta como la red de seguridad, *«cero riesgo de regresión para empresas que nunca toquen esto»*— queda inalcanzable en cuanto alguien toca esto una vez.

Combinado con F8-01 es peor: si activas una vacía por error, para deshacerlo tienes que **construir una plantilla nueva desde cero** que replique el documento de fábrica. Y el `PATCH` que responde `200` ignorando el campo hace creer que se desactivó.

### F8-03 · El estado de una venta se muestra en inglés crudo — BAJA, abierto (conocido)

El listado de Ventas muestra `completed` y `voided` tal cual. Ya estaba documentado en `PENDIENTES_FRONTEND.md` el 27/08 («`sale.status` nunca estuvo en `STATUS_LABELS`… hallazgo documentado, no arreglado, fuera de alcance») y sigue visible en una pantalla de uso diario.

### Lo que se probó y está bien

| Comprobación | Resultado |
|---|---|
| `GET`/`PATCH /company/settings` | `PATCH` parcial conserva lo no enviado; `null` explícito borra |
| Separación de permisos de los datos de impresión | El Asesor ve razón social, NIT y textos vía `/me`, pero `GET /company/settings` le da `403` |
| Crear plantilla con los tres layouts | `classic`, `modern`, `compact`; sin `layout` toma `classic`; uno inventado da `422` |
| Guardar ≠ activar | Las cuatro nacen inactivas (el caso del bug 6e) |
| Swap transaccional al activar | Siempre **exactamente una** activa por tipo |
| Borrar la plantilla activa | `409 TEMPLATE_IS_ACTIVE` |
| Leer la plantilla activa | El Asesor sí (`contracts.view`), Bodega no; y listar todas exige `company.configure` |
| `document_type` inventado · `body` nulo · HTML como string | `422` los tres |
| Aislamiento entre empresas | La empresa B no lista, activa, borra ni renombra plantillas de A (`404`) |
| Campos dinámicos | Se sustituyen con los datos reales y bien formateados: `$ 1.000.000`, `5.00%`, `CC 1010101010`, `08/03/2026` |
| Campo inexistente | Degrada a `[campo desconocido: x]` en vez de romper el render |
| Impresión del **contrato** con plantilla activa | Correcta, con encabezado, cuerpo, aviso legal y pie |
| Impresión del **paz y salvo** | Correcta: empresa, cliente con documento, contrato, capital, fecha de cancelación y número de recibo |
| Impresión del **comprobante de venta** | Correcta |

**Queda sin probar de esta fase:** el acta de cierre de caja, que exige una sesión cerrada — la del laboratorio quedó abierta a propósito para las fases anteriores.

---

## Cobertura: qué se probó y qué no (al cerrar la Fase 7)

Los **109 endpoints** pasaron por la matriz de permisos, pero eso solo verifica que **rechazan** bien — no que funcionen. Con profundidad funcional real:

| Módulo | Endpoints | Cobertura funcional |
|---|---|---|
| `contracts` | 11 | Alta — el ciclo completo, incluidos remate e import |
| `cashbox` | 12 | Alta — apertura, arqueo, cierre, reapertura, gastos |
| `sales` | 7 | Alta — venta, anulación, devoluciones, notas crédito |
| `accounts` | 7 | Alta — falta `PATCH` de cuenta |
| `reports` | 10 | Alta — falta `stale-inventory` |
| `inventory` | 18 | Buena — ingresos, egresos, publicación, kardex, transformaciones |
| `identity` | 12 | Alta |
| `customers` | 4 | **Parcial** — sin detalle, edición ni ficha con historial cruzado |
| `catalogs` | 10 | **Parcial** — sin detalle de proveedor, sus compras ni su resumen |
| `platform` | 9 | **Parcial** — sin eventos de suscripción ni audit-log de plataforma |
| `company` | 8 | **Ninguna** — solo permisos |

### Sin probar, por riesgo

**Alto — datos sensibles o lo que el cliente se lleva en la mano**

- **Storage y fotos.** `PhotoUploader`, subida a Supabase, URLs firmadas, RLS del bucket. Ahí viven cédulas, prendas y contratos firmados (Ley 1581), y es la única pieza donde el front habla directo con Supabase sin pasar por el backend.
- **Impresión.** Contrato, paz y salvo, acta de cierre y comprobante de venta — hoy reemplazan a los PDFs.
- **Plantillas de documentos.** El módulo `company` entero: editor Tiptap, tres formatos visuales, activar/desactivar. **Tuvo cuatro bugs en agosto**, uno de ellos tirando «No se pudo cargar la app».

**Medio — flujos que ya mordieron antes**

- El alta de usuario **en navegador**: el canje del enlace con `verifyOtp` y la pantalla de crear contraseña. Se probó la API, no el camino real.
- Recuperar contraseña desde el login, y cambiar la propia en `/perfil`.
- El panel de plataforma por UI (se hizo todo por API).
- Exportación a Excel en las cuatro pantallas.

**Medio — condiciones que no se dan probando de a uno**

- **Concurrencia**: dos usuarios vendiendo el mismo artículo o cerrando caja a la vez.
- **Volumen**: paginación con miles de registros y el tope silencioso de `fetchAllPages` (10.000 filas, corta sin avisar).

**Bajo**

- Navegación por teclado y lectores de pantalla (se midió contraste, no la operación sin ratón).
- Filtros y buscadores de cada listado (se probó el de contratos).
- Google OAuth: no está configurado.

---

## Fase 7 — Regresión (08/09/2026)

**El objetivo no era automatizar todo, sino que lo que se rompió una vez no pueda volver en silencio.** Tres de los hallazgos de esta auditoría comparten la misma forma: nadie los vio porque nada los vigilaba. Cuatro tests nuevos cubren esas tres formas.

**Cada uno se verificó viéndolo fallar**: se reintrodujo el defecto original y se comprobó que el test lo caza, antes de darlo por bueno. Es la misma regla que el proyecto ya aprendió — *«un test escrito contra un payload inventado confirma el bug en vez de encontrarlo»*.

### F7-01 · `CREDIT_NOTE_INSUFFICIENT_BALANCE` estaba documentado y el backend no lo emitía — **arreglado**

**Lo encontró el test mientras lo escribía**, antes de terminarlo. `API_GUIDE` §15 documenta ese código para cuando la nota crédito no alcanza; `sales/service.py` lanzaba un `AppError` sin `code`, que cae en el `BAD_REQUEST` por defecto. Confirmado en vivo:

```
nota crédito con saldo 1.320.000 · intento redimir 99.999.999
  → 400  code=BAD_REQUEST
  API_GUIDE §15 documenta: CREDIT_NOTE_INSUFFICIENT_BALANCE
```

Es **exactamente** el bug que costó once días de trabajo (`NOT_FOUND` donde el front escuchaba `CASH_SESSION_NOT_OPEN`): un contrato entre dos capas que solo conocía una. El front que escuche el código documentado nunca lo recibe. Arreglado pasando el `code` explícito.

### Los cuatro tests

| Test | Qué vigila | Se vio fallar con |
|---|---|---|
| `unit/test_endpoint_guards.py` | Que **ningún endpoint quede sin `require_permission`** — el «bug de revisión» de `CLAUDE.md` regla 3. Recorre los routers con el AST, sin red ni base: milisegundos | Un endpoint nuevo sin guard, añadido a propósito en `audit/router.py` |
| `unit/test_error_catalog.py` | Que **todo código de error esté en el catálogo** de `API_GUIDE` §15, y que el catálogo no documente códigos muertos. Mismo molde que `test_audit_actions.py`, que ya había demostrado su valor | Un `code="CODIGO_INVENTADO_QA"` metido en un módulo |
| `integration/test_smoke_listings.py` | Que **ningún listado responda 5xx** ni devuelva texto plano, con una empresa **vacía**. Recorre los 40 GET sin parámetros de ruta que expone el OpenAPI | Reintroduciendo la cláusula rota de `/accounts/transfers`: los dos tests fallan |
| `frontend/tests/token-contrast.test.ts` | Que **los tokens de texto cumplan WCAG AA** sobre los fondos de la app. La regla estaba escrita en `DESIGN_SYSTEM` §4.10 y nadie la medía | Corrigiendo `--text-muted` al valor propuesto: el test avisa |

El smoke es el que más valor tiene por línea escrita: **habría cazado el 500 de `/accounts/transfers` el día que se escribió**. Ese endpoint aparecía nueve veces en `test_accounts.py` y las nueve eran POST — un endpoint puede estar roto al 100% y parecer cubierto si lo que se ejercita es su vecino. Corre con una empresa vacía a propósito: la lista vacía es el caso que más se olvida, y era justamente el que reventaba.

### Los defectos conocidos quedan marcados, no escondidos

Los dos tests de contraste que hoy **no** pasan están marcados con `it.fails` y no con `skip`:

```
Tests  163 passed | 2 expected fail (165)
```

CI queda en verde documentando el defecto real, y el día que se corrija el token el test empezará a fallar por *«pasó cuando se esperaba que fallara»* — obligando a quitarle el `.fails`. Un `skip`, en cambio, se olvida. Comprobado: al aplicar el valor propuesto para `--text-muted`, el test reacciona.

### Qué NO se automatizó, y por qué

No todo lo de esta auditoría debe correr en CI. Lo que queda como **herramienta manual** en `scripts/qa/`:

- **La matriz completa de permisos** (420 comprobaciones × 4 roles). Necesita usuarios reales en Supabase Auth y tarda cinco minutos: es una auditoría periódica, no un test de cada PR. Lo que sí quedó en CI es su parte estática y barata — que ningún endpoint quede sin guard.
- **El barrido de contraste y responsive con Playwright.** Playwright no es dependencia del proyecto (`ARCHITECTURE` §10) y montarlo en CI es un proyecto en sí. La parte que sí se automatizó es la que vale para el 90% de los casos: los tokens.
- **Los flujos de dinero de punta a punta.** Ya están cubiertos por los tests de integración de cada módulo; duplicarlos como E2E costaría más de lo que aporta.

### Estado de las suites

| | Antes de la auditoría | Después |
|---|---|---|
| Backend | 325 | **333** — 2 de los bugs arreglados (Fase 1) + 6 de regresión (Fase 7) |
| Frontend | 161 | **165** — 163 en verde + 2 marcados como defecto conocido |

Ambas suites corridas enteras al cerrar: `333 passed` y `163 passed | 2 expected fail`.

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
ventas = _dec(t["gross_revenue"]) - _dec(t["discounts"])  # ← resta el descuento
intereses = _dec(e["interest_collected"])  # ← NO resta interest_discounts
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
| Saldos derivados: listado vs. extracto | Coinciden; la `cash` sin saldo corriente (la base se redeclara en cada apertura), `bank` con acumulado — **ya no aplica: `00048` (10/09) hizo que los cuatro tipos lleven saldo corriente** |
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

Todo vive en el proyecto Supabase de **dev** (`driyubkodnsqxbtxcmaz`). Las empresas reales (*La Legal*, *LA GRAN LEGAL*, *Empresa Demo Front*) **no se tocan** salvo autorización explícita — que ya ocurrió una vez: ver "Datos de prueba en LA GRAN LEGAL" abajo.

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
- **Una cuenta `Caja fuerte` (`vault`)** creada el 10/09 al probar `00049` en vivo, con 700.000 tras un traslado desde el cajón. Se dejó a propósito: es el fixture para probar que una caja fuerte no puede cobrar y que no entra al arqueo diario.
- **Dos gastos de 1.000 con la nota "QA regresión 00052 — borrable"** (11/09/2026), de verificar en vivo que el cambio de `_resolve_active_register` no rompe el registro de un gasto real. Bajaron el efectivo esperado del turno de 770.000 a 768.000. Se dejaron: `cash_movement` es inmutable por trigger y corregirlos exigiría contra-movimientos que ensucian más que los 2.000.
- **Una cuenta `Cajon 2` desactivada**, y un `cash_movement` de −70.000 con su contra-movimiento de +70.000. Es el rastro de la demostración de por qué **dos cuentas de efectivo hacen incuadrable el arqueo** (el gasto pagado desde el segundo cajón lo dejó en negativo y bajó el arqueo del turno a un número que no correspondía a ninguno de los dos). El movimiento no se pudo borrar —`cash_movement` es inmutable por trigger— así que se corrigió como manda el propio sistema: con un contra-movimiento. **Es el ejemplo vivo de esa disciplina.**

### Datos de prueba en LA GRAN LEGAL (09/09/2026)

**La excepción a la regla de arriba, autorizada explícitamente por Mateo.** La empresa tenía cinco contratos, todos `active` y creados el mismo día: no había con qué probar la pantalla de contratos, los filtros por estado, la cola de remate ni el paz y salvo. Se sembraron **22 contratos que cubren los seis estados**, 3–4 de cada uno, con `scripts/qa/seed_contratos.py`.

| Prefijo | Estado resultante | Cuántos |
|---|---|---|
| `DEMO-A*` | `active` | 4 (uno con interés pagado por adelantado — `interest_paid_until` en el futuro) |
| `DEMO-M*` | `in_arrears` | 4 (1, 2, 3 y 4 meses adeudados) |
| `DEMO-P*` | `in_extension`, prórroga **vigente** | 4 |
| `DEMO-R*` | `in_extension`, prórroga **vencida** → `ready-for-auction` | 4 |
| `DEMO-X*` | `auctioned` | 3 |
| `DEMO-S*` | `paid` | 3 |

**La llave fue `POST /contracts/import`, no `POST /contracts`.** Dos razones, y las dos importan:

1. **No desembolsa.** La creación normal saca el préstamo de la caja: 22 contratos por ahí le habrían movido el efectivo esperado de la sesión a una empresa que la tiene abierta desde el 03/09. El import existe justo para la foto financiera al corte — sin sesión y sin `cash_movement` (`docs/MIGRACION_CONTRATOS.md`).
2. **Es el único camino que permite fabricar estados.** `status` no se acepta en ningún body: el backend lo DERIVA de `interest_paid_until` contra hoy, con la ventana del snapshot del contrato. `POST /contracts` fija `start_date = hoy`, así que solo puede producir `active`. El import acepta las dos fechas, y el mismo recálculo de `GET /contracts/{id}` persiste el estado antes de responder.

**Lo que hay que saber para leer los números.** "Listo para remate" **no es un `status`**: es `in_extension` con `extension_ends_at` en el pasado, que es lo que consulta `GET /contracts/ready-for-auction`. Por eso el conteo por estado muestra 8 `in_extension` (4 vigentes + 4 vencidas) y la cola de remate muestra 4.

**Un contrato de Tecnología nunca puede estar `in_arrears`** en esta empresa: su `arrears_window_months` es 1, así que el primer mes adeudado ya dispara la prórroga. Los cuatro de mora son de Joyería por necesidad, no por elección.

**Los efectos colaterales, elegidos:**

- Los 3 `paid` generan su `contract_payment` y su `cash_movement`, **por transferencia a Bancolombia** — verificado que no existe ni un movimiento en efectivo, así que el arqueo del cajón queda intacto. Recibos #1 a #3.
- Los 3 `auctioned` crean su `inventory_item` en `draft` con `origin='auction'`, costo = capital + interés pendiente (p. ej. 1.300.000 + 7 meses × 5% = 1.755.000). Quedan **sin publicar**: no tienen código y no están en vitrina.

**El actor.** Los contratos los firma `qa.datos.prueba@qalab.com` ("Datos de prueba (QA)"), creado a propósito con nombre explícito para que en la UI se lea *creado por* y se distinga del trabajo real de Wilderson. No se pudo invitar por API (`POST /identity/invitations` exige `identity.manage_users`, que exige ya ser usuario de la empresa): se hizo el bootstrap del RUNBOOK — auth user con el service role + fila `app_user` con el rol Admin. **Queda `inactive` al terminar el script**: es un admin con contraseña conocida dentro de la empresa de un cliente. Reejecutar el script lo reactiva solo.

**Reversible.** Todo lleva `legacy_code` con prefijo `DEMO-` y una nota fechada. `python scripts/qa/seed_contratos.py --limpiar` lo borra, localizando cada fila por **ID** y nunca por tipo — borrar `cash_movement` por `reference_type='contract_payment'` alcanzaría abonos reales de la empresa.

### Ejemplo vivo de una ampliación de préstamo (10/09/2026)

Además de los 22, quedaron en LA GRAN LEGAL los contratos **#28 y #29**, que son una cadena de recargo completa creada al verificar `00051` en vivo:

| | #28 (`DEMO-RECARGO`) | #29 |
|---|---|---|
| Capital | 1.000.000 | **1.400.000** |
| Estado | `superseded` | `active` |
| Prendas | `transferred` | `in_custody` |
| Interés mensual | 50.000 | 70.000 |

Prenda avaluada en 2.000.000, LTV 70 % → cupo de 400.000, retirado completo. A la caja salieron **solo** los 400.000. Sirve para mirar en pantalla cómo se ve la cadena en los dos sentidos; `--limpiar` no los toca (`#29` no lleva prefijo `DEMO-`), así que si estorban hay que borrarlos a mano.

### Cómo se probó

- **Matriz de permisos:** `require_permission` es un `Depends`, así que se evalúa **antes** del body. Un request con body vacío y un UUID inexistente devuelve `403` si falta el permiso y `422`/`404` si lo tiene — así se barre el catálogo entero sin crear ni modificar nada.
- **Mapa de endpoints:** los paths salen de `/openapi.json` (la verdad), y el permiso de cada uno del AST de los `router.py` cruzando por el nombre de la función. Ojo: varios routers declaran **más de un `APIRouter`** en el mismo archivo, así que tomar el último `prefix` asignado da rutas equivocadas.
- **UI:** Playwright vía el caché de npx, con login real de cada rol contra Vercel.
- **Contraste:** `getComputedStyle` recorriendo los nodos de texto y calculando el ratio WCAG contra el primer ancestro con fondo opaco.

Los scripts viven en [`scripts/qa/`](../scripts/qa/) — ver su README para levantar el laboratorio y correr la matriz de permisos completa.
