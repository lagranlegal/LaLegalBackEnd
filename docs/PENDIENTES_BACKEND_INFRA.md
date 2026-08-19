# Pendientes para revisar con backend/arquitectura/infraestructura

> Documento de traspaso — no es una queja sobre el backend, es la lista concreta de huecos reales encontrados construyendo el front, para decidir en equipo qué se resuelve y en qué orden. Cada punto dice qué se verificó, cómo, y por qué importa para el negocio (no solo técnicamente). Última actualización: 19/08/2026 (segunda revisión — se suman los puntos 13 a 18: reportes, panel de plataforma, ajustes de usuario, paginación, edición de artículos de remate, resumen financiero).
>
> **Tercera revisión (backend, mismo día):** puntos 1, 3, 4, 17 y la mitad de 14 (`PlanOut.modules` + `CompanyOut` con plan/suscripción) ya resueltos — ver la nota "✅ Resuelto" en cada uno. Puntos 10 y 14 (auditoría) además tenían un diagnóstico distinto al reportado — corregido inline, no era el bug descrito originalmente.
>
> **Cuarta revisión (backend, mismo día):** se suma el punto 19 (`ContractItemOut.inventory_item_id`, reportado por el front después de la tercera revisión) — también resuelto.

## 1. Búsqueda de clientes: solo por nombre, no por documento

`GET /customers?q=` hace full-text search **solo sobre `full_name`** — confirmado contra el backend real: `?q=123456789` (número de cédula exacto de un cliente que sí existe) devuelve `items: []`, mientras que `?q=Juan`/`?q=Pérez`/`?q=juan perez` sí lo encuentra.

**Por qué importa para el negocio, no solo técnicamente:** en el mostrador de una compraventa, el cliente casi siempre entrega su cédula física — el operador tipea el número, no el nombre. Con el buscador actual, si no recuerda cómo está escrito el nombre exacto en el sistema, no puede encontrarlo por documento aunque lo tenga en la mano. Esto afecta directamente **crear contrato**, **venta con cliente registrado**, y cualquier flujo que use `CustomerPicker`.

**Sugerencia:** que `?q=` busque también por `doc_number` (coincidencia exacta o prefijo, no necesita ser full-text ahí — un documento se busca completo o casi completo, no por fragmentos como un nombre).

**✅ Resuelto (19/08/2026):** `?q=` en `GET /customers` ahora matchea `doc_number` (exacto o prefijo) además del full-text de `full_name`. Ver `docs/API_GUIDE.md` §5.

## 2. `GET /contracts` sin `?q=` — buscador de contratos es un parche client-side

Confirmado: el único filtro es `?status=`. El front ya tiene un buscador (agregado en la revisión post-paso-10) pero es un parche: trae los primeros 200 contratos y filtra en el navegador por número o código anterior — **nunca por nombre del cliente**, porque `ContractOut` solo trae `customer_id`, no el nombre, y resolverlo fila por fila sería un request por cada uno.

**Sugerencia:** `?q=` en `GET /contracts` que busque por número de contrato, `legacy_code`, y — si es razonable del lado del backend — nombre/documento del cliente (un `JOIN` contra `customer`, que el front no puede hacer eficientemente).

## 3. `GET /sales` no tiene NINGÚN filtro (ni siquiera `status`)

Confirmado en el schema: `{cursor?, limit?}` únicamente. Ni `customer_id`, ni `status`, ni fecha. Esto bloquea two cosas:
- El historial de cliente (`/clientes/$id`) trae hasta 200 ventas y filtra por `customer_id` en el navegador — mismo parche que el punto 2, con el mismo techo de 200.
- No hay forma de, por ejemplo, listar solo ventas anuladas, o ventas de un rango de fechas, sin traer todo y filtrar en el front.

**Sugerencia:** al menos `?customer_id=` y `?status=` en `GET /sales` — son los dos filtros que ya tiene `GET /contracts` y que la simetría entre ambos módulos sugiere que deberían coincidir.

**✅ Resuelto (19/08/2026):** `GET /sales` ya acepta `?customer_id=` y `?status=`. Ver `docs/API_GUIDE.md` §10. `?q=` con número de contrato/`legacy_code`/cliente en `GET /contracts` (punto 2) y filtros de fecha en `GET /sales` (parte del punto 13) siguen pendientes.

## 4. `CompanyOut` (panel de plataforma) no trae plan ni fecha de expiración de suscripción

Ya documentado en `docs/RECOMENDACIONES.md` §1.8 — se repite acá porque es exactamente el tipo de cosa que esta lista busca centralizar. Un super-admin puede extender una suscripción sin ver la fecha de expiración actual.

**✅ Resuelto (19/08/2026):** `CompanyOut` (creación, detalle y listado) trae `plan_code`/`plan_name`/`subscription_expires_at` de la suscripción `active` actual (LEFT JOIN — `null` si no hay ninguna, nunca desaparece la fila). Ver `docs/API_GUIDE.md` §3.

## 5. `GET/PATCH /company/settings` — bloquea dos cosas, no solo "Configuración"

Ya en el backlog original del backend (`docs/pending/API_GUIDE.md` §15) como pendiente de la pantalla "Configuración". La revisión post-paso-10 encontró que **también** bloquea la firma de la empresa en el documento imprimible del contrato — `docs/pending/CONTEXTO.md` §3 pedía explícitamente que la firma se insertara automáticamente en el PDF de todos los contratos nuevos, y hoy no hay dónde subirla ni de dónde leerla. El documento imprimible del front (`ContractPrintView.tsx`) deja dos líneas en blanco para firmar a mano en vez de eso. Detalle completo en `docs/RECOMENDACIONES.md` §1.9.

## 6. PDFs (contrato firmado, acta de cierre) — siguen sin generarse

Decisión ya tomada explícitamente (backend §15: "requieren Storage + una librería de PDF, fuera de alcance"). El front cubre ambos con vistas imprimibles (`PrintLayout`, `@media print`) mientras tanto — funcionan, pero no son un PDF descargable/archivable, son "imprime desde el navegador". Si en algún momento se prioriza un PDF real server-side, sería quien reemplace esto, no algo que el front necesite rehacer.

## 7. `GET /reports/series` — serie mensual para el dashboard

Ya en backlog aceptado (`docs/pending/API_GUIDE.md` §15). El dashboard hoy solo tiene KPIs de hoy/mes, sin gráfica de tendencia. Sin cambios desde la última revisión.

## 8. Definir con el cliente qué va en "Reportes" y "Configuración"

No es un pendiente técnico — es una decisión de producto que todavía no se tomó. Hoy:
- **"Reportes"** no tiene pantalla propia. Su contenido real ya existe pero está repartido: KPIs en el dashboard (`/`), histórico de cierres dentro de Caja (`/caja`). Falta decidir si eso se consolida en una pantalla `/reportes` (y qué más iría ahí — ¿reporte de cartera de contratos? ¿ventas por período? ¿algo de inventario?) o si se deja como está.
- **"Configuración"** bloqueada por el punto 5. Cuando exista el endpoint, falta decidir el alcance exacto: ¿solo logo/firma/timezone, o también parámetros de negocio (tasas por defecto, ventanas de mora) que hoy solo se editan por categoría?

## 9. Verificación en vivo pendiente por falta de una segunda cuenta de prueba

Dos caminos de código están implementados pero **nunca se dispararon de verdad** contra el backend, porque hacerlo hubiera arriesgado la única sesión de administrador activa usada para todas las pruebas de esta integración:
- `LAST_ADMIN_SAFEGUARD` (paso 8, identity) — el modal explicativo existe, pero nunca se forzó el rechazo real desde el backend.
- El camino negativo del guard de `/platform` (paso 10) — un usuario autenticado SIN el claim `app_metadata.platform_role=super_admin` debería rebotar a `/`; solo se verificó el camino "sin sesión en absoluto".

**Para desbloquear esto:** una segunda cuenta Admin activa en la empresa de pruebas (para el primero) y una cuenta cualquiera sin el claim de plataforma (para el segundo) — no es un cambio de backend, es un pendiente operativo de tener más cuentas de prueba disponibles.

## 10. Comportamiento de "meses completos" en el límite exacto — confirmar si es intencional

Al fabricar datos de prueba con `POST /contracts/import` se encontró un comportamiento consistente y repetible, no un error aislado: si `interest_paid_until` queda **exactamente** a N meses calendario de hoy (ej. hoy 19/08, `interest_paid_until` = 19/07 → exactamente 1 mes), `months_owed` cuenta **N-1**, no N — hace falta que `interest_paid_until` sea al menos un día más viejo (18/07) para que cuente como el mes completo. Se confirmó dos veces con datos distintos (1 mes y 3 meses de diferencia), mismo resultado ambas veces.

No se reporta como bug — probablemente es intencional (no se penaliza el día exacto del vencimiento, hay que estar realmente *pasado* del mes) y de hecho suena razonable para no ser injustos con el cliente. Se deja anotado para que quede confirmado explícitamente como comportamiento esperado, no algo que alguien "arregle" después sin saber que ya se decidió así.

**Diagnóstico corregido (backend, 19/08/2026):** corrí `months_between` con las fechas reales de `DEMO-MORA-1MES`/`DEMO-MORA-1MES-B` contra el "hoy" real de ahora mismo — los dos calculan `N` exacto, no `N-1`; no hay ningún corrimiento de límite. Lo que pasó: `DEMO-MORA-1MES` se creó (probablemente 08-18) cuando en ESE momento le faltaba un día para el mes completo (correcto, 0 meses adeudados en ese instante), y el `status` quedó grabado con esa foto — el sistema recalcula al leer (`GET /contracts/{id}`) o por el job nocturno, nunca solo, así que un registro sin releer desde entonces queda con el estado de cuando se creó (`CLAUDE.md`: "el estado del contrato solo lo calcula el servicio + job nocturno"). Confirmado en vivo: un `GET /contracts/{id}` sobre ese mismo contrato ahora lo corrige a `in_arrears` sin tocar nada más. No hay cambio de código que hacer.

## 11. Cómo probar como super-admin (no es un pendiente, es documentación que faltaba)

La cuenta de pruebas que se ha usado durante toda la integración (`mateojaras@gmail.com`) **ya tiene** el claim `app_metadata.platform_role: "super_admin"` configurado en Supabase Auth — confirmado contra el JWT real. Entrar a `/platform` con esa misma sesión ya funciona hoy, sin nada que configurar. No hay flujo de auto-servicio para volverse super-admin (por diseño: `docs/pending/ARCHITECTURE.md` §5 — "se fija manualmente en Supabase Auth, una sola vez, fuera de la app") — para dar ese claim a otra cuenta hace falta entrar al dashboard de Supabase Auth de ese proyecto y editarlo a mano en `app_metadata`.

## 12. Datos de prueba generados para cubrir todos los estados de contrato

Para poder probar abonos/mora/prórroga/remate de verdad (pedido explícito), se usó `POST /contracts/import` para fabricar contratos con fechas ya vencidas en varios estados. Quedan en el ambiente de dev, con `legacy_code` autoexplicativo:

| # | legacy_code | Estado | Para qué sirve |
|---|---|---|---|
| 9 | `DEMO-MORA-1MES-B` | En mora (1 mes) | Probar el flujo normal de abono de 1 mes |
| 10 | `DEMO-MORA-2MESES` | En mora (2 meses) | Probar abono parcial (1 de 2) o completo |
| 11 | `DEMO-MORA-CON-ABONO` | En mora, con 1 abono ya registrado | Ver el historial de abonos con datos reales |
| 12 | `DEMO-PRORROGA` | Prórroga activa (NO vencida) | Confirmar que "Rematar" correctamente NO aparece todavía |
| 13 | `DEMO-LISTO-REMATE` | Prórroga vencida | Probar "Rematar" en vivo, sin auctionar (a diferencia del #5, que ya se rematō probando el bug de la revisión anterior) |
| 14 | `DEMO-PARA-PAGAR` | Pagado (capital + interés saldados) | Ver un contrato cerrado, con la prenda `returned` |
| 8 | `DEMO-MORA-1MES` | Quedó en `active`, no `in_arrears` como su nombre sugiere | Efecto colateral real del punto 10 de arriba (límite exacto de 1 mes) — se deja como evidencia del hallazgo, no se puede borrar (no hay `DELETE` de contratos) |

Todos con `Anillos de oro` como categoría (la única nivel 3 que existe hoy en la empresa de pruebas) y prendas/montos variados para que se vean distintos en las listas.

---

## 13. Reportes — qué falta para separar contabilidad de tienda y contratos con claridad

Pedido explícito: "qué necesitamos del backend para hacer los reportes de forma clara". Hoy existe `GET /reports/dashboard` (KPIs de hoy/mes), `GET /reports/closings` (histórico de cierres) y `GET /cashbox/sessions/{id}/report` (desglose módulo×concepto×medio, pero **solo de UNA sesión a la vez**). No alcanza para un reporte contable real. En orden de prioridad:

1. **Desglose de caja agregado por rango de fechas, no por sesión.** Es la extensión natural de algo que ya existe — `GET /cashbox/sessions/{id}/report` ya calcula módulo×concepto×medio para una sesión puntual; hace falta la misma agregación pero sumando N sesiones entre `from_date`/`to_date`. Esto es, literalmente, la "contabilidad separada de tienda y contratos" que pide `docs/pending/CONTEXTO.md` §3, consolidada en cualquier rango (mes, trimestre, lo que sea) en vez de sesión por sesión. Mejor relación esfuerzo/valor de toda la lista: no es un reporte nuevo, es agregar lo que ya se calcula.
2. **Intereses cobrados en un período — no existe en ningún lado hoy.** El dashboard tiene `capital_outstanding` (cuánto hay prestado), pero nada dice cuánto ha *generado* el módulo de empeño en intereses cobrados en el mes. Sin esto no se puede ver la rentabilidad real de Contratos.
3. **`GET /reports/series?months=12`** — ya estaba en el backlog aceptado del backend (`docs/pending/API_GUIDE.md` §15) desde antes de este documento. Sin serie histórica, "Reportes" solo puede mostrar el momento actual, no tendencia.
4. **Filtros de fecha en `GET /sales`** — mismo punto 3 de la primera revisión de este documento, se repite acá porque bloquea directamente "ventas del mes pasado" como reporte.

Menor prioridad, útiles pero no bloqueantes para una v1:
- Capital desglosado por estado en pesos (hoy el dashboard da el *conteo* de contratos por estado, no cuánto capital hay en mora vs. vigente vs. prórroga).
- Utilidad de ventas (costo del artículo vs. precio de venta — cruzar `item.cost` contra `sale_line.unit_price`, hoy no se agrega en ningún endpoint).
- Contratos rematados en un período + valor recuperado.
- Antigüedad/rotación de inventario (artículos `available` hace más de N días sin venderse).

**Decisión de producto todavía pendiente** (no técnica): ¿"Reportes" es una pantalla nueva que consume todo esto, o el resumen financiero por módulo (punto 18 de abajo) reemplaza la necesidad de una pantalla separada? Se recomienda resolverlo junto con el punto 18.

## 14. Panel de plataforma — no se ve fecha de expiración, ni historial de cambios de suscripción

Al entrar como super-admin (punto 11), la lista y el detalle de empresas no muestran ni el plan ni la fecha de expiración — ya documentado como punto 4 de este archivo y en `docs/RECOMENDACIONES.md` §1.8. Verificando más a fondo para esta revisión, aparecieron dos problemas adicionales, uno de ellos más serio que el original:

- **`PlanOut` no trae lo que `docs/pending/CONTEXTO.md` §3 dice que un plan debería tener.** El documento describe planes con *"módulos habilitados, límite usuarios, precio"* — el schema real (`PlanOut`) solo trae `{id, name, code, price, active}`. No hay forma de que el front muestre "este plan permite hasta 5 usuarios" ni qué módulos habilita, aunque el concepto ya esté descrito en la arquitectura.
- **Extender o suspender una suscripción NO queda en la auditoría — confirmado en vivo, no es una suposición.** Se hizo `POST .../subscription/extend` y luego `POST .../suspend` + `POST .../activate` sobre una empresa de prueba real, y se revisó `GET /audit-log?module=platform` inmediatamente después: **solo aparece el `create_company` original** — ninguna de las tres acciones nuevas generó una entrada. Esto es distinto (y más importante) que "no veo cuánto se pagó": hoy, si dos personas del equipo de plataforma tienen acceso de super-admin, no hay ningún registro de quién extendió una suscripción, cuándo, ni con qué `notes` (el campo `notes` de `SubscriptionExtendIn` se manda pero no hay ningún lugar donde se pueda volver a leer — se pierde). Contradice la regla general del propio backend (`docs/pending/CLAUDE.md`: *"toda acción sensible... inserta en `audit_log` en la misma transacción"*) — suspender el acceso de una empresa entera y cambiar su fecha de vencimiento son acciones tan sensibles como cualquiera de las que sí se auditan.
- **Recomendación sobre "valores pagados"**: dado que el cobro es 100% manual y fuera del sistema (`docs/pending/CONTEXTO.md` §3: *"el cliente paga por fuera del sistema"*), hoy no hay NINGÚN registro financiero de lo pagado — ni siquiera el monto. Sugerencia concreta: agregar un campo opcional `amount`/`amount_paid` a `SubscriptionExtendIn`, y que quede auditado (con el punto anterior resuelto, esto ya alcanzaría para tener un historial básico de "quién pagó cuánto y cuándo" sin construir un módulo de facturación completo).

**✅ Resuelto en parte (19/08/2026):** `PlanOut.modules` ya se expone (la columna ya existía con datos reales, solo faltaba el schema — ver `docs/API_GUIDE.md` §3); falta `max_users`/límite de usuarios, que sí necesita columna nueva. Sobre la auditoría: **diagnóstico corregido** — el insert de `extend_subscription`/`set_company_status` funciona bien, confirmado consultando `audit_log` directo sin RLS (las filas existen). El problema real es que `GET /audit-log` es tenant-scoped (RLS por `company_id` de quien pregunta) — un super-admin nunca puede ver auditoría de una empresa que no es la suya propia, sin importar el filtro `?module=`. Falta un endpoint tipo `GET /platform/companies/{id}/audit-log` con el mismo molde que el resto de `platform` (`require_super_admin` + sesión bypass sin RLS) — no es una pieza nueva de arquitectura, es aplicar el patrón que ya existe. Sigue pendiente (Tier 3), junto con `amount_paid`.

## 15. Ajustes/configuración de usuario — qué recomiendo incluir

No hay ninguna pantalla de "mi perfil" hoy — el pendiente ya estaba anotado desde el paso 2 ("Perfil"/"Cambiar contraseña" en el menú del avatar). Verificado qué hace falta de backend para cada pieza razonable:

| Función | ¿Necesita backend nuevo? | Detalle |
|---|---|---|
| Ver mi perfil (nombre, correo, rol, empresa) | No | Ya disponible completo vía `GET /me`, sería una pantalla de solo lectura. |
| Cambiar mi contraseña | No | Va directo contra Supabase Auth (`supabase.auth.updateUser({password})`), igual que ya hace el flujo de aceptar invitación — no pasa por este backend en absoluto. |
| Editar mi nombre (`full_name`) | **Sí** | No existe ningún `PATCH /me` ni endpoint de auto-edición — confirmado, `/api/v1/me` solo tiene `GET`. Los únicos `PATCH` de usuario que existen son de admin sobre OTROS usuarios (`PATCH /identity/users/{id}/role`). |
| Foto de perfil / avatar | **Sí** | No existe ningún campo `avatar_url` en `MeUserOut`/`UserOut` — si se quiere, habría que agregarlo (el Storage ya está listo desde el paso 7b, el front puede subir la foto solo; falta el campo para guardar el path). |
| Preferencias de notificaciones | No aplica todavía | Notificaciones son Fase 2 en el roadmap (`docs/pending/CONTEXTO.md` §5) — no tiene sentido un ajuste para algo que no existe. |

**Recomendación de alcance para una v1:** perfil de solo lectura + cambiar contraseña (cero backend nuevo, se puede construir ya) y dejar nombre/avatar editables para cuando exista `PATCH /me` — no vale la pena bloquear la pantalla completa por esos dos campos.

## 16. Paginación — confirmado que ya existe en todos lados, incluida auditoría

Se verificó específicamente `GET /audit-log` (la duda puntual) y de paso el resto de listados ya construidos: **todos** usan `{cursor?, limit?}` con el mismo patrón `CursorPage_*` — confirmado en el schema (`list_audit_log_api_v1_audit_log_get` sí tiene `cursor`/`limit`, igual que `contracts`, `customers`, `identity/users`, `platform/companies`, etc.). El default documentado es 50 (máximo 200) — cómodamente por encima del mínimo de 12 pedido. **No es un pendiente real, solo faltaba confirmarlo explícitamente** — queda anotado acá como verificación, no como cambio a pedir.

## 17. Artículos creados por remate: no se pueden corregir categoría antes de publicar

Reproducido en vivo de punta a punta: se rematou un contrato, el artículo quedó en `draft` con `origin: "auction"`, `supplier_id: null` y las categorías **heredadas tal cual de la prenda del contrato** (la categoría que se eligió al crear el contrato, pensada para clasificar una prenda en garantía, no necesariamente la más adecuada para vender en tienda). Se publicó igual para confirmar el código: salió `JAO0003R` — el sufijo `R` en vez de letra de proveedor **ya funciona correctamente del lado del backend**, sin ningún bug ahí.

El problema real es que **`ItemUpdateIn` (`PATCH /inventory/items/{id}`) solo acepta `{name?, description?, sale_price?, photos?}`** — no hay forma de corregir `cat1_id`/`cat2_id`/`cat3_id` antes de publicar, aunque el artículo siga en `draft` (mismo estado en el que sí se puede editar nombre/precio/fotos sin restricción). Si la categoría heredada del contrato no es la correcta para la tienda, hoy no hay forma de arreglarlo — ni desde el front (porque el backend lo rechazaría) ni manualmente.

**Sugerencia:** agregar `cat1_id?`/`cat2_id?`/`cat3_id?` a `ItemUpdateIn`, con la misma validación de árbol de 3 niveles que ya usa `POST /inventory/entries` — la restricción de que solo se pueda mientras `status='draft'` seguiría siendo válida (`409` una vez publicado, como ya pasa hoy). No hace falta ni debería agregarse un campo de proveedor: el diseño de `origin`+sufijo `R` para artículos de remate ya es correcto tal como está, el front solo necesita mostrarlo bien (ver siguiente punto).

**Del lado del front (sin esperar al backend):** hoy `ItemEditDialog` no muestra de dónde viene un artículo — ni "origen: remate", ni el link al contrato de donde salió (`source_contract_id` sí lo trae `ItemOut`, no se usa en pantalla). Se puede corregir esto ahora mismo sin depender del punto de arriba; lo dejo anotado para hacerlo en la próxima sesión de trabajo del front.

**✅ Resuelto (19/08/2026):** `ItemUpdateIn` (`PATCH /inventory/items/{id}`) ya acepta `cat1_id?/cat2_id?/cat3_id?` mientras `status='draft'` — todo-o-nada (los tres juntos o ninguno, `400` si viene parcial), misma validación de árbol que `POST /entries`. Ver `docs/API_GUIDE.md` §9.

## 18. Resumen financiero de contratos y ventas — recomendación de dónde ubicarlo

Pedido: un apartado con el resumen en dinero de contratos (abonos, desembolsos, cartera) y de ventas, en el lugar que mejor encaje con el diseño actual de la app.

**Recomendación:** que viva dentro de "Reportes" (punto 13), no dentro de las pantallas operativas de `/contratos` y `/ventas`. Es una separación de propósito que ya sigue el resto de la app — las listas operativas (`ContractsListPage`, `SalesListPage`) están pensadas para *hacer* cosas (crear, cobrar, vender, anular), no para *analizar* — meterle un bloque financiero ahí competiría con la acción principal de la pantalla y DESIGN_SYSTEM.md ya establece "una acción primaria por pantalla". El dashboard (`/`) ya es el lugar de KPIs de un vistazo; "Reportes" sería el lugar para profundizar (por período, por módulo) sin mezclarse con ninguno de los dos.

Como complemento liviano (no reemplaza lo anterior): agregar una fila corta de KPIs arriba de `ContractsListPage` y `SalesListPage` (cartera activa + capital en mora arriba de contratos; total vendido hoy/este mes arriba de ventas) — mismo patrón `KpiRow` que ya existe en el dashboard, dando contexto inmediato sin salir de la pantalla operativa. Esto sí se puede construir con los datos que YA expone `GET /reports/dashboard` hoy, sin esperar nada nuevo del backend.

**Qué necesita el backend para el resumen completo (no el KPI liviano):** los mismos puntos 1 y 2 del punto 13 — desglose de caja por rango de fechas e intereses cobrados por período son, en la práctica, el "resumen financiero de contratos" que se pide acá. No es una pieza aparte, es el mismo pendiente visto desde dos ángulos de producto distintos (una pantalla de reportes vs. un resumen dentro de contratos) — se resuelven con el mismo trabajo de backend.

## 19. Trazabilidad contrato → artículo de inventario: falta el vínculo inverso

Pedido explícito: poder asociar un artículo rematado a su contrato de origen. La dirección **artículo → contrato** ya se resolvió del lado del front (punto 17: `ItemOut.source_contract_id` ya existía en la API, solo faltaba mostrarlo). La dirección **contrato → artículo** (desde la prenda del contrato, saber en qué artículo específico se convirtió) es la que sí necesita un cambio de backend:

- **`ContractItemOut` no trae `inventory_item_id`**, aunque `docs/pending/API_GUIDE.md` §7 describe explícitamente que existe la columna: *"`contract_item.inventory_item_id` guarda el vínculo"*. Confirmado contra el schema real (`npm run gen:api` sin diff, no es un tipo desactualizado): el campo simplemente no está en la respuesta de la API, aunque exista en la base de datos.
- El front no puede reconstruir esto de forma confiable por su cuenta: `GET /inventory/items` no tiene filtro por `source_contract_id`, y aunque lo tuviera, un contrato con **varias prendas** genera varios artículos — sin el vínculo por prenda específica, no hay forma de saber cuál artículo corresponde a cuál prenda (emparejar por nombre/descripción sería frágil, no una solución real).

**Sugerencia:** exponer `inventory_item_id` (nullable) en `ContractItemOut` — es literalmente el mismo dato que `ItemOut.source_contract_id` visto desde el otro lado, la columna ya existe según la propia documentación del backend, solo falta incluirla en el schema Pydantic de salida. Con eso, el detalle del contrato podría mostrar, junto a cada prenda ya rematada, un link directo al artículo específico en el que se convirtió (en vez de solo el estado "Rematado").

**✅ Resuelto (19/08/2026):** `ContractItemOut` ya trae `inventory_item_id` (`null` mientras la prenda no se remata). Cero migración — la columna y el `UPDATE` que la llena (`auction_contract` → `mark_item_auctioned`) ya existían; solo faltaba incluirla en el `SELECT` del repositorio y en el schema de salida. Ver `docs/API_GUIDE.md` §7. Test de regresión en `tests/integration/test_auction.py` que compara el `inventory_item_id` de cada prenda en la respuesta de `POST /contracts/{id}/auction` contra el valor real en `contract_item` — no solo "no es null", sino que es exactamente el mismo id.
