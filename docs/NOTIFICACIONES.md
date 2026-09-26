# NOTIFICACIONES.md — Avisos por correo al cliente y a la empresa (spec)

> **Estado (25/09/2026, cierre): FASE 5 IMPLEMENTADA en `dev`, sin desplegar** — los recordatorios al cliente R1–R4 tienen productor (un paso nuevo del job), agrupados por cliente y día, todos apagados por defecto; y las preguntas legales quedaron cerradas con el criterio de Mateo (§12.3, orientación, no concepto): **§20**.
>
> **Estado (25/09/2026, noche): FASE 7 IMPLEMENTADA en `dev`, sin desplegar** — las cuatro alertas inmediatas a la empresa (A1–A4) tienen productor, encendidas por catálogo y detrás del interruptor general, que sigue apagado: **§19**.
>
> **Estado (25/09/2026, tarde): FASES 4 y 6 IMPLEMENTADAS en `dev`, sin desplegar** — cada operación de dinero genera su aviso al cliente (C1–C7), todos apagados por defecto: **§18**.
>
> **Estado (25/09/2026): FASES 1, 2 y 3 IMPLEMENTADAS en `dev`, sin desplegar.** La 3 —base legal del cliente, casilla del mostrador, enlace de baja— en **§17**; la 2 en §16. Ningún aviso al cliente está encendido.
>
> **Estado (24/09/2026): FASE 1 IMPLEMENTADA en `dev`, sin desplegar** — maquinaria, catálogo completo, resumen diario/semanal a la empresa y límites de la Ley 2300 como parámetros. Qué quedó, qué no y dónde el código contradijo este documento: **§15**. El párrafo que sigue describe el punto de partida y se deja como estaba.
>
> **Estado original: DISEÑADO, sin una línea de código.** El backend no tenía ningún módulo de correo: cero dependencias (`pyproject.toml` no menciona ninguna librería de email), cero plantillas, cero cola, cero tabla. Todo el correo que sale de la plataforma lo manda **Supabase Auth** con su SMTP compartido, que responde `429 INVITE_RATE_LIMITED` a las pocas invitaciones (`app/modules/identity/auth_admin.py:70`). Se va a migrar a **Resend** sobre `prendo.com.co`.
>
> Pedido por Mateo: *"notificar todo lo que valga la pena — contratos, abonos, ventas, vencimiento de cuota, prórroga, remate, paz y salvo, entre otras cosas — al cliente y a la empresa."*
>
> **Principio de diseño:** un aviso es la **consecuencia** de un hecho que ya quedó registrado, nunca un hecho nuevo. De ahí sale todo lo demás: el aviso no puede hacer fallar la operación que lo originó, no puede perderse sin dejar rastro, y no puede depender de un canal que la mitad de los destinatarios no tiene.
>
> **Verificado contra el código y contra la base dev el 21/09/2026.** Lo que es suposición está marcado como tal.
>
> **Estado de las decisiones — 22/09/2026, contestadas por Mateo.** De las ocho preguntas de negocio que abría §12, **dos quedaron cerradas** y ya no son provisionales:
>
> 1. **No se le avisa al cliente que su prenda está lista para remate.** Textual: *"por el momento no, pero la app debe tener la escalabilidad por si se requiere más adelante"*. El evento nace igual en el catálogo, con destinatario cliente y **deshabilitado**, para que encenderlo sea un cambio de configuración y no una tanda de desarrollo (§2.2, §4.3, §12.0-a).
> 2. **La base legal del correo se distingue por FINALIDAD, no por una casilla de consentimiento genérico.** Un aviso sobre el propio contrato que la persona firmó es servicio del contrato; cualquier otra cosa exige autorización expresa. La base se guarda por cliente y de forma explícita, para que la respuesta de un abogado sea un cambio de configuración y no un rediseño (§9.2, §11, §12.0-b). **Es una recomendación de producto e ingeniería, no asesoría legal** — la salvedad completa está en §9.2-h.
>
> Quedan **seis** preguntas abiertas en §12.

---

## 1. La restricción que manda sobre todo: el cliente no tiene correo

Medido hoy en la base de dev, que tiene datos reales:

| | Clientes | Con `email` | Con `phone` |
|---|---|---|---|
| **LA GRAN LEGAL** (el cliente real) | 5 | **1** | 5 |
| Empresa Demo Front | 3 | 1 | 3 |
| ZZ QA — auditoría 08/09 | 6 | **0** | 6 |
| ZZ QA-B / ZZ repro | 2 | 0 | 2 |
| **Total** | **16** | **2 (12,5 %)** | **16 (100 %)** |

Y no es un descuido de captura: es el esquema. `supabase/migrations/00004_customers_catalogs.sql:18-19`:

```sql
phone  text not null,
email  text,
```

**El celular es obligatorio y el correo no**, porque en una compraventa colombiana el cliente da el celular. Eso no se va a corregir pidiéndole el correo con más insistencia.

> **"No tiene correo" es el caso NORMAL, no la excepción.** Cualquier diseño que asuma lo contrario nace roto: mandaría avisos a 2 de 16 clientes y reportaría éxito.

### 1-bis. La asimetría que sí sirve: la empresa siempre tiene correo

La otra cara del mismo dato, y es la que decide el orden de construcción (§11):

| | Filas | Con correo |
|---|---|---|
| `customer.email` — **nullable** | 16 | 2 (12,5 %) |
| `app_user.email` — **NOT NULL** | 27 | **27 (100 %)** |

`app_user.email` no puede estar vacío porque **es la identidad de Supabase Auth**: sin correo no hay cuenta, no hay JWT, no hay acceso. Así que **el lado empresa del producto es 100 % entregable hoy y el lado cliente no.** Todo lo que se construya para la empresa funciona el primer día; todo lo que se construya para el cliente funciona para el 12 % de la base.

### Las tres consecuencias, resueltas y no esquivadas

**(a) Qué pasa cuando no hay correo: se registra, no se omite.**
El hecho notificable se registra **siempre** (`notification_event`), y el intento de entrega queda en estado `unroutable` — *"había algo que avisar y no había por dónde"*. Ni silencio, ni error. El plan ya lo dice y aplica igual acá: **un correo que no llegó y nadie registró es peor que no mandarlo.** El contador de `unroutable` es, además, el insumo de (c) y la métrica que dice si vale la pena seguir invirtiendo en el canal correo.

**(b) El evento y el canal son cosas separadas.**
Dos tablas, no una (§4): el **evento** es qué pasó y a quién le importa; la **entrega** es un intento por un canal concreto. WhatsApp —que en Colombia es el canal real para el cliente— entra después como filas de entrega con `channel = 'whatsapp'` sobre los mismos eventos, sin tocar quién los produce ni cuándo. **No se construye WhatsApp acá, pero la puerta queda abierta por construcción y no por buena voluntad.**

**(c) Cómo se captura el correo sin volverlo obligatorio.**
Obligarlo bloquearía el mostrador, y además no funcionaría: quien no tiene correo pondría `a@a.com`. Tres cosas, ninguna bloqueante:

| Dónde | Qué |
|---|---|
| `POST /customers` | El correo **sigue siendo opcional**. No cambia |
| Al **crear un contrato** | Si el cliente no tiene correo, la pantalla ofrece pedirlo ahí: *"¿quiere recibir avisos de su cuota por correo? (opcional)"* + casilla de autorización. Es el único momento en que el cliente tiene un motivo propio para decir sí — acaba de recibir plata y tiene una fecha de pago que no quiere olvidar. Pedirlo al registrar la ficha es pedirlo cuando a él no le sirve de nada |
| Lista **"clientes sin correo"** | Derivada de los `unroutable`, para el rato muerto del mostrador. Es trabajo que se puede hacer o no; no es un formulario que traba una venta |

> **Defecto encontrado de paso (§13): el backend no valida el formato del correo del cliente.** `app/modules/customers/schemas.py:17` declara `email: str | None` pelado, mientras `identity/schemas.py:17` sí usa `EmailStr`. La validación existe **solo en el frontend** (`CustomerFormDialog.tsx:26`, con `zod`). Cualquier otro cliente de la API escribe `juan@gmial,com` sin resistencia — y ese correo es exactamente el que rebota, o peor, el que le llega a un tercero (§9).

---

## 2. Catálogo de eventos

Dos familias, y se separan porque **el disparador y la idempotencia son distintos**:

- **Transaccional** — *pasó algo, te aviso*. Lo dispara la acción del usuario, dentro de la transacción que ya registra el documento. Su llave de deduplicación **es el documento**: existe y es único.
- **Recordatorio por fecha** — *falta X para tu cuota*. Lo dispara el job nocturno. No hay documento nuevo: la llave hay que **construirla** (§6), y ahí es donde se manda dos veces.

Leyenda de **urgencia**: `inmediata` = se intenta al terminar la operación, con el job como red; `diaria` = solo el job.

### 2.1 · Transaccional — al cliente

| # | Evento | Disparador | Destinatario | Urgencia | Sin correo | Sensible |
|---|---|---|---|---|---|---|
| C1 | **Contrato creado** — número, monto, fecha de la próxima cuota | `POST /contracts` (`create_contract`) | Cliente | inmediata | `unroutable` + la pantalla ofrece pedirlo | Monto **sí**; prenda **no** |
| C2 | **Abono registrado** — qué pagó, hasta cuándo quedó cubierto, saldo | `POST /contracts/{id}/payments` (`create_payment`) | Cliente | inmediata | `unroutable` | Monto |
| C3 | **Paz y salvo** — el contrato quedó saldado | el mismo abono, cuando deja `status='paid'` | Cliente | inmediata | `unroutable` | Monto |
| C4 | **Préstamo ampliado** — nace un contrato sucesor | `POST /contracts/{id}/extend-loan` (`extend_loan`) | Cliente | inmediata | `unroutable` | Monto |
| C5 | **Nota crédito emitida** — tiene saldo a favor | `POST /sales/{id}/returns` que liquida en nota (`create_return`) | Cliente | inmediata | `unroutable` | Monto |
| C6 | **Comprobante de venta** | `POST /sales` (`create_sale`) **con** `customer_id` | Cliente | inmediata | `unroutable` | Monto; artículos **no** |
| C7 | **Venta anulada / devolución** | `void_sale` · `create_return` | Cliente | inmediata | `unroutable` | Monto |

**Por qué C3 es el que más vale para el cliente.** Es el único correo de esta lista que el cliente *quiere guardar*: es la prueba de que no le deben nada. Hoy el paz y salvo existe solo como impreso (`GET /contracts/{id}/settlement`, que exige `status='paid'` literal — `service.py:516`) y se pierde en cuanto el papel se pierde.

**Por qué C4 no es opcional.** `extend_loan` **no modifica el contrato: lo sucede** (`docs/RECARGOS.md` §4-bis). El viejo queda `superseded` y nace otro con número propio. El cliente se va del mostrador con un papel nuevo, pero si vuelve con el viejo nadie le va a aceptar un abono contra él: el proyecto ya aprendió esto y por eso `CONTRACT_SUPERSEDED` **nombra el contrato sucesor** en `details` en vez de decir "está cerrado" a secas. El correo tiene que hacer lo mismo: **nombrar los dos números**, y decir que la fecha de cobro no se movió (que es justo lo que `00053` se propuso garantizar y el cliente no tiene forma de saber).

**C6/C7 casi no tienen destinatario.** En ventas el cliente es **opcional** (`CLAUDE.md` → Ventas). Una venta de mostrador sin cliente no tiene a quién avisarle, y eso no es un hueco: es el negocio.

### 2.2 · Recordatorio por fecha — al cliente

La fecha de la próxima cuota **no necesita cálculo nuevo**: es `rules.add_months(interest_paid_until, 1)`. El cliente está al día hasta ahí, por definición de `months_owed = months_between(interest_paid_until, today)` (`app/modules/contracts/rules.py`). Reusar esa función y no escribir otra es obligatorio: dos formas de calcular la misma fecha terminan divergiendo, y este proyecto ya pagó eso dos veces con el día de la empresa.

| # | Evento | Cuándo lo decide el job | Destinatario | Urgencia | Sin correo | Sensible |
|---|---|---|---|---|---|---|
| R1 | **Cuota por vencer** | `add_months(interest_paid_until,1)` cae en 3 días (parámetro, §5) | Cliente | diaria | `unroutable` | Monto |
| R2 | **Cuota vencida** | `months_owed` pasó de 0 a ≥1 → el contrato entró en `in_arrears` | Cliente | diaria | `unroutable` | Monto |
| R3 | **Entró en prórroga** | `compute_status` lo puso en `in_extension` | Cliente | diaria | `unroutable` | Monto |
| R4 | **La prórroga vence pronto** | `extension_ends_at` cae en N días | Cliente | diaria | `unroutable` | Monto |
| R5 | **Listo para remate** | `in_extension` **y** `extension_ends_at` ya pasó | **Empresa** (§2.4, E1). Al cliente: el evento existe en el catálogo y nace **deshabilitado** — ver abajo y §12.0-a | diaria | — | — |

> **R3 es el aviso más valioso de todo el documento y el más fácil de pasar por alto.** `in_extension` es la última campana antes de que la prenda se pueda rematar, y **se dispara sola**, sin que nadie toque nada: `compute_status` lo pone cuando `months_owed` llega a `arrears_window_months` (4 en metales, 1 en tecnología). Hoy el cliente no se entera de que su contrato cambió de estado; se entera cuando viene a pagar y le dicen que su cadena ya no está.

**«Listo para remate» no es un `status`.** Es `in_extension` con `extension_ends_at` ya pasado — exactamente el predicado de `GET /contracts/ready-for-auction`. Cualquier consulta de este documento que lo trate como un estado del enum está mal.

#### R5 al cliente — decidido el 22/09/2026: no hoy, y por eso mismo el evento existe

Mateo: *"por el momento no, pero la app debe tener la escalabilidad por si se requiere más adelante"*. Eso **confirma** lo que la tabla ya proponía —el aviso de remate va a la empresa (E1), no al cliente— y le quita lo provisional. Pero agrega un requisito de diseño que pesa más que la decisión misma: **encenderlo después tiene que ser un cambio de configuración, no una tanda de desarrollo.** Tres cosas que sí se cierran acá —(a), (b) y (c)— y una cuarta, (d), que queda abierta a propósito.

**(a) El evento existe en el catálogo desde el día uno, con destinatario cliente, y nace deshabilitado.** `auction_ready_customer`, `audience='customer'`, `purpose='service'` (§9.2), `default_enabled = false`. **No es un evento que "se agregará": es uno que está y no se dispara.** La diferencia es concreta y verificable: el tipo está en el catálogo, tiene plantilla escrita, tiene `dedupe_key` (`auction_ready:<contract_id>:<extension_ends_at>` — anclada al ancla del contrato, como todas las de estado, §6.1) y tiene sus dos tests (§14). Lo único que falta el día que se encienda es el valor de un `settings`.

**Por qué esto no es sobre-ingeniería, que es la objeción obvia.** El tercer paso del job ya recorre **exactamente** esa población para producir E1: el predicado de `ready-for-auction` se evalúa igual haya o no aviso al cliente. El evento al cliente no agrega una consulta, agrega un destinatario a una consulta que ya se hace. Dejarlo escrito y apagado cuesta una plantilla y un test; agregarlo después cuesta tocar catálogo, job, plantillas y tests con el sistema ya andando y con clientes reales del otro lado.

**(b) El interruptor vive en `company.settings.notifications.events.auction_ready_customer` — una preferencia por empresa, no un permiso.** Es la excepción razonada al precedente de `RECARGOS.md` §8.1, y la justificación está en §4.3, donde vive el resto de la jerarquía de preferencias.

**(c) Lo que queda escrito para el día que se encienda, porque quien lo encienda va a asumir algo sin saberlo.** El argumento que frenó la decisión no es de producto, es legal: **avisar que un bien se va a rematar tiene peso en Colombia**, y hacerlo por un correo cuya entrega no se puede probar deja a la compraventa diciendo *"le avisamos"* sin poder demostrarlo. Un `delivered` de Resend prueba que un servidor aceptó el mensaje; no prueba que el titular se enteró — y esa distinción es justo la que se discutiría. Se agrega un segundo problema, propio de este producto: con 14 de 16 clientes sin correo (§1), el aviso existiría para unos pocos y para la mayoría no, y esa desigualdad es difícil de sostener si alguien la mira de cerca.

| Para que ese argumento deje de aplicar, haría falta | Por qué |
|---|---|
| **Registrar la entrega de forma probatoria** — un canal con acuse verificable y la constancia guardada, no solo el estado del envío | Es lo que convierte *"le avisamos"* en algo que se puede mostrar. El `provider_id` de `notification_delivery` (§4.1) es el gancho donde colgaría esa constancia, pero **por sí solo no es prueba de entrega al titular** |
| **Que el aviso no sustituya a lo que el contrato firmado ya diga** | Si el papel fija una forma de avisar, el correo es un extra y no puede contradecirla. Eso se lee en el contrato del inquilino, no en este documento |
| **Concepto de un abogado** sobre si un aviso mandado y no probado mejora o empeora la posición de la compraventa | Es la pregunta que este documento no puede contestar, y la razón por la que el evento nace apagado en vez de encendido |

> **Quien encienda esta casilla está asumiendo que un correo sin prueba de entrega alcanza como aviso de remate.** Queda dicho acá y no en una conversación: el interruptor es fácil, la consecuencia no. La pantalla que lo enciende tiene que mostrar este texto, igual que la de §4.3 muestra cuántos correos van a salir.

**(d) La misma pregunta para R3 (prórroga) — y esta NO se puede cerrar.** R3 sigue encendido y mandándose al cliente, porque **es criterio propio, no concepto**, que no es lo mismo: R3 informa un **cambio de estado del propio contrato** —*"entró en prórroga"*—, mientras R5 anuncia que **la prenda se va a disponer**. El primero es información que el cliente hoy no tiene y que le sirve para pagar; el segundo es el acto. Pero la frontera entre informar un estado y anunciar una consecuencia patrimonial **la pone un abogado, no este documento**, y por eso **queda numerada como la §12.1-7**, aunque no sea una de las ocho originales: es el pedazo que la decisión de Mateo no alcanzó a cubrir, y va al mismo abogado en la misma consulta que (a). Lleva número, y no un recuadro al margen, porque una pregunta abierta escondida dentro de una decisión que dice «cerrada» es una pregunta que nadie vuelve a hacer.

**Y si la respuesta fuera que R3 pesa igual, no hay rediseño:** R3 ya es una entrada del catálogo y el mismo interruptor de (b) lo apaga. Esa es la prueba de que el mecanismo generaliza — no se construyó para el remate, se construyó para cualquier evento cuya respuesta legal todavía no está.

### 2.3 · Agrupación: el recordatorio es **por cliente y por día**, no por contrato

Esta es la decisión que los números de la base obligan, y no es una optimización: es el diseño.

Medido hoy — contratos **vivos** (`active` · `in_arrears` · `in_extension`) por cliente:

| Empresa | Clientes con contrato vivo | Contratos vivos | El peor caso |
|---|---|---|---|
| LA GRAN LEGAL | 5 | 22 | **6 contratos** en un solo cliente |
| Empresa Demo Front | 2 | 15 | **13 contratos** en un solo cliente |
| ZZ QA — auditoría 08/09 | 3 | 8 | 4 |
| **Total base dev** | **12** | **49** | |

Un recordatorio por contrato le manda **13 correos en una noche** a la misma persona. Eso no es un recordatorio: es lo que hace que bloquee el remitente y de paso queme la reputación de `prendo.com.co` para los otros inquilinos (§8).

**Decidido:** un evento de recordatorio es por **(cliente, día, tipo)** y su cuerpo lista todos los contratos afectados. Efecto lateral que importa para §10: el volumen del inquilino deja de ser *contratos × puntos de aviso* y pasa a ser *clientes × días* — de 22 a 5 en LA GRAN LEGAL.

Los transaccionales **no** se agrupan: cada uno es el acuse de un hecho puntual que el cliente acaba de vivir, y juntar dos abonos en un correo los vuelve ilegibles.

### 2.4 · A la empresa — el resumen diario

Un solo correo al día por empresa, con secciones. **No es un correo por evento**, y el porqué está en §3.

| # | Sección | De dónde sale | Urgencia |
|---|---|---|---|
| E1 | **Contratos listos para remate** | el predicado de `ready-for-auction` | diaria |
| E2 | **Entraron en mora anoche** / **entraron en prórroga anoche** | el delta que escribió `recompute_all_statuses` | diaria |
| E3 | **La caja de ayer no se cerró** | no hay `cash_session` cerrada del día anterior | diaria |
| E4 | **Descuadre de arqueo** por encima de un umbral | `cash_movement` tipo `adjustment` del cierre | diaria |
| E5 | **Cuentas por pagar vencidas** | `GET /reports/payables` | diaria |
| E6 | **Cuentas `settlement` sin liquidar** hace N días | `account` tipo `settlement` con saldo | diaria |
| E7 | **Mercancía sin rotación** | `GET /reports/stale-inventory` | **semanal** — nada rota en un día |
| E8 | **Su suscripción vence en 15 / 7 / 1 días** | `subscription.expires_at` | diaria |

**E1 es el primer envío que hay que construir (§11), y este es el dato que lo prueba:** hoy mismo, en dev, hay **8 contratos** que cumplen el predicado de `ready-for-auction`. Son prendas que ya se pueden rematar y plata inmovilizada, y nadie las está mirando porque hay que entrar a una pantalla a buscarlas.

**E8 cierra un agujero real.** `expire_overdue_subscriptions` corta el acceso en seco: en cuanto el status deja de ser `active`, `get_current_user` responde `402 SUBSCRIPTION_EXPIRED`. El job **sí** audita ese cambio (`platform/service.py:415-436`, con `user_id=None`) y escribe un `subscription_event` — pero **nadie le avisó antes al dueño**. Se encuentra la app cerrada un lunes por la mañana. Hoy hay 2 suscripciones `expired` y 5 `active` en la base.

### 2.5 · A la empresa — inmediato, y son muy pocos

La excepción al resumen diario. Cuatro actos, y el criterio para que estén acá es objetivo: **son exactamente los que el proyecto ya decidió que necesitan permiso especial, motivo obligatorio y fila de auditoría.**

| # | Evento | Endpoint / acción | A quién |
|---|---|---|---|
| A1 | **Venta anulada** | `void_sale` | quien tenga `notifications.receive_alerts` |
| A2 | **Descuento** por encima de un umbral | `apply_sale_discount` · `apply_payment_discount` | ídem |
| A3 | **Retiro de capital del dueño** | `POST /capital/withdrawals` | ídem |
| A4 | **Caja reabierta** | `reopen_session` | ídem |

**Por qué estos cuatro y no los otros 48.** Los cuatro ya están en `audit_log`, y una auditoría que nadie lee no es un control: es un archivo. El valor no está en el aviso, está en que llegue **el mismo día** a alguien que puede preguntar. Son además de volumen bajísimo por naturaleza — si A1 se vuelve frecuente, el problema no es el correo.

### 2.6 · De la plataforma — no del inquilino

| # | Evento | Estado hoy |
|---|---|---|
| P1 | **Invitación de usuario** | ~~Lo manda Supabase Auth~~ **Migrada a Resend en la fase 2 (24/09/2026, §16).** Supabase queda de respaldo si la plataforma no tiene proveedor |
| P2 | **Enlace de acceso** (`generate_recovery_link`) | **Se queda como está: se pasa a mano, por WhatsApp.** Y no es pereza — ver §9.3 |

---

## 3. Qué NO se notifica, y por qué

Esta sección vale tanto como el catálogo. Un sistema que manda demasiado se ignora, y un cliente que recibe cinco correos al día bloquea el remitente — y se lleva puesta la reputación del dominio para los otros inquilinos.

### La regla que elimina 40 de los 52 endpoints de una sola vez

Hay **52 endpoints que mutan datos** hoy (contados con `grep '@router.(post|patch|put|delete)'` sobre `app/modules/*/router.py` el 21/09/2026 — la auditoría de QA cita 47, la diferencia son los agregados después). Y el catálogo de `audit_log` tiene **~50 acciones** (`frontend-starter/src/features/audit/labels.ts`). Casi ninguna merece un correo:

> **Un hecho cuyo destinatario es la persona que acaba de hacer clic no es un correo.** Es una pantalla.

El cajero que registró el abono ya vio el recibo. El bodeguero que publicó el artículo ya vio el código. Mandarles un correo de lo que acaban de hacer es ruido con acuse de recibo.

### La lista explícita

| Qué | Por qué no |
|---|---|
| **Todo el módulo de inventario** — `create_entry`, `pay_entry`, `create_exit`, `publish_item`, `update_product`, `create_transformation` | Movimientos internos. Nadie de afuera espera nada, y el de adentro lo acaba de hacer. Lo que sí importa —mercancía quieta— es **E7**, y es un resumen, no un evento |
| **Todo `catalogs`** — categorías, proveedores | Configuración. Va a `audit_log` y ahí se queda |
| **`open_session` / `close_session`** | Pasa todos los días. Un correo diario que siempre dice lo mismo entrena a la gente a no abrirlo, y el día que diga algo importante (**E3**: *no* se cerró) ya nadie lo abre. Se notifica la **ausencia**, no el hecho |
| **`create_customer` / `update_customer`** | *"Registramos tu ficha"* no le sirve a nadie y encima le confirma a un tercero que esa cédula está en una casa de empeño |
| **Roles, permisos, plantillas de documento, configuración** | Actos de administración. El admin los hizo hace diez segundos |
| **Un correo por venta a la empresa** | Medido: **13 ventas en septiembre**, menos de una por día. Un correo por venta se lee la primera semana y se filtra la segunda. Va al resumen |
| **`import_contract`** | Es carga de datos históricos. Avisarle al cliente de un contrato que ya tenía es confuso, y avisar de una migración de 200 contratos es una tanda de 200 correos sobre nada |
| **`correct_contract_status`** | Es una reparación de datos (`scripts/qa/reparar_f21_10.sql`). Su `user_id` va NULL porque no lo hizo un usuario de la empresa. Contarle al cliente que le arreglamos un estado es abrir una conversación que no tiene final feliz |
| **`expire_subscription`** (el hecho) | Cuando llega, el dueño ya no puede entrar: el correo llega tarde por construcción. Lo que sirve es **E8**, el aviso **antes** |

### Y un límite duro, por cliente y por día

**Máximo 1 recordatorio por cliente por día** (§2.3) y **máximo 3 correos por cliente por día** contando transaccionales. Pasado eso, el evento se registra y la entrega queda `throttled`. Por qué existe el tope: sin él, un cliente con 13 contratos que hace 3 abonos el mismo día recibe 16 correos, y no hay ninguna redacción que lo haga parecer intencional.

---

## 4. Modelo de datos

### 4.1 · Dos tablas: el evento y la entrega

```sql
-- EL HECHO. Canal-agnóstico. Se escribe SIEMPRE, incluso sin por dónde avisar.
create table public.notification_event (
  id            uuid primary key default gen_random_uuid(),
  company_id    uuid not null references public.company(id),
  event_type    text not null,              -- 'contract_created', 'installment_due_soon', ...
  audience      text not null,              -- 'customer' | 'company' | 'platform'
  customer_id   uuid references public.customer(id),   -- audience='customer'
  entity_type   text,                       -- mismo vocabulario que audit_log
  entity_id     uuid,
  payload       jsonb not null,             -- lo MÍNIMO para redactar (§9.1)
  dedupe_key    text not null,              -- construida, nunca aleatoria (§6)
  occurred_on   date not null,              -- el día de la EMPRESA, no UTC
  created_at    timestamptz not null default now(),
  unique (company_id, dedupe_key)
);

-- EL INTENTO, por canal y destinatario. Varias por evento.
create table public.notification_delivery (
  id            uuid primary key default gen_random_uuid(),
  company_id    uuid not null references public.company(id),
  event_id      uuid not null references public.notification_event(id),
  channel       text not null,              -- 'email' hoy; 'whatsapp' después
  to_address    text,                       -- null cuando es unroutable
  status        text not null,              -- ver §4.2
  attempts      int not null default 0,
  last_error    text,
  provider_id   text,                       -- el id de Resend, para cruzar con su panel
  scheduled_at  timestamptz,
  sent_at       timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
```

**Por qué dos tablas y no una con una columna `channel`.** Es el patrón que este proyecto ya usa cuatro veces: **el documento guarda el hecho, las filas hijas guardan sus efectos.** `contract` + `cash_movement`; `credit_note` + `credit_note_redemption` (`00043`); `sale_return` + sus líneas; `capital_movement` con su movimiento de caja. Acá compra tres cosas concretas:

1. **La idempotencia es del hecho, no del canal.** *"¿ya se le avisó de esta cuota?"* se responde con una fila, no con un `group by`. Con una sola tabla, el `unique` tendría que incluir el canal, y el día que exista WhatsApp la pregunta dejaría de tener respuesta única.
2. **`unroutable` deja de ser una ausencia.** Es una fila con `to_address = null`, que se cuenta y se lista (§1c). Con una sola tabla, "no había correo" sería *no hay fila* — indistinguible de *el job no corrió*, que es el error que costó doce días en F21-10.
3. **WhatsApp es un `insert`, no una migración.** Un canal nuevo agrega filas de entrega sobre eventos que ya existen. Nada de lo que produce eventos se toca.

**Por qué `occurred_on` es `date` y no se deriva de `created_at`.** Literalmente el argumento de `00053` para `extended_on`: `created_at` es `timestamptz` y el "día" del negocio es el de la zona de la **empresa**. Convertirlo en cada lectura es el cálculo que ya costó el bug de las 5 horas **dos veces** en este proyecto (Fly corre en UTC; Colombia es UTC-5 sin horario de verano — `ARCHITECTURE.md` §10).

**RLS:** las dos tablas llevan `company_id`, `enable`+`force row level security` y la política `tenant_isolation` de siempre, más su test en `tests/rls/`. Los eventos `audience='platform'` son el caso incómodo —una invitación pertenece a la empresa pero la manda la plataforma— y se resuelven como ya se resuelve todo lo de plataforma: se escriben y se leen con la sesión de bypass, con `company_id` puesto.

### 4.2 · Estados de una entrega

```
                    ┌─→ unroutable   (no hay dirección para ese canal)      TERMINAL
                    ├─→ suppressed   (sin consentimiento, opt-out, o correo inválido)  TERMINAL
                    ├─→ throttled    (superó el tope de §3)                  TERMINAL
  (evento creado) ──┼─→ skipped_stale (el hecho es demasiado viejo, §5)      TERMINAL
                    └─→ pending ──→ sending ──→ sent ──→ delivered           TERMINAL
                                       │          └────→ bounced             TERMINAL
                                       └─→ failed (reintentable) ──→ pending
                                                                └─→ dead     TERMINAL
```

**Cinco terminales que no son `sent` y ninguno es un error.** Esa es la parte que importa: la mayoría de los desenlaces de este sistema son *"no se mandó, y está bien"*. Un diseño con solo `sent`/`failed` los colapsa en fracaso y produce un tablero rojo que nadie mira.

| Estado | Qué significa | ¿Falla ruidosa o silenciosa? |
|---|---|---|
| `unroutable` | El caso **normal** (§1) | **Ruidosa a propósito:** alimenta la lista de clientes sin correo |
| `suppressed` | La base legal del cliente no alcanza para la finalidad de ese evento (§9.2), pidió la baja, o `email_invalid_at` puesta | Ruidosa en el agregado, invisible por fila. **Es el contador que hay que mirar el día que cambie el mapa de §9.2-d** |
| `throttled` | Tope de §3 | Silenciosa; solo importa si sube |
| `skipped_stale` | El job estuvo caído y el hecho ya no es noticia (§5) | **La alarma más importante del sistema.** Un `skipped_stale > 0` es la señal que nadie tuvo cuando la Machine desapareció 12 días |
| `dead` | 3 intentos y no salió | **Ruidosa:** entra al resumen de la empresa |
| `bounced` | Rebotó duro | Ruidosa una vez, y marca la dirección (§7) |

### 4.3 · Preferencias: cuatro niveles, cuatro preguntas distintas

No se colapsan porque **no son la misma pregunta**, y unificarlas es lo que produce la casilla que nadie sabe contestar — el mismo error que `RECARGOS.md` §8.1 ya descartó para el LTV. El cuarto nivel lo agregó la decisión del 22/09 sobre el aviso de remate (§2.2).

| Nivel | Pregunta que contesta | Dónde vive | Default |
|---|---|---|---|
| **Empresa** | ¿Este negocio le escribe a sus clientes? | `company.settings.notifications` (jsonb) | **Apagado** |
| **Evento** | ¿Este aviso en particular está encendido para esta empresa? | `company.settings.notifications.events.<event_type>`, sobre el `default_enabled` del catálogo | El del catálogo. Hoy **solo `auction_ready_customer` nace en `false`**; el resto en `true` |
| **Usuario** | ¿A qué empleados les llega el resumen de la empresa? | **un permiso**, no una columna | Solo Admin |
| **Cliente** | ¿Con qué base legal se le escribe, y para qué finalidad? | `customer.email_basis` (+ `email_consent_at`, `email_opt_out_at`) cruzado con el `purpose` del evento (§9.2) | `contract` si tiene contrato vivo y correo; nulo = no sale nada |

**Por qué apagado por defecto en la empresa.** Encenderlo para un inquilino existente dispara la tanda de arranque: LA GRAN LEGAL tiene 22 contratos vivos y 8 contratos ya listos para remate. El primer día mandaría avisos sobre hechos de hace semanas. Es el mismo problema de §5, y se resuelve con la misma regla, pero el interruptor apagado es la primera línea de defensa. **Encender es un acto explícito, con una pantalla que dice cuántos correos van a salir.**

**Por qué el nivel evento es una preferencia por empresa y NO un permiso — la excepción razonada al precedente.** `RECARGOS.md` §8.1 descartó una casilla por empresa para el cupo de ampliación y usó un permiso, con tres argumentos. Hay que mirarlos uno por uno antes de copiar la conclusión, porque **dos de los tres no aplican acá**:

| Argumento de `RECARGOS.md` §8.1 | ¿Aplica al aviso de remate? |
|---|---|
| *"Nadie sabe responder eso al dar de alta una empresa"* | **No aplica: acá no se pregunta.** La casilla no está en el alta. Nace en `false` porque la plataforma ya tomó la decisión por defecto, y quien la cambie lo hace después, con el negocio andando y un motivo. Una preferencia que nadie tiene que contestar para empezar a operar no es la casilla que ese argumento condena |
| *"La misma regla se comportaría distinto en dos pantallas"* | **No aplica: hay una sola.** El LTV se evalúa al crear un contrato **y** al ampliarlo — dos superficies que podían divergir. Este evento lo produce **únicamente** el tercer paso del job nocturno (§5.2). Un solo punto de evaluación, como exige §14 para el tope por cliente |
| *"Parte el producto en dos comportamientos que hay que documentar, soportar y testear"* | **Sí aplica, y es el costo que se paga.** Por eso §14 exige probar las dos ramas, encendida y apagada. Es barato porque la rama vive en un solo lugar: el evento se crea igual, lo que cambia es si la entrega nace `pending` o no se crea |

**Y el argumento positivo, que es el que decide:** un permiso contesta *"¿qué empleado puede hacer X?"*. Acá **ningún empleado hace nada** — el correo lo manda el job, sin `user_id`, como ya pasa con `expire_subscription` (§7). Colgar un permiso de un actor que no existe es un error de categoría: habría que inventar a quién asignárselo. La pregunta real es *"¿esta compraventa le avisa a sus clientes que va a rematar?"*, y es **una decisión legal del negocio**, no un privilegio de un usuario: la contesta el dueño con su abogado, vale para toda la empresa y no cambia según quién esté en el mostrador. Cambiarla es un acto de configuración, ya auditado por `update_settings` (§7) y ya protegido por `company.configure`.

**Por qué es un mapa por evento y no una columna `auction_notice_enabled`.** Porque el problema se va a repetir. La forma —catálogo con `default_enabled`, override por empresa— sirve para el próximo aviso cuya respuesta legal todavía no está, sin una migración por cada uno. Una columna dedicada resuelve el caso de hoy y obliga a otra el día que aparezca el segundo. Es un SaaS: la bifurcación se abstrae, no se hornea.

**Por qué el nivel usuario es un permiso y no una preferencia.** Quién recibe el correo de *"descuadre de caja de $180.000"* es **la misma pregunta** que quién puede ver el reporte de caja, y este proyecto ya tiene una forma para eso: RBAC. Una columna `wants_digest` en `app_user` deja que un usuario de Bodega se suscriba a los números del negocio sin pasar por ningún rol — un permiso de lectura por la puerta de atrás. Dos permisos nuevos, porque no son la misma decisión:

| Permiso | Qué autoriza |
|---|---|
| `notifications.receive_digest` | Recibir el resumen diario (§2.4) |
| `notifications.receive_alerts` | Recibir las alertas inmediatas (§2.5) — anulaciones, descuentos, retiros del dueño, reapertura de caja |

**`company.contact_email` no es el destinatario del resumen.** Existe (`00002_platform.sql:16`, nullable) y su lugar es el `Reply-To` (§8), no la bandeja del dueño: es un buzón de contacto, no una persona con permisos. Mandar los números del negocio ahí es mandarlos a quien sea que lo lea.

> **Trampa: no reusar `grace_days`.** `company.settings` trae `grace_days: 30` desde `00002` y **ningún código lo lee** — verificado con grep: solo aparece en la migración y en un comentario de `company/service.py:72`. Es configuración muerta, y es tentadora como "días de antelación del aviso". **No.** Su nombre promete gracia de mora; usarla para otra cosa deja un campo que significa dos cosas según quién lo lea. El parámetro de antelación va nuevo y con nombre propio dentro de `settings.notifications`.

### 4.4 · Plantillas: **no** reusan `document_template`, y el porqué es de gobierno

El precedente existe y es bueno: `document_template` (`00046`) guarda el cuerpo completo de los documentos imprimibles como JSON estructurado, editable por cualquiera con `company.configure`, con una sola plantilla activa por `(empresa, tipo)` y tres formatos visuales (`00047`).

**Decidido: las plantillas de correo viven en el repositorio, en código, y no son editables por el inquilino.** Tres razones, en orden de peso:

1. **La entregabilidad es un recurso compartido que no se puede particionar.** Hay **un solo dominio** (§8). Si un inquilino puede escribir el cuerpo, puede escribir *"haga clic acá para verificar su cuenta"* sobre la reputación de `prendo.com.co`, y el spam de uno bloquea el correo de los otros treinta. Es la misma forma del argumento que decide el remitente: **un solo dominio ⇒ el gobierno del correo es de la plataforma.**
2. **`document_template` es un documento del inquilino; un correo es un envío de la plataforma.** El contrato de empeño lo imprime la compraventa, lo firma su cliente y lo ve una persona. Un correo sale del dominio de la plataforma hacia un tercero. No es la misma superficie, y por eso tampoco alcanza el permiso `company.configure` que `00046` reusó con buen criterio para sí mismo.
3. **Razón técnica, y sola ya bastaría:** el `body` de `document_template` es ProseMirror/Tiptap y **lo renderiza el frontend**. Un correo se renderiza en el servidor, en Python. Reusar la tabla obliga a escribir un segundo renderer del mismo JSON en otro lenguaje, y los dos van a divergir — es exactamente la forma del defecto que este proyecto ya persigue (una regla escrita en dos lugares).

**Qué sí es del inquilino, sin tocar el cuerpo:** su nombre (`company.name` / `legal_name`), su logo (`logo_url`), su teléfono (`contact_phone`), su `contact_email` como `Reply-To`, y el `footer_note` / `legal_notice` que **ya existen** en `company.settings.documents` (`company/service.py:41-44`). Eso cubre el pedido real —*"que se vea de mi negocio"*— sin entregar la redacción.

**La puerta que queda abierta, por si acaso:** `document_type` es un enum extensible y `00046` ya documenta cómo (`alter type document_type add value if not exists 'receipt'`). El día que un inquilino de verdad necesite su propia redacción, `'notification_email'` cabe ahí — pero entonces hace falta **revisión antes de activar**, y eso es un producto con cola de aprobación, no una fila en una tabla. No se construye hoy.

---

## 5. El disparo: quién dispara qué, y qué pasa si el job no corrió

### 5.1 · Transaccional: la fila va en la transacción, el envío no

**`CLAUDE.md` regla 4: una operación de negocio = UNA transacción.** Un `POST` a Resend dentro de esa transacción la deja abierta esperando a un tercero por la red, y un proveedor de correo lento haría **fallar el registro de un abono**. Eso es inaceptable y decide el diseño:

| Paso | Dónde |
|---|---|
| 1. `insert` en `notification_event` + `notification_delivery(status='pending')` | **Dentro** de la transacción del documento |
| 2. El envío HTTP a Resend | **Fuera**, en un `BackgroundTasks` de FastAPI, después del commit |
| 3. Si el paso 2 no ocurrió o falló | La fila sigue `pending` y **el job nocturno la barre** |

**Que la fila vaya dentro de la transacción no es un detalle: es la razón de que sea una fila y no una llamada a una cola.** Si el abono se revierte, el aviso se revierte con él. Un aviso de un abono que no existe es peor que ningún aviso.

**El costo, dicho en voz alta:** en `dev` el paso 2 es **poco confiable por configuración**, no por bug. `fly.dev.toml` usa `auto_stop_machines=true` + `min_machines_running=0` (`ARCHITECTURE.md` §8): la máquina se puede apagar justo después de responder y llevarse el `BackgroundTask` puesto. Está bien, y es exactamente por eso que el paso 3 existe: **la garantía la da el job, el `BackgroundTasks` solo da la velocidad.** Un paz y salvo puede llegar hasta 24 h tarde en el peor caso. En `prod` (`min_machines_running=1`) el peor caso es mucho más raro, pero el diseño no depende de eso.

### 5.2 · Recordatorios: el job nocturno, con un tercer paso

`app/jobs/nightly.py` hace hoy dos pasos, cada uno en su propia transacción de bypass para que la falla de uno no revierta el otro. Se agrega un **tercer paso**, con la misma forma, y va **después** de `recompute_all_statuses`: los eventos R2/R3 son el **delta** que ese paso acaba de escribir. Invertirlos manda los avisos de estado con un día de retraso.

### 5.3 · Si el job no corrió: la ventana de rezago

**Ya pasó, y es el antecedente más importante de este documento.** La Machine `nightly-job` de dev **desapareció entre el 27/08 y el 08/09/2026 y nadie se enteró** (`ARCHITECTURE.md` §11). Y volvió a romperse distinto: entre el 10/09 y el 21/09 quedó clavada a una imagen vieja y **resucitó 4 contratos ya reemplazados**, el 100 % de las ampliaciones que existían (F21-10, `docs/QA_AUDITORIA.md`).

Aplicado a los correos, un job que vuelve después de doce días muertos manda doce días de avisos de golpe. Con los números de hoy: 8 avisos de remate sobre prórrogas vencidas hace semanas, más los recordatorios de cuotas que ya pasaron. Una tanda así en la primera semana de vida es cómo se quema un dominio.

**Decidido: un recordatorio cuya fecha objetivo quedó más de `stale_after_days` en el pasado no se manda — se registra.** Evento creado, entrega en `skipped_stale`.

| Por qué | |
|---|---|
| **Un recordatorio atrasado no es un recordatorio** | "Su cuota vence en 3 días" mandado 12 días después es desinformación, no un aviso tarde |
| **Evita la estampida** | Que es el mecanismo concreto por el que un dominio nuevo entra en listas negras |
| **Deja el rastro que no existía** | `skipped_stale > 0` es una alarma con fecha y volumen. En F21-10 la evidencia de que el job llevaba días sin correr hubo que **deducirla** de que `subscription_event` no tenía ni una fila `expired` en toda la historia de la base |

**Y de regalo, el latido que `ARCHITECTURE.md` §11 dice que falta.** Hoy: *"su ausencia es silenciosa. No hay health check ni alerta"*, y para saber si el job vive hay que preguntarle a Fly (`verificar_job_nocturno.py`, que necesita `FLY_API_TOKEN` y corre desde afuera). Con esto, **"¿corrió anoche?" se responde desde la base**: `select max(occurred_on) from notification_event`. No reemplaza al guardián —que vigila la causa (que la Machine exista, conserve su `schedule` y tenga la imagen del release actual) y no el daño— pero es la primera señal que vive **dentro** del perímetro que ya tiene la base, sin exportar credenciales a un tercero. Es justo lo que F21-10 dejó anotado y sin hacer para `verificar_cadenas.py`.

Los **transaccionales no tienen ventana de rezago**: un paz y salvo de hace una semana sigue sirviendo. Solo se saltan los recordatorios, porque son los únicos cuyo valor caduca.

---

## 6. Idempotencia y reintentos

### 6.1 · La llave se **construye**, nunca es aleatoria

El proyecto ya tiene la forma: `Idempotency-Key` obligatorio en operaciones de dinero, persistido con `UNIQUE(company_id, idempotency_key)` en la tabla del documento (`00005`, `00006`, `00009`, `00032`, `00037`, `00042`, `00054`), y la violación de ese único la traduce un handler a `409 IDEMPOTENCY_IN_PROGRESS` (`app/core/errors.py:164`, hallazgo F10-01: antes eran cinco `500`).

**Se sigue el mismo criterio, con una diferencia que es la clave de todo:** en una mutación de dinero la llave la **trae el cliente**. Acá no hay cliente HTTP — la trae el propio evento, y se arma con lo que lo hace único:

| Familia | `dedupe_key` | Por qué así |
|---|---|---|
| Transaccional | `payment:<contract_payment_id>` · `contract:<contract_id>` · `sale:<sale_id>` · `extend:<contract_id>` | El documento ya existe, ya es único por empresa y ya es inmutable. Un abono, un aviso, para siempre |
| Recordatorio | `due_soon:<customer_id>:<target_date>:<lead_days>` | Lleva **la fecha de la que habla**, no la fecha en que corrió el job |
| Estado | `arrears:<contract_id>:<interest_paid_until>` · `extension:<contract_id>:<extension_ends_at>` | Anclada al **ancla del contrato**, que es lo que cambió |
| Resumen | `digest:<company_id>:<occurred_on>` | Uno por empresa por día, por construcción |

**Por qué la llave del recordatorio lleva la fecha objetivo y no la del envío.** Es la única forma de que el job pueda correr **dos veces la misma noche**, o **tres días después**, sin duplicar — y de que el mes siguiente sí mande, porque `target_date` es otra. Si la llave llevara `today`, correr el job dos veces mandaría dos correos; si no llevara fecha, no volvería a mandar nunca.

**`interest_paid_until` en la llave de mora hace el trabajo solo:** cuando el cliente abona, el ancla avanza, así que la llave del mes siguiente es distinta sin que nadie tenga que "limpiar" nada.

### 6.2 · Para el job, el choque de llaves **no es un error**

La violación del `unique` sube hoy como `409 IDEMPOTENCY_IN_PROGRESS`, y eso es correcto en un `POST`: *"no repitas, consulta el resultado"*. **Dentro del job es el camino normal**, y hay que escribirlo así: `on conflict (company_id, dedupe_key) do nothing`, contando los que no entraron. Un job que se cae con un 409 la segunda noche es un job que deja de correr, y su ausencia es silenciosa.

### 6.3 · Reintentos

| Clase de falla | Qué se hace |
|---|---|
| `5xx` de Resend, timeout, `429` de cuota | **Reintentable.** 3 intentos, a la +1 h, +6 h y +24 h. Al cuarto: `dead` |
| Rebote **duro** (dirección inexistente) | **Cero reintentos** → `bounced`, y se marca `customer.email_invalid_at` (§7) |
| Rebote **blando** (buzón lleno, temporal) | Reintentable, mismo esquema |
| `suppressed` / `unroutable` / `throttled` / `skipped_stale` | Terminales. No se reintentan **nunca**: no falló nada |

**Por qué 3 y no 10.** Resend caído más de 24 h es un incidente, no un caso de reintento — y a las 24 h un recordatorio de cuota ya no es un recordatorio. Reintentar diez veces solo mueve la fecha en que alguien se da cuenta.

**Quién reintenta:** el job nocturno, barriendo `status in ('pending','failed')` con `scheduled_at <= now()`. Cero infraestructura nueva. La contrapartida es que el backoff real es de un día, no de una hora, mientras no exista un despachador más frecuente — **suposición no verificada:** habría que confirmar si `fly machines run --schedule` admite algo más fino que `daily`/`hourly` antes de prometer un reintento a la hora.

---

## 7. Auditoría: un envío **no** se audita

**Decidido: `notification_event` + `notification_delivery` *son* el registro. No se escribe en `audit_log` por cada envío.** Tres razones:

1. **`audit_log` responde "quién hizo qué".** Un envío automático no tiene quién: iría con `user_id = NULL`, como ya van `expire_subscription` y `correct_contract_status`. Esos son dos casos excepcionales; los envíos serían **cientos por mes** y volverían la excepción la mayoría.
2. **Inundaría la única pantalla que sirve para vigilar empleados.** La auditoría se arregló hace poco justo para que contestara *"¿qué pasó hoy?"* — ordenaba por UUID aleatorio y salía en orden arbitrario (reportado el 08/09/2026). Meterle 300 filas de máquina al mes la vuelve a romper, por otra vía.
3. **Sería el mismo dato en dos tablas.** El defecto que este proyecto persigue con más insistencia (`00022`–`00023`, el precio del lote; `00043`, el saldo de la nota crédito): **un dato guardado dos veces se desincroniza; uno derivado no puede.**

**Qué SÍ va a `audit_log` — lo que tiene un quién:**

| Acción | Por qué |
|---|---|
| Encender o apagar los avisos de una empresa | Ya lo cubre `update_settings`. Es un cambio de política con consecuencias hacia afuera |
| `resend_notification` | **Una persona decidió volver a escribirle a un cliente.** Hay un quién, hay un cuándo, y es el caso que alguien va a preguntar en seis meses |
| Autorización expresa, cambio de `email_basis` o baja (opt-out) de un cliente | Habeas Data (§9.2): la autorización tiene que quedar probada **con quién la registró y cuándo**. Dos matices: el `email_basis='contract'` que escribe `create_contract` no necesita fila propia —su prueba **es el contrato**—, y el opt-out que hace el propio cliente va con `user_id = NULL`, porque no lo hizo un empleado |

**Y sobre el agujero de F21-10, con honestidad:** el job nocturno **no escribe en `audit_log`** (`app/jobs/nightly.py`), y por eso no dejó rastro forense — *"no se puede saber cuál de los dos vectores causó cada fila"*. Este diseño **no cierra eso**: `recompute_all_statuses` sigue sin auditar. Lo que sí hace es que el tercer paso del job deje un rastro **más útil que una fila de auditoría**, porque registra lo que **decidió** (`sent` / `unroutable` / `skipped_stale` / `suppressed`) y no solo que corrió. Auditar `recompute_all_statuses` sigue pendiente y es un trabajo aparte.

---

## 8. Multi-tenancy y remitente: **el remitente es la plataforma, el autor es la empresa**

Hay **un solo dominio**, `prendo.com.co`, ya verificado y conectado. No hay un dominio por inquilino y no va a haberlo pronto. Así que la pregunta no es técnica, es de producto: **un correo sobre un contrato de empeño, ¿de quién parece venir?**

```
From:      LA GRAN LEGAL (vía Prendo) <notificaciones@prendo.com.co>
Reply-To:  contacto@lagranlegal.example        ← company.contact_email, si existe
Subject:   LA GRAN LEGAL · Su cuota vence el 1 de octubre
Firma:     LA GRAN LEGAL · Tel. 300 000 0000 · <footer_note del inquilino>
           Enviado por Prendo en nombre de LA GRAN LEGAL · No me escriban más
```

| Decisión | Por qué |
|---|---|
| El dominio es de la plataforma | **No hay alternativa técnica.** Firmar como `@lagranlegal.com` exige SPF/DKIM en el DNS de ese dominio, y el inquilino no tiene dominio. Falsear el `From` va directo a spam por DMARC |
| El **nombre visible** es del inquilino | La relación del cliente es con la compraventa. Un correo firmado solo *"Prendo"* sobre su contrato de empeño, de una marca que nunca oyó, **se lee como phishing** — y con razón |
| El `(vía Prendo)` va **escrito**, no escondido | Gmail y Outlook **ya muestran** "via prendo.com.co" cuando el dominio del remitente no coincide con el nombre. Va a aparecer de todos modos: mejor decidido y en español que filtrado por el cliente de correo |
| El **asunto nunca dice Prendo** | El asunto es lo único que el cliente lee antes de decidir si abre. Ahí el que importa es el negocio que le prestó la plata |
| El `Reply-To` es del inquilino | Si el cliente responde *"¿puedo pagar el martes?"*, eso tiene que llegar a la compraventa, no a la plataforma. **Si `contact_email` está vacío** (es nullable y hoy casi nadie lo llenó): sin `Reply-To`, y el cuerpo pone el teléfono. Nunca un `Reply-To` que nadie lee |
| Los correos **de la plataforma** invierten todo | Invitación, enlace de acceso, suscripción por vencer: remitente **Prendo**, sin nombre de inquilino. Ahí la contraparte es Prendo de verdad |

> **La regla, en una línea: el remitente lo decide quién es la contraparte del destinatario.** El cliente de una compraventa tiene enfrente a la compraventa. Un usuario de Prendo tiene enfrente a Prendo. **Las dos marcas no se mezclan, y por eso el respaldo del nombre en `AppShell` es `'Mi empresa'` y no `'Prendo'`** (`AppShell.tsx:140-142`, `AppFooter.tsx:18`): ese texto es el nombre del inquilino.

**Suposición marcada, a verificar antes de implementar:** que el nombre visible del `From` pueda variar por inquilino con un solo dominio verificado en Resend. Es lo normal en los proveedores de correo, pero **no lo verifiqué contra la API de Resend** y si no se pudiera, la alternativa es un subdominio o una dirección por inquilino (`lagranlegal@prendo.com.co`), que tiene su propio costo de reputación.


### 8.1 · El aspecto de los correos: el molde de las plantillas de Supabase (25/09/2026)

**De dónde sale.** Los correos que redacta el backend (`notifications/templates.py`) usan el molde de las plantillas que están pegadas en Supabase Auth — `frontend-starter/docs/correo-invitacion.html` y `correo-recuperacion.html`—, que son las que al dueño le gustan: fondo beige `#f1ebdd`, tarjeta blanca con borde `#ddd7c9`, la marca en versalitas `#7a5a1c`, botón píldora dorado `#c99a3d` con texto carbón, recuadro de aviso sobre beige y pie con línea separadora. Las razones del molde (tablas y estilos en línea, una columna, botón hecho con una tabla, el enlace repetido como texto, ninguna imagen externa) y los contrastes medidos están en la cabecera de esas plantillas; no se repiten acá. **La invitación (P1) es la plantilla «Invite user» casi al pie de la letra** —en *tú*, como ella, aunque el resto de los correos sigan en *usted*—, con una diferencia a propósito: nombra a la empresa en el cuerpo («te invitaron a trabajar en X»), porque el backend sí sabe quién invitó y Supabase, con una plantilla por proyecto, no. El pie no repite el correo del destinatario, como sí hace Supabase: la plantilla solo lee `invitee_name` e `invite_link`.

Una corrección respecto del molde, medida: la tarjeta de Supabase es `width:560px;max-width:100%`, y una tabla con ancho fijo **no se encoge** — a 360 px de ancho desborda (592 px medidos con Chrome). La del backend es `width:100%;max-width:560px`, con una tabla fantasma de 560 solo para Outlook de escritorio (`<!--[if mso]>`), que ignora `max-width`. Si se retoca la plantilla de Supabase, conviene llevarle el mismo arreglo.

**Por qué los avisos al cliente no llevan «Prendo» en el encabezado.** Es esta misma sección aplicada al cuerpo: el autor es la empresa. Donde la invitación y el resumen dicen PRENDO, el aviso al cliente dice el nombre de la compraventa; Prendo aparece solo bajo la tarjeta, en «Enviado por Prendo en nombre de …», que es lo que la honestidad exige y el `(vía Prendo)` del `From` ya anuncia. Un cliente que ve una marca que nunca oyó encabezando un correo sobre su contrato de empeño lo lee como phishing, que es exactamente el argumento de la tabla de arriba. El molde sigue siendo uno solo porque es de la plataforma (§4.4): cambia la marca, no la redacción ni el diseño. La firma de la empresa (teléfono, `footer_note`) va en el recuadro beige, y el enlace de baja (§9.2-e) en el pie, subrayado y a la vista.

---

## 9. Habeas Data — Ley 1581

La base tiene clientes reales con **cédula y fotos del documento** (`customer.doc_number`, `doc_photo_url`, `doc_photos` desde `00050`). Un correo con el detalle de un contrato de empeño es **dato sensible que sale del perímetro**, y una vez enviado no se puede recoger. El proyecto ya trató esto con seriedad: `verificar_cadenas.py` **no** se puso en GitHub Actions a propósito, porque exportar `DATABASE_URL` como secret de un tercero amplía el radio de exposición más de lo que aporta. El mismo criterio manda acá.

### 9.1 · Qué va en el cuerpo, y qué no

> **Un correo es un aviso, no un documento.** El documento está en la app, o en el papel firmado.

| Dato | ¿Va? | Por qué |
|---|---|---|
| Nombre del cliente (solo el nombre de pila) | **Sí** | Es el mínimo para que no parezca un correo masivo |
| Número de contrato, recibo o venta | **Sí** | Es la referencia con la que el cliente pregunta en el mostrador |
| **Monto y fecha** | **Sí** | Es el aviso entero. Un recordatorio sin monto no previene nada — y sin él el cliente tiene que entrar a averiguar, que es el trabajo que el correo venía a ahorrar |
| **Descripción de la prenda** | **NO** | El peor de todos si se equivoca el destinatario: *"su cadena de oro de 18 k"* le dice a un desconocido que en esa casa hay oro. Y no aporta nada: el número de contrato identifica igual |
| **Número de cédula**, ni enmascarado | **NO** | Utilidad cero, daño máximo. Es el dato que convierte un correo mal dirigido en una fuga de identidad. El cliente ya sabe su cédula |
| Dirección, teléfono, fotos del documento | **NO** | Nada de esto ayuda a entender un aviso |
| Saldo total de la deuda | **Sí**, en los transaccionales de contrato | Es la pregunta que el cliente hace siempre. En los recordatorios agrupados, el saldo por contrato |
| Archivos adjuntos | **NO, nunca** | Un adjunto con datos personales se reenvía solo, sobrevive al `bounce` y no hay forma de saber dónde quedó |

**Y por eso `notification_event.payload` guarda lo mínimo para redactar**, no una foto del documento. Es una decisión de retención: esa tabla va a tener miles de filas y ser la más fácil de exportar por error.

> **La decisión del 22/09 sobre la base legal (§9.2) no toca nada de esta tabla, y conviene decirlo.** Que un correo se apoye en la relación contractual habilita **mandarlo**, no **contar más**. La finalidad `service` es justamente lo que obliga a que el cuerpo hable del contrato de esa persona y de nada más; un correo que se apoya en el contrato y encima trae la cédula o la prenda se sale de su propia base. Si algo, la base contractual hace esta sección **más** estricta, no menos.

### 9.2 · Base legal: se distingue por FINALIDAD, no por una casilla de consentimiento genérico

**Decidido el 22/09/2026.** Mateo pidió una recomendación y esta es, con su salvedad escrita en (h) y no en una nota al pie.

> **Un recordatorio sobre el propio contrato que la persona firmó es servicio del contrato, no mercadeo**, y se apoya en la relación contractual. **Cualquier cosa que no sea eso** —promociones, *"vuelva a visitarnos"*, avisos de otra empresa— **exige autorización expresa.**

Esto reemplaza el diseño anterior (*"sin `email_consent_at` no sale nada"*), que era el estricto por defecto. El cambio de fondo no es volverse laxo: es que **"¿tengo permiso?" estaba mal planteada como un booleano.** Bien planteada son dos datos que hoy no existen: **para qué es este correo** y **bajo qué base tengo la dirección de esta persona**.

**(a) La base se guarda por cliente, explícita, y no como un booleano.**

```sql
alter table public.customer
  add column email_basis          text,          -- 'contract' | 'consent' | null = ninguna
  add column email_consent_at     timestamptz,   -- cuándo autorizó expresamente (solo con 'consent')
  add column email_consent_source text,          -- 'counter' | 'contract_form' | 'import' | ...
  add column email_opt_out_at     timestamptz,   -- pidió la baja; manda sobre todo lo demás
  add column email_invalid_at     timestamptz;   -- rebotó duro; no volver a intentar (§6.3)
```

**Cómo se escribe `contract`, y por qué se escribe en vez de deducirse.** La migración lo pone en los clientes que hoy tienen correo y al menos un contrato no terminal; de ahí en adelante lo pone `create_contract` cuando el cliente tiene correo y todavía no tiene base. **No se deriva en cada envío con un `join` contra los contratos vivos**, y el motivo es el mismo del SNAPSHOT legal del contrato (`CLAUDE.md`): la base legal que importa es **la que había el día que se mandó el correo**, y eso hay que poder mostrarlo seis meses después. Un cálculo al vuelo contesta qué pasa hoy, no qué pasaba entonces.

**(b) Cada evento del catálogo lleva su finalidad.** `purpose`: `service` | `marketing`. **Hoy todos los eventos de §2 son `service`** — no hay ni uno de mercadeo en el catálogo, y esa es justamente la razón por la que la recomendación es sostenible. El catálogo **no admite un evento sin `purpose`**: no hay valor por defecto, porque el defecto sería el cómodo y el día que alguien agregue *"promoción de fin de año"* nadie se va a acordar de esta sección.

**(c) La decisión de enviar es una función de las dos, y se evalúa en un solo lugar.**

| Finalidad del evento | Base `contract` | Base `consent` | Sin base (`null`) |
|---|---|---|---|
| **`service`** — el propio contrato, abono, venta o paz y salvo de esa persona | **sale** | **sale** | `suppressed` |
| **`marketing`** — promoción, reactivación, cualquier cosa de otra empresa | `suppressed` | **sale** | `suppressed` |

Y por encima de la tabla, tres cortes que ganan siempre y en este orden: **no hay dirección** (`unroutable`, §1), **`email_opt_out_at` puesta**, **`email_invalid_at` puesta**. Ninguna base legal sobrevive a que el titular haya pedido la baja — esa es la diferencia entre tener derecho a escribir y tener razón.

**El interruptor por empresa sigue apagado por defecto (§4.3), y eso no cambia.** Ninguna de estas bases enciende nada sola: primero alguien de la compraventa decide que su negocio le escribe a sus clientes, con la pantalla que dice cuántos correos van a salir.

**(d) El punto de todo esto: la decisión difícil se vuelve un dato, no un rediseño.** El mapa *finalidad → bases aceptadas* es **configuración de la plataforma**, no del inquilino (la ley es la misma para los treinta). Hoy: `service: ['contract','consent']`, `marketing: ['consent']`. Si mañana un abogado dice **"estricto"**, se cambia una línea —`service: ['consent']`— y pasa exactamente esto: los clientes que solo tenían base contractual dejan de recibir, sus entregas quedan `suppressed`, el contador sube y se ve en el agregado (§4.2). **Cero migraciones, cero backfill, cero plantillas tocadas, ninguna fila borrada.** Y al revés también: si el concepto dice que la base contractual alcanza y hasta cubre reactivar clientes viejos, es la misma línea en la otra dirección.

**Es el mismo criterio con el que se resolvió el aviso de remate** (§2.2): cuando la decisión no se puede tomar bien hoy, lo que se construye es el interruptor, no la decisión. Ahí fue un `settings` por empresa porque la pregunta era del negocio; acá es configuración de plataforma porque la pregunta es de la ley. **La forma es la misma; el dueño de la respuesta, no.**

**(e) Todo correo lleva salida (opt-out), incluidos los de servicio del contrato.** No porque la ley lo exija en cada correo transaccional —eso es parte de lo que hay que confirmar—, sino porque **es barato y es lo que convierte una queja en una baja**. Quien se cansa de recibir avisos y no encuentra cómo salir marca spam, y esa marca no la paga el inquilino que la provocó: la paga la reputación de `prendo.com.co` para todos los demás (§8). El enlace escribe `email_opt_out_at` y gana sobre cualquier base, como dice (c).

**(f) Capturar la autorización expresa en el mostrador, de ahora en adelante.** Preguntarla cuesta cero y quita la duda para siempre; no preguntarla deja al producto colgado de una interpretación. Va donde ya va la captura del correo (§1c), al crear el contrato, junto al *"¿quiere recibir avisos de su cuota por correo?"*: una casilla aparte, con su texto. Quien dice que sí queda `email_basis='consent'` + `email_consent_at` + `email_consent_source='contract_form'`, y ese cliente **ya no depende de cómo se resuelva la pregunta legal**. Quien no contesta se queda en `contract` y sigue recibiendo lo de su contrato.

**Lo que NO se hace: volver obligatorio el correo.** Obligarlo trabaría el mostrador y además no funcionaría —quien no tiene correo escribe `a@a.com` (§1c)—. **"No tiene correo" es el caso normal** (§1), y ninguna decisión legal cambia ese dato: lo que se gana acá es a quién se le puede escribir, no cuántos hay.

**(g) Los 2 correos que ya existen: qué pasa con ellos ahora.** Con el diseño anterior nacían `suppressed` y había que volver a pedirles autorización. Con este, si tienen contrato vivo nacen `email_basis='contract'` y **son destinatarios desde el primer día**. Lo que **no** se hace es marcarlos `consent`: nadie los autorizó expresamente, y escribir una fecha de autorización que no ocurrió sería fabricar la prueba. **`email_consent_at` solo se escribe cuando alguien dijo que sí**, y por eso sigue sirviendo como prueba cuando se la pidan.

**(h) La salvedad, sin adornos.** **Esto es una recomendación de producto e ingeniería, no asesoría legal.** La **Ley 1581 de 2012** exige autorización previa, expresa e informada del titular **como regla general**, y contempla excepciones. **Si un aviso sobre el contrato que la propia persona firmó cae en una de ellas —o si la relación contractual basta como base— lo tiene que confirmar un abogado.** No cito artículos, decretos ni jurisprudencia a propósito: no los verifiqué, y un número inventado en un documento de diseño termina copiado en un correo a un cliente. Lo que el diseño garantiza no es tener la razón: es que **la respuesta del abogado sea un cambio de configuración y no un rediseño**.

**(i) Qué papel sostiene la base `contract` (decisión del 25/09/2026, §12.3-4).** Hasta acá `contract` era «la
relación contractual» en abstracto. Desde el 25/09 el criterio del dueño es concreto: la base se apoya en **una
cláusula de autorización de avisos dentro del contrato firmado**, más la **política de tratamiento de datos**
de la empresa (Ley 1581). La relación con lo construido:

| Pieza | Dónde | Qué hace |
|---|---|---|
| La cláusula | `document_template` del contrato (editor del front, `00046`) | El front la ofrece como **ejemplo insertable**; la empresa decide si la usa y con qué redacción. **El backend no la lee ni la exige**: el cuerpo del contrato es del inquilino (§4.4) y es ProseMirror que renderiza el front |
| El valor `email_basis = 'contract'` | `customer`, escrito por `create_contract`/`import_contract`/`extend_loan` (§17) | Sigue siendo lo que el despachador cruza con la finalidad (§9.2-c). No cambió nada del código |
| La prueba | el contrato firmado | Es lo que §7 ya decía: la prueba de la base `contract` **es el contrato**. Con la cláusula adentro, esa prueba dice además qué autorizó |

**Lo que esto NO resuelve, dicho:** el backend no puede saber si el contrato que firmó un cliente tenía la
cláusula — una empresa que no la inserte sigue escribiendo `contract` igual. Validarlo exigiría leer el cuerpo
del contrato impreso, que es del front y del inquilino. Queda como responsabilidad de la empresa, y es otra razón
para la revisión legal previa que recomienda §12.3.

### 9.3 · Si el correo está mal escrito y le llega a un tercero

Es el caso que no tiene vuelta atrás, y hay que separar dos cosas:

- **Rebota** → se detecta. `bounced`, `email_invalid_at`, cero reintentos, y el cliente aparece en la lista de "revisar correo". **Falla ruidosa.**
- **Se entrega a otra persona** → **no se detecta nunca.** `juan.perez@gmail.com` por `juan.peres@gmail.com` es una dirección que existe, de un desconocido, y Resend reporta `delivered`. **Falla silenciosa, y es la peor del sistema.**

**No hay mitigación después del envío. Toda la mitigación es previa, y son tres:**

1. **Que el cuerpo no lleve cédula ni prenda (§9.1).** Es la única defensa que funciona contra lo indetectable: si llega a un tercero, ese tercero se enteró de que existe un contrato, no de quién es ni de qué dejó empeñado.
2. **Validar el formato en el backend** — hoy no se hace (§1, §13). No atrapa el dedazo verosímil, pero saca la basura.
3. **Confirmar la dirección la primera vez.** El primer correo a un cliente es un *"confirme que este correo es suyo"* que exige una acción; hasta que la haga, los demás quedan `pending`. **Y esa acción va por `POST`, nunca por un `GET` de un solo uso** — el proyecto ya reprodujo ese bug el 03/09/2026: los generadores de vista previa de WhatsApp y los escáneres de Gmail/Outlook **queman el enlace antes que el destinatario** (`auth_admin.py::_app_link`). Un enlace de confirmación auto-consumido por un escáner confirmaría direcciones solo. **Es la misma razón por la que P2, el enlace de acceso, se queda pasándose a mano por WhatsApp.**

> **Suposición marcada, y sobrevive a la decisión del 22/09:** no sé si la Ley 1581 exige un aviso de privacidad con formato específico en cada comunicación, ni si un recordatorio de cobro cuenta como comunicación comercial. La decisión de §9.2 elige una **base** legal; **no** resuelve qué texto tiene que llevar el pie del correo. **Esto lo tiene que revisar un abogado, no un documento de diseño** — y cuando lo diga, es texto de plantilla, que vive en el repositorio (§4.4) y se cambia en un despliegue.

---

## 10. Límites y costo

Resend en plan gratuito: **3.000 correos/mes** sobre un dominio verificado. *(Suposición: el tope diario — creo que 100/día — **no lo verifiqué**. Importa, porque el resumen diario y una tanda de recordatorios caen el mismo minuto: hay que confirmarlo antes de construir.)*

### Lo medido hoy en la base dev

| | Medido |
|---|---|
| Empresas | 7 (5 activas; 2 son laboratorios de QA) |
| Contratos vivos | **49** — LA GRAN LEGAL 22, Demo Front 15 |
| **Clientes** con contrato vivo | **12** ← el que manda, no el de contratos |
| Clientes con correo | **2 de 16** |
| Contratos creados en septiembre | 49 |
| Abonos en septiembre | 11 |
| Ventas en septiembre | 13 |
| Gastos en septiembre | 8 |
| Usuarios (todos con correo) | 27 |

### La estimación

**Hoy, con los datos reales: menos de 250 correos/mes en toda la base, y el techo del cliente es 2 destinatarios.** Resend gratis sobra por un orden de magnitud, y el cuello de botella **no es la cuota: es que el cliente no tiene correo** (§1).

Proyectado a un inquilino del tamaño de LA GRAN LEGAL, si todos sus clientes tuvieran correo:

| Concepto | Cálculo | Al mes |
|---|---|---|
| Recordatorios al cliente | 5 clientes × ~4 puntos de aviso | ~20 |
| Transaccionales al cliente | contratos + abonos + ventas del mes | ~70 |
| Resumen diario a la empresa | 1 × 30 días × 2 destinatarios con el permiso | 60 |
| Alertas inmediatas (§2.5) | poquísimas por naturaleza | ~5 |
| **Total por inquilino** | | **~155/mes** |

**3.000/mes ≈ 19 inquilinos de ese tamaño.** Se aprieta antes si los inquilinos son más grandes, y el primer número que lo rompe no es el de clientes: **es el resumen diario**, porque es el único que no depende de que haya actividad. 30 correos fijos por destinatario por mes por inquilino.

**Lo que decide la escala es la agrupación de §2.3.** Sin ella, con 22 contratos vivos y 4 puntos de aviso, LA GRAN LEGAL sola pasa de ~20 recordatorios a ~88, y el cliente de los 13 contratos recibe 13 correos en una noche. **La misma decisión que hace el producto tolerable es la que hace que la cuota alcance**, y eso no es coincidencia: si el volumen molesta a la máquina, ya molestaba al destinatario.

---

## 11. Fases de implementación

De lo más valioso a lo menos, y cada fase entrega valor sola.

> **Qué movió el 22/09/2026 (§12.0).** El orden no cambió; **el contenido de la fase 3 y su bloqueo sí.** Antes era *"capturar consentimientos"*: trabajo de mostrador que nadie controla y que no termina nunca, con la fase 4 esperando a un número que no dependía del equipo. Con la base contractual (§9.2), la fase 3 es **código** —columnas, mapa de finalidades, enlace de baja, `EmailStr`— y **los clientes con contrato vivo ya son destinatarios el día que se despliega**. Lo que sigue igual, y hay que decirlo para no vender humo: **el cuello de botella nunca fue legal, es que 14 de 16 clientes no tienen correo** (§1).

| # | Qué | Por qué en este orden |
|---|---|---|
| **1** | **El resumen diario a la empresa (§2.4), empezando por E1 "listos para remate"** | **El primer envío que hay que construir.** Cuatro razones: (a) **100 % entregable hoy** — `app_user.email` es `NOT NULL`, 27 de 27; (b) **cero riesgo de Habeas Data** — el dato se queda dentro de la empresa, va a sus propios usuarios; (c) **cero ambigüedad de marca** — el destinatario es un usuario de Prendo; (d) **ejercita todo el andamio** (Resend, las dos tablas, estados, reintentos, idempotencia, el tercer paso del job) sobre una población donde un bug no cuesta nada. Y el valor es real y medible: **8 contratos listos para rematar en dev ahora mismo**, sin que nadie los mire |
| **2** | **Migrar la invitación (P1) de Supabase Auth a Resend** | Es lo único que está **roto hoy**: `INVITE_RATE_LIMITED` con el SMTP compartido. Reusa todo lo de la fase 1 y no toca al cliente final. **No toca «Generar enlace»**, que es lo que hace que el alta de usuarios funcione sin correo y que no se rompe por esto |
| **3** | **Base legal, salida y captura (§1c, §9.2) + validar el correo en el backend** | **Va antes de cualquier correo al cliente, pero ya no bloquea como antes.** Entrega: `email_basis` con su backfill a `contract`, el `purpose` en el catálogo, el mapa de §9.2-d, el enlace de baja (§9.2-e), la casilla de autorización expresa en el mostrador (§9.2-f) y el `EmailStr` que falta (§13-1). Sin esto, todo envío al cliente se apoya en una base que no quedó escrita en ningún lado. **Lo que dejó de ser:** una campaña previa de recolección de firmas. Sigue sin mandar ni un correo y sigue habilitando las tres siguientes |
| **4** | **Paz y salvo (C3) + abono (C2)** | El primer correo al cliente. Se empieza por el que el cliente **quiere**: el comprobante de que no debe nada. La consecuencia de un fallo es un correo de menos, no una sorpresa. Sirve de prueba real de la base legal de la fase 3. **Lo que cambió el 22/09:** antes esta fase esperaba a que existieran consentimientos capturados uno por uno; ahora espera solo a que la fase 3 esté desplegada |
| **5** | **Recordatorios de cuota y prórroga (R1–R4), agrupados por cliente** | El de más valor de negocio y el de más riesgo: llega sin que nadie lo pida, lleva plata y fechas, y es el que estampida si el job falla (§5.3). Exige la ventana de rezago y el tope de §3 **funcionando y probados**, no planeados |
| **6** | **Contrato creado (C1), ampliación (C4), nota crédito (C5), venta (C6/C7)** | Valor real pero menor: el cliente estaba presente cuando pasó y se fue con el papel |
| **7** | **Alertas inmediatas a la empresa (§2.5)** | Deliberadamente al final: su valor depende de que el resumen diario ya tenga la confianza de quien lo recibe |
| **8** | **WhatsApp** | Fuera de alcance. Entra como `channel` nuevo sobre eventos que ya existen (§4.1), y el día que llegue será el canal principal del cliente. **Diseñar para que quepa es parte del trabajo de hoy; construirlo no** |

**Lo que hay que tener listo antes de la fase 1:** el dominio verificado en Resend (ya está), el tope diario confirmado (§10), `notifications.receive_digest` en el seed de permisos, el interruptor por empresa **apagado**, el **catálogo de eventos con `purpose` y `default_enabled`** —con `auction_ready_customer` presente y en `false` (§2.2)—, y el tercer paso del job **después** de `recompute_all_statuses` (§5.2). El catálogo va desde la fase 1 aunque su primer evento apagado sea para el cliente: si nace sin esas dos columnas, agregarlas después obliga a tocar todos los tipos que ya existan. Y **recrear la Fly Machine `nightly-job`** contra la imagen nueva en el mismo despliegue: `fly deploy` **no la actualiza** y esa es, literalmente, la causa de F21-10.

---

## 12. Preguntas de negocio pendientes

**Eran ocho. Mateo cerró dos el 22/09/2026, y quedan siete:** las seis que no tocó, más una que **abrió la
propia decisión** (el peso legal del aviso de prórroga). Se numera, aunque no sea una de las ocho
originales, por la razón que el propio documento da más abajo: *una pregunta abierta escondida dentro de
una decisión que dice «cerrada» es una pregunta que nadie vuelve a hacer.* Y esta va **al mismo abogado y
en la misma consulta** que la del remate, así que tiene que viajar con la lista, no debajo de ella.** Las dos cerradas están resueltas en el cuerpo del documento y se resumen en §12.0, para que quien lea solo esta sección no las reabra como si siguieran en discusión. Ninguna de las seis que quedan se puede contestar desde el código. Van en orden de cuánto bloquean.

### 12.0 · Lo que se cerró el 22/09/2026 (Mateo)

**(a) ¿Le avisamos al cliente que su prenda está lista para remate? — NO por ahora, y el evento existe igual.**
Respuesta textual: *"por el momento no, pero la app debe tener la escalabilidad por si se requiere más adelante"*. **Confirma** lo que la spec proponía (§2.2, R5: el aviso va a la empresa, como E1) y le quita lo provisional. Lo que **agrega** es el requisito que importa: `auction_ready_customer` existe en el catálogo **desde el día uno**, con `audience='customer'` y `default_enabled = false`. No es un evento que se agregará: **está y no se dispara.** Encenderlo es poner `company.settings.notifications.events.auction_ready_customer = true` — una **preferencia por empresa y no un permiso**, con la comparación contra el precedente de `RECARGOS.md` §8.1 hecha renglón por renglón en §4.3 (resumida: *"nadie sabe responder eso al dar de alta"* no aplica porque acá no se pregunta al dar de alta, y *"la misma regla en dos pantallas"* no aplica porque hay una sola — el job). El argumento legal que lo frenó y **qué haría falta para que deje de aplicar** —registrar la entrega de forma probatoria, que el contrato firmado no diga otra cosa, y el concepto de un abogado— quedan escritos en §2.2-c, para que quien lo encienda sepa qué está asumiendo.

> **Lo único que quedó abierto de esta decisión: ¿el aviso de prórroga (R3) tiene el mismo peso legal? Quedó numerada como la §12.1-7**, aunque no sea una de las ocho originales — precisamente por lo que se dice al final de este recuadro. R3 hoy **se manda** al cliente, con este criterio —**y es criterio propio, no concepto**—: informar que el contrato cambió de estado no es lo mismo que anunciar que la prenda se va a disponer. Va al mismo abogado y en la misma consulta que (a), porque es la misma pregunta con otro sujeto. Si la respuesta es que pesa igual, **no hay rediseño**: R3 ya es una entrada del catálogo y el mismo interruptor lo apaga (§2.2-d, §4.3). Se anota acá en un recuadro propio justamente porque **una pregunta abierta escondida dentro de una decisión que dice "cerrada" es una pregunta que nadie vuelve a hacer**.

**(b) ¿Hace falta autorización expresa de Habeas Data para un recordatorio de cobro? — Se distingue por FINALIDAD, no por consentimiento genérico.**
Un recordatorio sobre **el propio contrato que la persona firmó** es *servicio del contrato* y se apoya en la relación contractual; promociones, reactivaciones o avisos de otra empresa exigen **autorización expresa**. Se implementa como dos datos y un mapa: `customer.email_basis` (`contract` | `consent`), el `purpose` de cada evento del catálogo, y la tabla de §9.2-c que los cruza. **El punto no es la respuesta, es que la respuesta sea configuración:** si mañana un abogado dice "estricto", se cambia `service: ['consent']` y los clientes con base solo contractual quedan `suppressed` —contados y visibles— sin migración, sin backfill y sin rediseño. Es el mismo criterio de (a): la decisión difícil se vuelve un dato. Además: **todo correo lleva salida**, incluidos los de servicio del contrato (§9.2-e), y **la autorización expresa se captura en el mostrador de ahora en adelante sin volver obligatorio el correo** (§9.2-f). **Lo que cambia en el calendario:** los clientes con contrato vivo **ya son destinatarios**, y la fase 3 deja de ser una campaña de recolección para ser código (§11).
**Salvedad, en el mismo renglón que la decisión y no en una nota al pie: esto es una recomendación de producto e ingeniería, no asesoría legal.** La **Ley 1581 de 2012** exige autorización previa, expresa e informada **como regla general**, y las excepciones las confirma un abogado (§9.2-h).

### 12.1 · Las siete que siguen abiertas

1. **¿Cuántos días antes se avisa la cuota, y cuántas veces?** Puse 3 días como parámetro sin decidir el valor. Y la de fondo: ¿se avisa **también** cuando ya venció (R2)? Un recordatorio es un favor; un cobro repetido es otra cosa, y la frontera la pone el negocio, no el sistema. **No reusar `grace_days`** (§4.3).
2. **¿El resumen diario le llega también al dueño cuando no hay nada que reportar?** Un correo que dice "todo en orden" prueba que el sistema vive y entrena a abrirlo; treinta seguidos entrenan a archivarlo. Mi recomendación: **sí los primeros 30 días, después solo cuando haya algo** — pero es una decisión de producto.
3. **¿Puede un inquilino redactar sus propios correos?** Lo decidí como **no** (§4.4), con el argumento de que la entregabilidad es un recurso compartido. Si comercialmente hace falta ofrecerlo, no es una fila en `document_template`: es un producto con revisión previa a la activación.
4. **¿Cuál es el umbral de "descuento grande" y de "descuadre grande" para las alertas inmediatas (§2.5)?** Un monto fijo se desactualiza y un porcentaje no dice nada sobre un contrato chico. Hoy no hay con qué medirlo: hay 11 abonos y 13 ventas en septiembre en toda la base. Recomendación: nacer con el umbral en 0 —avisar **todos** los descuentos, que son pocos— y subirlo cuando moleste. **Cerrado de más se nota; abierto de más no** (es el mismo criterio con que se resolvió `TERMINAL_STATUSES` en `rules.py`).
5. **¿`stale_after_days` en cuánto?** Cuántos días de atraso hacen que un recordatorio deje de mandarse (§5.3). Puse el mecanismo, no el número. Mi recomendación: **2 días** — un aviso de "vence en 3 días" mandado el día del vencimiento todavía sirve; mandado una semana después, no.
6. **¿El correo del cliente es de la empresa o de la plataforma?** Un cliente de LA GRAN LEGAL que también es cliente de otra compraventa en Prendo hoy son **dos filas de `customer`**, una por inquilino, cada una con su autorización. Es coherente con todo el modelo (RLS por `company_id`) y creo que es correcto: autorizó a **una** compraventa. Pero significa que un opt-out en una no vale en la otra, y que puede recibir dos correos de dos inquilinos el mismo día. Vale decirlo antes de que alguien lo reporte como un bug.

7. **¿El aviso de prórroga (R3) tiene el mismo peso legal que el de remate?** Es el residuo de la decisión (a) de §12.0: Mateo cerró el aviso de remate, y al cerrarlo quedó en pie la pregunta con otro sujeto. **R3 hoy SE MANDA** al cliente, con este criterio —**y es criterio propio, no concepto**—: informar que el contrato **cambió de estado** («entró en prórroga») no es lo mismo que anunciar que **la prenda se va a disponer**. El primero es información que el cliente hoy no tiene y que le sirve para pagar a tiempo; el segundo es el acto. Pero **la frontera entre informar un estado y anunciar una consecuencia patrimonial la pone un abogado, no este documento.** Va en la misma consulta que (a). Si la respuesta es que pesa igual, **no hay rediseño**: R3 ya es una entrada del catálogo y lo apaga el mismo interruptor (§2.2-d, §4.3) — que es, de paso, la prueba de que el mecanismo generaliza.

---

### 12.2 · Resueltas el 24/09/2026 — Mateo delegó el criterio

Mateo pidió resolverlas «como lo haría una app profesional de este tipo». Criterio común: **ningún correo
sin información**, umbrales **configurables por empresa**, y lo que va al **cliente**, conservador. Con esto
**no queda ninguna pregunta de §12.1 abierta del lado de producto**; solo la consulta al abogado.

1. **Cuota:** recordatorio a **3 días** y **el día del vencimiento**. Ya vencida: **máximo uno por semana**,
   en horario hábil, nunca domingo ni festivo — diseñado dentro de la **Ley 2300 de 2023** («dejen de
   fregar»). Si esa ley aplica a una compraventa **va en la misma consulta al abogado** que (a) y la 7.
   Parámetros por empresa; `grace_days` sigue sin reusarse.
2. **Resumen diario:** **solo si hubo actividad o alertas.** Además un **resumen semanal que sale siempre**
   (lunes): prueba que el sistema vive sin entrenar a archivar. Patrón de Square/Toast.
3. **Correos por inquilino:** **no.** La empresa personaliza nombre, logo, teléfono y una línea de cierre;
   el cuerpo es de la plataforma (§4.4).
4. **Umbrales de «descuento grande» y «descuadre grande»:** **configurables por empresa, nacen en 0**
   (se avisa todo). Por debajo del umbral el evento **igual sale en el resumen**; el umbral decide solo la
   alerta inmediata.
5. **`stale_after_days` = 2.**
6. **Cliente por inquilino: confirmado.** Cada compraventa es la *responsable* del dato ante la Ley 1581 y
   Prendo el *encargado*; el opt-out por inquilino es lo correcto, no un bug.
7. **Aviso de prórroga (R3): APAGADO por defecto hasta el concepto del abogado.** Apagarlo cuesta casi nada
   (2 de 16 clientes tienen correo) y quita un riesgo legal sin concepto. Se enciende por empresa con el
   mismo interruptor de `auction_ready_customer`.

**Esto es criterio de producto, no asesoría legal.** La consulta al abogado lleva tres puntos: el aviso de
remate (a), el de prórroga (7) y si la Ley 2300 aplica a los recordatorios (1).

### 12.3 · Las preguntas legales: CERRADAS con criterio del dueño (Mateo, 25/09/2026)

> **Esto es orientación, no un concepto de abogado.** Mateo decidió el criterio el 25/09/2026 sin hacer la
> consulta que §12.2 proponía; este documento lo registra y lo implementa, pero **no lo vuelve una opinión
> legal**. No se citan artículos ni decretos más allá de los nombres de las leyes, por la misma razón de
> §9.2-h. **Recomendación firme: una revisión legal antes de encender cualquier recordatorio en una empresa
> real** (y en particular antes de encender R5). Todo lo de abajo quedó como configuración, así que lo que
> diga esa revisión se aplica sin rediseño.

El 24/09 las tres preguntas quedaron en pausa, con los avisos al cliente construidos y apagados (el texto de
esa pausa se reemplaza por este). El 25/09 Mateo las cerró así:

**1. Ley 2300 de 2023 («Dejen de fregar»): TODO mensaje sobre un pago pendiente es cobranza — R1, R2, R3 y R4.**
La ley alcanza a quien hace gestión de cobranza, directa o indirecta, y no distingue entre recordar antes del
vencimiento y cobrar después: el criterio es que el mensaje trata de un pago que el cliente tiene pendiente.
Por eso los cuatro recordatorios (y R5) caen bajo sus límites, y los límites de fábrica que la fase 1 dejó
como parámetros ya coinciden con ella: **lunes a viernes de 7:00 a 19:00, sábados de 8:00 a 15:00, sin
domingos ni festivos, y máximo un contacto por semana por canal.** Aplican a los cuatro sin excepción.
**Los comprobantes transaccionales (C1–C7) NO son cobranza** —acusan algo que el cliente acaba de hacer— y ya
quedaron fuera del tope semanal en las fases 4 y 6 (§18.1-1); siguen dentro de la ventana horaria, que es la
lectura conservadora que no rompe nada. La consecuencia práctica de aplicar el tope semanal a R1 está en §20.4.

**2. R3 (entró en prórroga) NO pesa como el remate: informa un cambio de estado.** Es la respuesta a §12.1-7.
El correo lo dice: es **informativo** y **no reemplaza lo pactado en el contrato**, que es el que fija plazos
y condiciones. R4 (la prórroga vence pronto) lleva la misma aclaración. Siguen `default_enabled = false`:
cerrar la pregunta legal no enciende nada, porque encender es de cada empresa (§4.3). Esto reemplaza
§12.2-7, que los había dejado apagados *hasta el concepto*.

**3. R5 (`auction_ready_customer`) es un aviso de CORTESÍA, no la notificación formal.**
- **La notificación formal es la que diga el contrato.** En una compraventa con pacto de retroventa la
  propiedad se consolida según lo pactado en el contrato; el correo no es el acto que la consolida ni el
  aviso que el contrato exige, y no puede contradecirlo (§2.2-c).
- **Prueba.** La Ley 527 de 1999 da valor probatorio a los mensajes de datos, pero **que el servidor acepte un
  correo no prueba que el titular lo leyó** — un `sent` (o el futuro `delivered` de Resend) dice que un
  servidor lo recibió, nada más. Si una empresa necesita **prueba de entrega**, lo que sirve es **correo
  electrónico certificado** (por ejemplo 4-72 e-entrega o Certicámara). **Queda anotado como mejora futura, sin
  construir:** sería otro canal (`channel`) sobre los mismos eventos (§4.1-b), con la constancia colgada del
  `provider_id` de la entrega.
- **La plantilla se lo dice al cliente en lenguaje llano:** *«Este es un aviso de cortesía. La notificación
  formal es la que establece su contrato, en la forma y los plazos que allí se pactaron: este correo no
  reemplaza lo pactado en su contrato.»* (`templates.COURTESY_NOTE`).
- **Sigue apagado por defecto y conserva la advertencia al encenderlo** (§2.2-c): la pantalla que lo enciende
  —en el front— muestra lo que asume quien lo enciende. Esta decisión le quita a la advertencia el tono de
  «pregunta sin respuesta», no su razón de ser.

**4. La base legal «contrato» (§9.2) se apoya en una cláusula de autorización de avisos DENTRO del contrato
firmado, más la política de tratamiento de datos (Ley 1581).** No es una casilla nueva ni un cambio de datos:
es qué papel sostiene el valor `email_basis = 'contract'`. El front va a ofrecer esa cláusula como **ejemplo
insertable** en el editor de plantillas de contrato (otro trabajo, en `frontend-starter`); la relación está en
§9.2-i.

## 13. Defectos y cosas de arrastre encontradas al escribir esto

Ninguno bloquea el diseño; todos lo tocan.

| # | Qué | Dónde | Gravedad |
|---|---|---|---|
| 1 | **El backend no valida el formato del correo del cliente.** `email: str \| None` pelado, mientras `identity`/`platform` sí usan `EmailStr`. La validación vive **solo** en el frontend (`zod`), así que cualquier otro cliente de la API —o un script de importación— escribe basura sin resistencia. Es el insumo directo de §9.3 | `app/modules/customers/schemas.py:17` y `:32` vs. `identity/schemas.py:17` | **Media.** Hoy no molesta; el día que se manden correos, molesta |
| 2 | **`company.settings.grace_days` es configuración muerta.** Default `30` desde `00002`, y **ningún código la lee** (grep: solo la migración y un comentario). Peligrosa porque su nombre la vuelve tentadora para otra cosa | `00002_platform.sql:22`; comentario en `company/service.py:72` | Baja — pero anotarla evita reusarla mal |
| 3 | **El aviso de vencimiento de suscripción no existe** y el corte es en seco. `expire_overdue_subscriptions` audita y escribe `subscription_event`, pero nadie le avisó antes al dueño: se encuentra la app cerrada. Es E8, y es el único evento de este documento que hoy se rompe en silencio **del lado de la plataforma** | `platform/service.py:400-438` | **Media** — 2 suscripciones ya `expired` en dev |
| 4 | **La afirmación "el job nocturno no escribe en `audit_log`" es cierta a medias, y la mitad correcta importa.** El **segundo** paso (`expire_overdue_subscriptions`) **sí** audita, con `user_id=NULL`. El que no audita es el **primero**, `recompute_all_statuses` — que es exactamente el que causó el daño de F21-10 y por el que no se pudo saber qué vector escribió cada fila | `nightly.py` · `contracts/service.py:867-895` vs. `platform/service.py:415` | Informativa, pero corrige el relato |
| 5 | **`company.contact_email` está casi vacío** y es el único lugar donde hoy vive un correo de contacto de la empresa. El `Reply-To` de §8 depende de él, así que hay que tratar el caso nulo desde el primer envío, no después | `00002_platform.sql:16` (nullable) | Baja |
| 6 | **La Machine `nightly-job` sigue sin process group, a propósito**, y este documento le agrega un tercer paso — o sea, más responsabilidad sobre la pieza más frágil de la infraestructura. No es un defecto nuevo: es el riesgo conocido que crece. Hay que recrearla en el mismo despliegue y verificar que el `schedule` sobreviva | `ARCHITECTURE.md` §11 · `QA_AUDITORIA.md` F21-10 | **Alta si se olvida** |

---

## 14. Definición de Hecho (cuando se implemente)

- **Migración** con `company_id`, RLS `enable`+`force`, política `tenant_isolation` y su test en `tests/rls/` — una por tabla nueva.
- **Ninguna llamada HTTP dentro de una transacción de negocio.** Test: Resend caído ⇒ el abono se registra igual y su entrega queda `pending`.
- **Idempotencia probada en las dos familias:** correr el job dos veces la misma noche ⇒ un solo correo; correrlo el mes siguiente ⇒ otro correo. Y el `on conflict do nothing` verificado como camino normal, no como excepción (§6.2).
- **La ventana de rezago probada con el escenario real:** job apagado N días, encendido después ⇒ `skipped_stale`, cero envíos, y el conteo visible. **Hay que verlo fallar sin el fix** — la regla dura del proyecto.
- **Un cliente sin correo produce una fila `unroutable`**, nunca una ausencia. Test explícito: es el caso normal (§1).
- **La matriz de §9.2-c probada en sus cuatro casillas:** `service` + base `contract` sale; `marketing` + base `contract` queda `suppressed`; sin base no sale nada aunque haya correo; y `email_opt_out_at` gana sobre cualquier base. **Y el caso que prueba el diseño y no la regla:** cambiar el mapa a `service: ['consent']` ⇒ esos mismos clientes quedan `suppressed`, **sin tocar una migración ni una plantilla**.
- **El evento apagado se prueba apagado y encendido.** Con `auction_ready_customer` en `false`, la noche produce E1 a la empresa y **ninguna** entrega al cliente; con el interruptor en `true`, produce las dos. Un evento que nace apagado y que nadie probó encendido es un evento que no existe — y toda la decisión de §2.2 se apoya en que encenderlo sea configuración.
- **Ni la cédula ni la descripción de la prenda aparecen en ningún cuerpo renderizado.** Test sobre el render, no sobre la plantilla — un test que mira la plantilla no cubre el `payload`.
- **El tope por cliente y día se hace cumplir en un solo lugar**, no en cada productor de eventos. Un punto de verdad, como el alcance de sede en `SUCURSALES.md` §8.4.
- **Códigos de error nuevos en `API_GUIDE.md` §15**, con `tests/unit/test_error_catalog.py` en verde **en las dos direcciones** — un código sin documentar rompe la suite. Previsibles: `NOTIFICATIONS_DISABLED`, `CUSTOMER_NOT_NOTIFIABLE`, `NOTIFICATION_ALREADY_SENT`.
- **Permisos nuevos en el seed** (`notifications.receive_digest`, `notifications.receive_alerts`) y en el mapa de `scripts/qa/map_endpoints.py`.
- **Etiquetas en español** para las acciones nuevas de `audit_log` en `frontend-starter/src/features/audit/labels.ts` — si no, la pantalla muestra `resend_notification` en crudo. Ya pasó con doce acciones.
- **Verificado en vivo, no solo en tests:** un correo real recibido, con el remitente de §8 tal como se ve en Gmail y en Outlook. *"Push ok" no prueba nada.*

---

## 15. Fase 1 — lo implementado (24/09/2026)

**Migración `00058_notifications.sql`** (aplicada y probada solo en local): tres tablas —`notification_event_type`
(el catálogo, global, como `permission`), `notification_event` y `notification_delivery`— con RLS `enable`+`force` y
`tenant_isolation` en las dos por empresa, y los permisos `notifications.receive_digest` / `notifications.receive_alerts`
sembrados al rol con `identity.manage_roles` de las empresas existentes. Aditiva: se puede aplicar antes del deploy.

**Código:** `app/modules/notifications/` (`catalog`, `preferences`, `limits`, `templates`, `providers`, `service`,
`digest`, `dispatcher`, `router`), `app/common/co_holidays.py`, `app/modules/contracts/integration.py` y dos funciones
nuevas en `reports/integration.py`. El job nocturno tiene ahora cuatro pasos (ARCHITECTURE §11).

### 15.1 · Qué quedó

| Pieza | Cómo quedó |
|---|---|
| **Catálogo** | Los 19 tipos de §2 desde el día uno, en la tabla y en `catalog.py` (un test exige que coincidan en las dos direcciones). **Los 12 al cliente (C1–C7, R1–R5 incluido `auction_ready_customer`) nacen `default_enabled = false`** (§12.3). Resúmenes y alertas a la empresa, `true`. `purpose` sin default |
| **Preferencias** | `company.settings.notifications`: `enabled` (interruptor general, **apagado**), `events.<code>` (override del catálogo), `thresholds` (descuento y descuadre, **nacen en 0**), `customer_contact_limits` (Ley 2300), `stale_after_days` (**2**). Faltante = default; nada exige backfill |
| **Resumen** | Paso 3 del job, después de `recompute_all_statuses`. Secciones: E1 (reusa `repository.list_ready_for_auction`, el predicado de `GET /contracts/ready-for-auction`), E2, E3, E4, E8 (15/7/1 por cruce de hito), descuentos, movimiento del período, entregas `dead`; el semanal suma E5 y E7 |
| **Diario / semanal** | El diario se **registra siempre** (latido del job, §5.3) y **sale solo con actividad o alertas nuevas** desde la corrida anterior. El semanal **sale siempre**: el lunes, o en la primera corrida de la semana si el lunes no hubo; ese día el diario va adentro y no sale aparte |
| **Umbrales** | Por empresa, nacen en 0. Lo que está por debajo **igual sale** en el resumen; el umbral solo pone la marca «⚠ sobre el umbral» (y decidirá la alerta inmediata de la fase 7) |
| **Idempotencia** | `unique(company_id, dedupe_key)` + `on conflict do nothing` como camino normal. Llaves: `digest:<empresa>:<día>`, `weekly_digest:<empresa>:<lunes>`, `auction_ready:<contrato>:<extension_ends_at>` |
| **Despachador** | Paso 4 del job. Único lugar donde se aplican rezago, límites al cliente y tope (§14). Reintentos +1 h/+6 h/+24 h y `dead` al cuarto; `for update skip locked`; `Idempotency-Key` de Resend = la entrega; `sending` colgado >1 h vuelve a `failed` |
| **Ley 2300** | Parámetros en `customer_contact_limits`, activos para `audience='customer'` y sin efecto para la empresa: L-V 7:00–19:00, sáb 8:00–15:00, sin domingos ni festivos colombianos (calculados, Ley Emiliani + Pascua), máx. 1 por semana y 3 por día por destinatario y empresa. Fuera de horario la entrega se corre al próximo momento hábil; pasado el tope, `throttled` |
| **Proveedor** | `ResendProvider` (HTTP, `RESEND_API_KEY`), `NullProvider` sin key → la entrega queda **`skipped_no_provider`** y el job sigue; `RecordingProvider` en tests. Remitente `notificaciones@prendo.com.co` (`NOTIFICATIONS_FROM_ADDRESS`) |
| **Remitente** | Resumen: `"Prendo" <notificaciones@…>` (el destinatario es un usuario de Prendo, §8). Cliente: `"<Empresa> (vía Prendo)"`, asunto sin «Prendo», `Reply-To` = `contact_email` o ninguno |
| **Endpoints** | `GET`/`PATCH /api/v1/notifications/settings` y `GET /api/v1/notifications/deliveries`, los tres con `company.configure`; el cambio se audita como `update_settings` (módulo `notifications`) con antes y después. Contrato en `API_GUIDE.md` §13-ter |

### 15.2 · Discrepancias: dónde el código contradijo este documento (y ganó)

1. **E2 no sale "del delta que escribió `recompute_all_statuses`"** (§2.4). Esa función devuelve un entero, y el recálculo al abrir un contrato (`get_contract`) ya persiste el cambio antes que el job: un contrato que alguien miró en el día desaparecería del resumen. El día de entrada se **deriva** del ancla con `rules.add_months` (mora = `interest_paid_until + 1 mes`; prórroga = `+ arrears_window_months`), igual que `compute_status`.
2. **E4 no lee `cash_movement` tipo `adjustment`** (§2.4). Desde `00048` esos ajustes van con `session_id = NULL`; el descuadre del cierre vive en `cash_session.difference` (+ `difference_reason`), que es lo que se lee.
3. **E5 "cuentas por pagar vencidas" no existe como dato:** una compra a crédito no guarda fecha de vencimiento. El semanal reporta el total y la franja de más de 60 días de `GET /reports/payables`.
4. **E6 (cuentas `settlement` sin liquidar hace N días) no se implementó:** no hay forma barata de fechar desde cuándo una cuenta tiene saldo. Queda para cuando se haga la fase 7.
5. **El interruptor de empresa gobierna TODO, también el resumen.** §4.3 lo describe como «¿este negocio le escribe a sus clientes?», pero §11 pide para la fase 1 «el interruptor por empresa apagado». Se resolvió así: `enabled` general, apagado, y el resto por evento. Motivo: el deploy no puede, solo, empezar a escribirle a los administradores de las 7 empresas de dev — dos son laboratorios de QA con correos inventados, y el primer rebote se paga en la reputación del dominio.
6. **§4.1 se amplió:** tabla de catálogo propia; `notification_event.target_date` (la fecha de la que habla el aviso, para la ventana de rezago); `notification_delivery.recipient_user_id`; `scheduled_at not null default now()`; `unique nulls not distinct (event_id, channel, to_address)`; y el estado **`skipped_no_provider`**, que §4.2 no tenía.
7. **Un aviso al cliente encendido hoy nace `suppressed`, no `pending`.** `customer.email_basis` es de la fase 3 y no existe; con la matriz de §9.2-c, sin base no sale nada. Encender `auction_ready_customer` produce las dos entregas que pide §14 (la de la empresa y la del cliente), pero la del cliente queda `suppressed` (o `unroutable` si no tiene correo). Es a propósito: encender un evento no puede adelantarse a la base legal que lo sostiene.
8. **`bounced`/`delivered` no se escriben todavía:** exigen el webhook de Resend. Un rechazo permanente de la API (4xx que no sea 401/403/429) va directo a `dead`, no a `bounced` — no es un rebote.
9. **El semanal sale en la primera corrida de cada semana** (no estrictamente el lunes) para que un lunes perdido no se coma la semana. Consecuencia: la primera noche tras el deploy sale un semanal, sea el día que sea.
10. **La hora del job no es fija:** `--schedule daily` de Fly no fija la hora, así que el resumen puede llegar a cualquier hora. Al cliente lo protege la ventana horaria del despachador; a la empresa no se le aplica.
11. **Las alertas A1–A4 y P1 existen en el catálogo pero sin productor.** `notifications.receive_alerts` ya está sembrado. → P1 tiene productor desde la fase 2 (§16); A1–A4, desde la fase 7 (§19).

### 15.3 · Lo que NO quedó (y en qué fase cae)

- Ningún evento al cliente tiene **productor** salvo `auction_ready_customer` (§14 lo pide probado encendido y apagado): C1–C7 y R1–R4 están en catálogo y plantilla, sin disparo. → C1–C7 tienen productor desde las fases 4 y 6 (§18); R1–R4 siguen sin él (fase 5).
- Webhook de Resend (`delivered`/`bounced`, `customer.email_invalid_at`), `resend_notification`, enlace de baja, `email_basis` y `EmailStr` del cliente: fase 3.
- `BackgroundTasks` para los transaccionales (§5.1): no hay transaccionales todavía. → Lo estrenó la invitación en la fase 2, y el diseño no sobrevivió intacto: §16.2-1.
- ~~Pantalla del front~~ **Ya existe** (corregido el 24/09/2026): `/configuracion/notificaciones`, commit `5146ee1` de `frontend-starter`. La etiqueta nueva de auditoría no hace falta: se reusó la acción `update_settings`.
- **Verificado en vivo** (§14, último punto): pendiente — exige la key en Fly y un correo real recibido en Gmail y Outlook.
- **Por verificar antes de encender al cliente:** que los horarios y el «uno por semana» sean los de la Ley 2300 (son mi lectura de la ley, no un concepto); y el tope diario del plan de Resend (§10).

---

## 16. Fase 2 — lo implementado (24/09/2026)

**Sin migración.** Todo cupo en `00058`: el tipo `user_invitation` ya estaba en el catálogo (`audience='platform'`),
`notification_delivery.recipient_user_id` ya existía y los estados alcanzaban. Commit `fbf7b8a`.

**Código:** `identity/auth_admin.py` (el `Invitation` trae `hashed_token` e `invited_at`; `invitation_email_link`;
`auth_user_exists`), `identity/integration.py` (la decisión de canal y `fresh_invitation_link`),
`notifications/integration.py` (nuevo), `notifications/dispatcher.py` (`dispatch_delivery`, `send_after_commit` y el
paso propio de la invitación), `templates.render_user_invitation`, `preferences.event_enabled`, y los routers de
`identity` y `platform`. Tests: `tests/integration/test_invitation_email.py` (13) y
`tests/unit/test_user_invitation_mail.py` (15).

### 16.1 · Qué quedó

**El flujo, con `send_email: true` (el default de `POST /identity/invitations`):**

```
request ── ¿hay RESEND_API_KEY y FRONTEND_URL? ──no──► POST /auth/v1/invite  (correo de Supabase, como antes)
                   │ sí
                   ▼
      POST /auth/v1/admin/generate_link  (type=invite, SIN correo → id, hashed_token, invited_at)
      ┌─ transacción de la invitación ───────────────────────────────────────────┐
      │ app_user (invited) + audit_log (delivery: "email")                       │
      │ notification_event (user_invitation, payload {}) + delivery (pending)    │
      └─ COMMIT explícito (§16.2-1) ─────────────────────────────────────────────┘
                   ▼
      BackgroundTasks → dispatch_delivery(id, enlace EN MEMORIA) → Resend → sent | failed
                   ▼  (si no salió)
      job nocturno → ¿sigue invited? → ¿existe la cuenta en Auth? → generate_link NUEVO → Resend
```

| Pieza | Cómo quedó |
|---|---|
| **El enlace del correo** | `{FRONTEND_URL}/auth/callback?token_hash=<hashed_token>&type=invite` — **la misma forma** que ya entrega «Generar enlace» (`auth_admin._app_link`). `/auth/callback` lo canjea con `verifyOtp({token_hash, type})`, un POST. Nunca el `action_link` de GoTrue (`/auth/v1/verify?token=…`), que es el GET de un solo uso que los escáneres queman (03/09/2026). **La plantilla lo hace cumplir**: si el enlace no es `/auth/callback?token_hash=…`, o trae `/auth/v1/verify` o un `#`, no redacta (`ValueError` → `dead`). Es el último punto por donde pasa todo correo, así que el candado vale aunque un productor futuro se equivoque |
| **El token no se guarda nunca** | Ni en `payload` (va vacío), ni en `last_error`, ni en `audit_log`. El envío inmediato lo recibe en memoria. Un test busca el token en todas las columnas de la entrega y del evento |
| **El job como red** | Si el envío inmediato no ocurrió (máquina apagada, §5.1) o falló, la entrega queda `pending`/`failed` y el barrido la toma. Como no hay token guardado —y aunque lo hubiera, `otp_expiry` es de 1 h en la config local de Supabase—, el despachador pide uno **nuevo** para la misma cuenta. Antes comprueba dos cosas, en este orden: que el `app_user` siga `invited` (si ya entró por «Generar enlace» o lo desactivaron → `suppressed`, sin llamar a Supabase) y que la cuenta de Auth exista (`GET /auth/v1/admin/users/{id}`; si no → `dead`, §16.2-9) |
| **Regenerar con `invite`, no con `recovery`** | Verificado contra GoTrue v2.195.0 local: regenerar un tipo invalida **solo** los tokens anteriores de ese tipo (`invite` nuevo ⇒ el `invite` viejo da 403 `otp_expired`; un `recovery` generado en medio no afecta al `invite`, y viceversa). «Generar enlace» usa `recovery` para rescatar a un invitado: si el job regenerara `recovery`, **mataría el enlace que el admin quizá ya mandó por WhatsApp** mientras el correo esperaba. P2 no se toca (§2.6) |
| **Resultados de Supabase al regenerar** | 422 `email_exists` (la persona ya puso contraseña pero todavía no hizo un request que la pase a `active`) → `suppressed`. 429 o 5xx → reintentable, **con el mismo contador y backoff** que un fallo de Resend (+1 h/+6 h/+24 h, `dead` al cuarto). Sin `FRONTEND_URL` → `dead` |
| **Sin proveedor (decisión)** | **La invitación vuelve al correo de Supabase de siempre**, y se decide ANTES de llamar a Supabase: la llamada misma cambia (`/invite` manda correo, `generate_link` no). Descubrirlo después dejaría una cuenta creada con un enlace que nadie recibe. Lo mismo sin `FRONTEND_URL`: no hay enlace seguro que armar, y un `action_link` en un correo es peor que el correo de Supabase (que al menos es el comportamiento conocido). Queda dicho en tres lugares: `invite_delivery: "email_supabase"` en la respuesta, `delivery: "email_supabase"` en el `audit_log`, y **ningún** evento en `notification_event` (§16.2-7) |
| **Por qué no `skipped_no_provider`, como el resumen** | Porque las consecuencias no se parecen. Un resumen que no sale es un correo de menos; una invitación que no sale es **una persona que no puede entrar**, y el admin, que ya vio «invitado», no tiene cómo saberlo. Volver a Supabase conserva el límite de siempre (`INVITE_RATE_LIMITED`), pero ese sí es ruidoso: el admin ve el 429 en el momento |
| **El interruptor de la empresa** | **No gobierna los eventos de plataforma.** `preferences.event_enabled` y `event_setting` devuelven el `default_enabled` del catálogo para `audience='platform'`, ignorando `enabled` y cualquier override en el jsonb (§16.2-5). Una sola línea de verdad, que usan `record_event`, el despachador y el `GET /notifications/settings` (`effective: true`) |
| **Idempotencia** | `dedupe_key = invitation:<user_id>:<invited_at>`. El usuario solo no alcanza: una segunda invitación a la misma persona (hoy la bloquea `USER_ALREADY_INVITED`, pero «reenviar invitación» es la evolución obvia) es un hecho **nuevo**, y `on conflict do nothing` se la tragaría en silencio. `invited_at` lo pone GoTrue en cada invitación (respuesta real de `generate_link`), así que la misma invitación da la misma llave y la siguiente otra. Sin `invited_at`, cae a `invitation:<user_id>` |
| **Idempotency-Key de Resend** | `delivery-<id>` en el envío inmediato; **`delivery-<id>-a<intento>` cuando el enlace se regeneró** (§16.2-4) |
| **Remitente y plantilla** | `"Prendo" <notificaciones@prendo.com.co>`, sin `(vía …)` y sin `Reply-To` (§8: la contraparte de un usuario es Prendo). Asunto `Invitación a <Empresa> en Prendo`. Cuerpo: desde el 25/09/2026 es el de la plantilla «Invite user» de Supabase, en *tú* y con la empresa nombrada (§8.1). **Solo** el nombre de la empresa y el del invitado: ni teléfono ni `footer_note` del inquilino, ni rol, ni quién invitó. Texto + HTML, todo valor escapado |
| **Alta de empresa** | `POST /platform/companies` con `send_email: true` pasa por la misma `identity.integration.invite_user`, así que hereda todo. El default sigue siendo `false` (el enlace vuelve en `admin_invite_link`) |
| **«Generar enlace» (P2)** | Sin cambios: `send_email: false` no crea evento ni correo, y `POST /users/{id}/recovery-link` no se tocó |
| **Respuesta** | `InvitedUserOut.invite_delivery`: `link` \| `email` \| `email_supabase`. Aditivo; el front puede usarlo para decirle al admin por dónde buscar si «no llegó» |

**Operación — lo que hace falta en Fly para que esto se encienda:** `RESEND_API_KEY` **y** `FRONTEND_URL` como secretos
**de la app del API** (no solo del job): el envío inmediato corre en el proceso web. Sin cualquiera de las dos, todo
sigue como antes (correo de Supabase). No hay interruptor por empresa que encender.

### 16.2 · Discrepancias: dónde el código contradijo este documento (y ganó)

1. **§5.1 «el envío va en un `BackgroundTasks`, después del commit» no es cierto por defecto.** En FastAPI 0.141 la salida de la dependencia con `yield` —el `session.begin()` de `get_db`, que es quien commitea— corre **después** de las tareas de fondo: las dos viven en el mismo `AsyncExitStack` del request (`fastapi/routing.py`, `request_response`). El despachador, en otra conexión, no veía la entrega, no mandaba nada, y el correo esperaba al job. **Silencioso**: el test lo cazó (se vio fallar sin el arreglo). Arreglo: `dispatcher.send_after_commit` hace `db.commit()` explícito y recién ahí agenda. Descartado: cambiar `get_db` a `Depends(scope="function")`, que toca todos los endpoints para arreglar dos. Anotado en `ARCHITECTURE.md` §4 como regla para el próximo productor transaccional.
2. **§4.1 dice que los eventos de plataforma «se escriben con la sesión de bypass».** La invitación desde `identity` se escribe con la sesión **tenant** (RLS encima): su `company_id` es la del admin que invita, y `tenant_isolation` la deja pasar. Solo el alta de empresa escribe con bypass. Es mejor así: un bug no puede escribir la invitación en otra empresa.
3. **§4.1 «el payload lleva lo mínimo para redactar»: acá no puede.** Lo único imprescindible para redactar una invitación es el enlace, y el enlace es una credencial que vence. El payload va **vacío**; el nombre se lee de `app_user` al enviar y el enlace llega en memoria o se regenera.
4. **§15.1 «`Idempotency-Key` de Resend = la entrega» no sirve para la invitación reintentada.** Con el enlace regenerado el cuerpo es otro, y Resend responde **409 `invalid_idempotent_request`** si una llave se reusa con otro payload dentro de 24 h (documentación de Resend, «Idempotency keys») — la invitación iría a `dead`. La llave es por intento. **El costo, dicho:** si un envío sí salió pero el proceso murió antes de registrarlo (`sending` colgado), el reintento manda un segundo correo con otro enlace, y el primero queda muerto (regenerar `invite` mata el anterior). La persona recibe dos; el último sirve, y el primero, al abrirlo, dice «Este enlace ya se usó».
5. **§15.2-5 «el interruptor de empresa gobierna TODO».** Para la plataforma, no: ver §16.1. El argumento de §15.2-5 —el deploy no puede empezar a escribirle solo a 7 empresas— no aplica, porque la invitación no la dispara el deploy: la dispara un admin, invitando.
6. **§15.1 «sin key → `skipped_no_provider` y el job sigue».** Para la invitación la decisión es previa (Supabase manda el correo). Queda un único caso donde una invitación termina `skipped_no_provider`: la key se quitó **entre** la invitación y el reintento del job. En ese caso el despachador **no** regenera el enlace (mataría el anterior para no mandar ninguno) y la invitación queda muda; el admin la rescata con «Generar enlace». Caso de borde, aceptado.
7. **§4.1 «el hecho se escribe SIEMPRE, incluso sin por dónde avisar» — no en el respaldo por Supabase.** En este sistema un evento sin entregas significa «apagado» (§4.3). Registrar la invitación que mandó Supabase como un evento sin entrega diría lo contrario de lo que pasó. El rastro de ese caso es el `audit_log` (`delivery: "email_supabase"`), que ya existía.
8. **§6.1 no tenía llave para la plataforma.** Quedó `invitation:<user_id>:<invited_at>` (§16.1).
9. **Un hallazgo que el diseño no preveía: `generate_link` con `type=invite` sobre una cuenta borrada desde el panel de Supabase no falla — crea otra**, con otro id, huérfana (ningún `app_user` la referencia) y que bloquea ese correo para invitaciones futuras (`EMAIL_ALREADY_REGISTERED`). Por eso el job pregunta primero `GET /auth/v1/admin/users/{id}` (404 `user_not_found`, respuesta real) y, si no existe, deja la entrega `dead` con el motivo (`AUTH_ACCOUNT_MISSING`), sin llamar a `generate_link`.
10. **§8 «correos de la plataforma: remitente Prendo, sin nombre de inquilino»** — el remitente sí; el **asunto y el cuerpo** llevan el nombre de la empresa. Es lo único que la persona reconoce («me invitaron a la compraventa donde trabajo»); un correo de «Prendo» a secas, de una marca que nunca oyó, es exactamente el que §8 dice que se lee como phishing.

### 16.3 · Lo que NO quedó, y lo dudoso

- **Riesgo residual del enlace, en el FRONT (no se tocó: hay otro agente ahí).** `AuthCallbackPage` canjea el `token_hash` **al montar** (`useEffect` → `verifyOtp`), sin que la persona toque nada. El POST protege contra lo que hace GET y no ejecuta JavaScript (vista previa de WhatsApp/Telegram, la mayoría de escáneres). **No protege contra un escáner que abra la página en un navegador real y ejecute el JS** — lo que hacen algunos sandboxes corporativos (Outlook Safe Links con «detonación», antivirus de gateway). Ese escáner quemaría el enlace igual que el `action_link`. **No verificado** si alguno de los buzones reales de los clientes hace eso. La mitigación es del front: pedir un clic («Continuar») antes de `verifyOtp`. Queda anotado para quien consolide.
- **El respaldo por Supabase conserva los dos problemas de siempre**: su plantilla lleva el `action_link` (quemable) y depende de la lista de Redirect URLs (`RUNBOOK_USUARIOS.md` §3). Solo aplica sin `RESEND_API_KEY`/`FRONTEND_URL`.
- **Verificado en vivo: pendiente.** Exige los dos secretos en Fly y un correo real recibido en Gmail y Outlook (§14). No se desplegó nada.
- **Suposición no verificada: que `generate_link` no tenga su propio límite en el proyecto hosted.** En local, varias llamadas seguidas respondieron sin 429; el límite conocido (`INVITE_RATE_LIMITED`) es el del envío de correo. Si el hosted limitara también `generate_link`, el 429 sigue saliendo como `INVITE_RATE_LIMITED` en el request (mismo contrato que antes) y como reintento en el job.
- **Suposición no verificada: la duración real del token en dev/prod.** `otp_expiry = 3600` es la config LOCAL (`supabase/config.toml`); no miré la del proyecto hosted. El correo no promete una duración («vence en poco tiempo») por eso mismo.
- **El front no muestra `invite_delivery`.** El diálogo de invitar sigue sin decir por dónde salió.
- **`RUNBOOK_USUARIOS.md` (raíz) quedó desactualizado** en sus filas de «No llega el correo» / `INVITE_RATE_LIMITED`: con proveedor, el correo ya no depende del SMTP de Supabase. No lo toqué (está fuera del repo y lo consolida Mateo).
- **Webhook de Resend** (`delivered`/`bounced`): sigue en la fase 3. Una invitación a una dirección mal escrita queda `sent` y nadie se entera — el admin lo notará porque la persona no aparece.

---

## 17. Fase 3 — lo implementado (25/09/2026)

**Migración `00059_customer_email_basis.sql`** (aplicada y probada solo en local). Commits: `da76b63` en
`backend-starter`; `2f022dd` y `35b1280` en `frontend-starter`. **Ningún aviso al cliente se encendió**: siguen
`default_enabled = false` por catálogo y el interruptor por empresa sigue apagado (§12.3). Lo que cambió es que, el
día que alguien encienda uno, ya hay con qué decidir a quién se le puede escribir.

### 17.1 · Qué quedó

| Pieza | Cómo quedó |
|---|---|
| **Columnas** | `customer.email_basis` (`contract` \| `consent` \| null), `email_basis_at`, `email_consent_at`, `email_consent_source` (`counter` \| `contract_form` \| `import`), `email_opt_out_at`, `email_invalid_at`. Tres `check` que el esquema garantiza solo: base ⇔ fecha; `consent` exige cuándo y dónde; una fecha de autorización no puede colgar de otra base. Y `notification_delivery.legal_basis` (§17.2-2) |
| **Backfill** | `contract` + `email_basis_at = now()` en los clientes con correo no vacío, sin base y con al menos un contrato **no terminal** (`paid`, `auctioned`, `superseded` son terminales, los de `rules.TERMINAL_STATUSES`). Nadie queda en `consent`: nadie autorizó nada todavía (§9.2-g). Verificado con un escenario sembrado en local antes de aplicarla: de 4 clientes (correo + mora, correo + pagado, sin correo + vigente, correo en blanco + vigente) tocó exactamente al primero |
| **Medido en LOCAL** | 1.146 clientes (casi todos basura de tests), 3 con correo, **ninguno con contrato vivo** → el backfill no tocó ninguno: **1.146 sin base, 0 `contract`, 0 `consent`**. En dev **no se midió** (prohibido tocarla en esta fase); por §1 y §10, a lo sumo 2 clientes tendrían `contract` — los 2 con correo, si su contrato sigue vivo |
| **La matriz** | `service.customer_gate(contacto, finalidad)` es **el único lugar** donde se cruza la base con `purpose` (§9.2-c): sin dirección → `unroutable`; baja → `suppressed`; rebote → `suppressed`; base que el mapa no acepta → `suppressed`; si no, sale, y la base queda en la entrega. El mapa sigue siendo `catalog.PURPOSE_ACCEPTED_BASES` (§9.2-d) y el test de «abogado estricto» lo cambia en memoria sin tocar nada más |
| **Al planificar Y al enviar** | `record_event` usa el `gate` al crear la entrega, y el despachador lo **vuelve a evaluar** en `_prepare`, antes de los límites de la Ley 2300: una baja por el enlace o una casilla desmarcada en el medio surten efecto ya. Además, si el correo del cliente **cambió** desde que se planificó, la entrega queda `suppressed` (§17.2-7) |
| **Casilla del mostrador** | `email_consent` en `POST`/`PATCH /customers`: `true` → `consent` + fecha + `counter`, **conservando la fecha original** si ya la tenía; `false` → retira, y la base cae a `contract` si hay contrato vivo y correo, o a ninguna. `email_opt_out` en el `PATCH`: la baja pedida en persona, y levantarla. Todo en el `audit_log` de `create_customer`/`update_customer`, con antes y después |
| **`contract` lo escriben** | `customers.integration.ensure_contract_basis`, llamada en la MISMA transacción por `create_contract`, `import_contract` y `extend_loan`, y por el `PATCH` del cliente cuando se le registra un correo y ya tenía un contrato vivo. Solo si tiene correo y **ninguna** base: nunca pisa `consent` |
| **Enlace de baja** | Token sin estado: `base64url(v1 ‖ company_id ‖ customer_id).base64url(HMAC-SHA256[:16])`, firmado con `NOTIFICATIONS_LINK_SECRET` (nuevo). No vence, no se guarda en ninguna fila. El correo lleva `{FRONTEND_URL}/baja/{token}` — **la página, nunca la API** — en el HTML y en el texto plano |
| **La baja** | `GET /api/v1/public/unsubscribe/{token}` **solo lee** (`{company_name, email_hint, unsubscribed_at}`, correo enmascarado `j•••@gmail.com`). `POST` al mismo path escribe `email_opt_out_at`, idempotente (repetirlo devuelve la fecha original y no audita otra vez), y audita `email_opt_out` con `user_id` NULL y `source: "link"`. Token malo, cliente o empresa inexistente, o plataforma sin secreto → `404 UNSUBSCRIBE_LINK_INVALID`, un solo código para todo |
| **Plantilla** | Todo correo al cliente lleva «¿No quiere recibir más avisos de <Empresa> por correo? Darse de baja». **Sin enlace no se redacta**: `templates._check_unsubscribe_url` exige `/baja/` y rechaza `/api/` o `#`, igual que el candado del enlace de la invitación (§16.1). El despachador, si no puede armarlo (falta el secreto o `FRONTEND_URL`), deja la entrega `dead` con el motivo |
| **Correo del cliente** | `CustomerCreateIn.email` sigue `EmailStr`. `CustomerUpdateIn.email` pasó a `str` con `format: email` en el OpenAPI y se valida en el servicio con el **mismo** `EmailStr` y el **mismo** `422 VALIDATION_ERROR` (`email` en `loc`), salvo el valor **idéntico** al guardado (§17.2-1). Un correo nuevo limpia `email_invalid_at` |
| **Front** | Casilla y baja en el formulario del cliente; la base, en la ficha; la página pública `/baja/$token` (abrirla no da de baja: el botón hace el `POST`). Detalle en `frontend-starter/docs/IMPLEMENTATION.md` |

### 17.2 · Discrepancias: dónde el código contradijo este documento (y ganó)

1. **§11 (fila 3) y §13-1 piden «el `EmailStr` que falta». Ya no faltaba:** lo puso F21-19 el 23/09/2026 (commit
   `989d19a`, `QA_AUDITORIA.md`), después de escrito este documento. Lo que sí faltaba era su borde: **un correo
   guardado antes de la validación congelaba la ficha**, porque el formulario lo reenvía tal cual y el `EmailStr`
   del `PATCH` lo rechazaba — no se podía corregir ni el teléfono. Resuelto aceptando el valor **idéntico** al
   guardado y validando cualquier otro (backend y front, la misma regla). **Cuántos hay:** en local, 0 de 3; en dev,
   0 de 2 según la medición de solo lectura de F21-19 (23/09) — no se volvió a medir. La regla es para prod, que
   nadie midió; con 0 casos conocidos no hacía falta un script de limpieza.
2. **§9.2-a se amplió con dos columnas.** `email_basis_at`: la base `contract` no tenía ninguna fecha que dijera
   desde cuándo rige, y §9.2-a exige «poder mostrarlo seis meses después». Y `notification_delivery.legal_basis`:
   una columna del **cliente** dice la base de hoy, no la del día del envío — si mañana pasa de `contract` a
   `consent`, la anterior se pierde. La de la entrega se escribe al planificar y se refresca al enviar.
3. **§9.2-a: «de ahí en adelante lo pone `create_contract`».** También `import_contract`, `extend_loan` y el
   `PATCH` del cliente que le registra un correo teniendo un contrato vivo. Sin lo último, el caso normal de §1c —el
   correo llega después del contrato— dejaba al cliente sin base para siempre.
4. **§9.2-f: la casilla va «al crear el contrato».** Quedó en el **formulario del cliente** (origen `counter`). La
   pantalla de crear contrato elige un cliente existente (`CustomerPicker`) y no tiene formulario de cliente; meterle
   uno era rediseñar esa pantalla. `contract_form` existe como valor permitido y hoy nadie lo escribe. Lo mismo para
   el *«¿quiere recibir avisos de su cuota por correo?»* de §1c: **no se construyó**.
5. **Retirar la autorización no estaba definido.** Quedó así: la base cae a `contract` si hay contrato vivo y
   correo, o a ninguna; `email_consent_at`/`_source` vuelven a null (el `check` lo exige: una fecha de autorización
   no puede colgar de otra base), y el historial queda en `audit_log`. **La baja es otra cosa**: no toca la base, la
   tapa — levantarla devuelve lo que había.
6. **§9.2-e: «el enlace escribe `email_opt_out_at`».** No: el enlace abre una **página** y la escribe el `POST` de
   su botón. Regla dura del proyecto desde el 03/09/2026; la página del front además espera el clic, por la lección
   de `/auth/callback` (§16.3).
7. **Un caso que el diseño no preveía: el correo cambió entre planificar y enviar.** La entrega guarda la dirección
   del día que se planificó. Mandarla a la vieja puede ser mandarla a otra persona (§9.3); mandarla a la nueva es
   mandarla a una dirección sobre la que nadie decidió. → `suppressed` con el motivo. La comparación ignora
   mayúsculas.
8. **§15.2-7 quedó superada.** «Un aviso al cliente encendido hoy nace `suppressed`» era porque no existía la base;
   ahora un cliente con base `contract` recibe el de servicio. El test de §14 (evento encendido ⇒ dos entregas) se
   actualizó: la del cliente con base nace `pending`, y el caso «tiene correo y ninguna base» tiene su propio test.
9. **La salida nueva tiene un modo de falla nuevo, a propósito.** Sin `NOTIFICATIONS_LINK_SECRET` o sin
   `FRONTEND_URL`, los correos al cliente quedan `dead` («sin enlace de baja no sale»). Es el mismo criterio de
   §9.2-e —un correo sin salida es el que termina en spam, y esa marca la paga `prendo.com.co` para todos— y el de la
   invitación sin enlace seguro (§16.1). Hoy no afecta nada: no hay avisos al cliente encendidos.
10. **El pie viejo decía «si no desea recibir estos avisos, avísele a <Empresa>».** Se reemplazó por el enlace: era
    exactamente el «no encuentra cómo salir» que §9.2-e quería evitar.
11. **`email_basis_at` del backfill es la hora de la migración**, no la del contrato: es cuándo se escribió de verdad,
    y fabricar una fecha anterior es lo mismo que §9.2-g prohíbe para `consent`.

### 17.3 · Operación — lo que hace falta para desplegarla

- **`NOTIFICATIONS_LINK_SECRET`** nuevo, largo y aleatorio, **distinto por ambiente**, en la app del API (el endpoint
  público lo necesita para validar) **y** en la Machine del job (el despachador lo necesita para firmar).
  `FRONTEND_URL` también en las dos. Cambiar el secreto invalida los enlaces de los correos ya enviados: rotarlo solo
  si se filtró. `.env.example` lo documenta.
- La migración es **aditiva**: el código viejo no lee estas columnas. Se puede aplicar antes del deploy — con la
  salvedad de siempre: `db push` aplica todo lo pendiente junto.
- **El front tiene que estar desplegado antes de encender cualquier aviso al cliente**: el enlace del correo apunta a
  `/baja/{token}`, y si esa ruta no existe el cliente cae en el 404 de la app.

### 17.4 · Lo que NO quedó, y lo dudoso

- **La captura al crear el contrato (§1c, §9.2-f)** — ver §17.2-4.
- **La lista «clientes sin correo» (§1c)** — no se construyó.
- **Webhook de Resend:** `email_invalid_at` existe y el `gate` lo respeta, pero **nadie lo escribe todavía**.
- ~~**Cabeceras `List-Unsubscribe` / `List-Unsubscribe-Post` (RFC 8058)** no se agregaron.~~ **Hechas el 25/09/2026**,
  ver §17-bis.
- **El texto de la casilla es de producto, no legal.** Dice qué cubre y que se puede retirar; si la Ley 1581 exige
  otra redacción para que la autorización sea «previa, expresa e informada», es la consulta de §9.2-h y §9.3. Cambiarlo
  es texto del front, sin migración.
- **Volver a suscribirse solo en el mostrador.** La página de baja no ofrece deshacer. Sería otro `POST`, tan seguro
  como el de la baja; se dejó fuera por alcance, no por riesgo. Hoy la persona lo pide en la compraventa y se
  desmarca la casilla.
- ~~**El endpoint público no tiene límite de tasa.**~~ **Tiene uno desde el 25/09/2026**, en memoria y por máquina —
  ver §17-bis.
- **El correo enmascarado muestra el dominio completo.** Suficiente para reconocerse; a quien tenga el enlace
  reenviado le dice el proveedor de correo de la persona, no más.
- **Verificado en vivo con un correo real: pendiente**, como en §15 y §16 — exige la key de Resend y el secreto en Fly.
  Verificado en local: la página de baja a 360 y 1280 px contra el backend y la base locales, tres `GET` sin tocar la
  baja, el `POST` con su `audit_log`.


## 17-bis. La baja de un clic y el límite de tasa del enlace — lo implementado (25/09/2026)

Los dos pendientes de §17.4 que tocaban el endpoint público de baja. **Sin migración.** Código:
`unsubscribe.list_unsubscribe_headers`, el campo `headers` de `providers.EmailMessage` (viaja a Resend en el campo
`headers` del cuerpo), `dispatcher._prepare`, `router.public_router` y `app/common/rate_limit.py` (nuevo). Tests:
`tests/unit/test_rate_limit.py` (4), tres en `test_unsubscribe_token.py`, uno en `test_resend_provider.py`, cuatro en
`tests/integration/test_email_basis.py` y dos aserciones en `test_notifications.py` (el correo al cliente las lleva, el
resumen no). El del despachador se vio fallar sin el cambio (`KeyError: 'List-Unsubscribe-Post'`).

### 17-bis.1 · Las cabeceras (RFC 2369 y RFC 8058)

Todo correo al **cliente** sale con:

```
List-Unsubscribe: <https://compraventa-backend-dev.fly.dev/api/v1/public/unsubscribe/{token}>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

Gmail y Yahoo las exigen desde 2024 a los remitentes masivos y con ellas muestran «Anular suscripción» junto al
remitente: la persona se da de baja sin abrir el correo, en vez de marcarlo como spam. Hoy el volumen no llega al
umbral de «masivo», pero la entrega mejora igual, y la marca de spam la paga `prendo.com.co` para todos (§9.2-e).

- **Apuntan a la API, no a la página — y es la única excepción a la regla de §17.** Quien usa la cabecera es el
  **servidor** del proveedor de correo, con un `POST` y el cuerpo `List-Unsubscribe=One-Click`, y la RFC pide que la
  baja quede hecha en ese request, sin página intermedia. El front es estático (Vercel): no tiene quién reciba un
  POST. La regla de §17 —«un GET nunca da de baja»— sigue intacta: la RFC eligió POST justamente porque los escáneres
  que abren enlaces hacen GET (§1 de la RFC). El enlace del **cuerpo** sigue yendo a la página del front.
- **El POST ya existía** (`POST /api/v1/public/unsubscribe/{token}`) e ignoraba el cuerpo: sirve igual a la página
  (que no manda cuerpo) y al proveedor (que manda el form-urlencoded). Test con el request exacto de la RFC.
- **Una sola URI HTTPS**, porque la RFC 8058 pide exactamente una. Un cliente de correo que no sabe hacer el POST
  abre esa URI en el navegador: el `GET` de la API, con `Accept: text/html`, responde **303 a la página del front**
  en vez de un JSON crudo. Lo distingue el `Accept` —un navegador que navega manda `text/html`; el `fetch` de la
  página manda `*/*`—, y redirigir tampoco escribe.
- **A dónde apuntan:** `PUBLIC_API_URL` si está; si no, `https://{FLY_APP_NAME}.fly.dev`, que Fly pone solo en cada
  máquina de la app, **la del job incluida** (es la que manda los recordatorios). O sea: **no hace falta ningún
  secreto nuevo** para dev ni prod. Sin ninguna de las dos (local), el correo sale **sin** las cabeceras — no `dead`:
  la salida obligatoria de §9.2-e es el enlace del cuerpo; esto mejora la entrega, no es la salida.

**Los correos a la empresa y la invitación NO las llevan, a propósito:**

- **Resumen y alertas** van a usuarios de la empresa. No se «dan de baja» de un enlace: los apaga un admin en
  Configuración, o se les quita el permiso `receive_digest`/`receive_alerts`. Un «Anular suscripción» de Gmail
  prometería una salida que no existe (el POST exige un token de **cliente**) — y si existiera, un clic distraído le
  apagaría al dueño el aviso de un faltante de caja. Eso es una pérdida, no una preferencia.
- **La invitación** es un correo único que pidió un admin para una persona concreta, no una lista: no hay de qué
  darse de baja. Gmail no las exige para correos transaccionales uno a uno.

### 17-bis.2 · El límite de tasa del endpoint público

`/api/v1/public/unsubscribe/{token}` era el único endpoint de la API sin sesión y sin ningún límite. El proyecto no
tenía mecanismo (ni middleware ni `slowapi`), así que se hizo lo más simple que funciona:

| Llave | Límite | Qué corta |
|---|---|---|
| IP (`Fly-Client-IP`; sin ella, la del socket) | **60 pedidos por minuto** | una IP barriendo tokens basura |
| token (recortado a 128 caracteres) | **10 pedidos cada 10 minutos** | un script golpeando la misma URL — el único caso que llega a la base: un token basura muere en el HMAC, sin consulta |

`GET` y `POST` cuentan juntos. Pasado cualquiera: **`429 RATE_LIMITED`**, `details.retry_after_seconds` y la cabecera
`Retry-After`. Un pedido rechazado no cuenta (quien reintenta en bucle no alarga su castigo).

- **El objetivo es abuso, no fuerza bruta:** el token es un HMAC de 128 bits; no hay nada que adivinar.
- **Por qué tan holgado por IP:** el POST de un clic lo manda el servidor de Gmail, así que bajas legítimas de
  personas distintas pueden llegar desde las mismas IPs de Google; y el CGNAT de los operadores móviles pone a mucha
  gente detrás de una IP. Un 429 a una baja legítima es un correo más que termina marcado como spam.
- **Por qué 10 por token:** una persona real hace 2 o 3 (abrir, confirmar, recargar); los escáneres que abren el
  enlace también caben.

**Cómo se comporta con varias máquinas — la limitación, dicha claro.** El contador vive **en memoria del proceso**, y
cada máquina de Fly corre un solo worker de uvicorn, así que el límite es **por máquina**:

- Con N máquinas detrás del proxy, quien reparte sus pedidos entre todas llega hasta **N veces** el límite. Hoy dev
  corre una (y se apaga sola) y prod una siempre encendida: hoy N = 1.
- **Se olvida al reiniciar** (deploy, arranque en frío de dev).
- **Ventana fija:** en el borde entre dos ventanas caben hasta 2× el límite en poco tiempo.
- **Memoria acotada:** a 10.000 llaves se barren las vencidas, y si no alcanza se vacía todo — perder un minuto de
  conteo es mejor que dejar que alguien haga crecer el proceso hasta que Fly lo mate.

Para cortar abuso alcanza. **No sirve** para un límite global (una cuota, un login propio): eso pide un contador
compartido —una tabla, que pide migración, o un Redis, que es infraestructura nueva— y ninguno se justificaba para un
endpoint que recibe unas decenas de visitas al día. Los tests vacían el limitador entre caso y caso
(`tests/conftest.py`): la suite entera corre en un proceso y desde la misma IP.

### 17-bis.3 · Lo dudoso

- **`Fly-Client-IP` se da por confiable.** El proxy de Fly la escribe; si alguien llegara a la máquina sin pasar por
  el proxy podría fingirla, pero la máquina no expone el puerto fuera de la red privada de Fly.
- **DKIM de las cabeceras.** La RFC 8058 pide que la firma DKIM cubra `List-Unsubscribe` y `List-Unsubscribe-Post`.
  Resend firma con DKIM y documenta este uso del campo `headers`, pero **no se verificó** en un correo real (exige la
  key y el dominio verificado, como todo lo de §15–§20). Se ve en «Mostrar original» de Gmail: `dkim=pass` y las dos
  cabeceras en `h=`.
- **La prueba real del clic** —Gmail mostrando «Anular suscripción» y el POST llegando a Fly— queda para cuando se
  encienda un aviso al cliente con Resend configurado.

---

## 18. Fases 4 y 6 — lo implementado (25/09/2026)

**Sin migración.** Todo cupo en `00058` y `00059`: los siete tipos ya estaban en el catálogo con su plantilla, y la
entrega, sus estados y la base legal ya existían. Commit `8171f6c`. **Ningún aviso se encendió**: los siete siguen
`default_enabled = false` y el interruptor de la empresa sigue apagado (§12.3). Lo que cambió es que ahora, si alguien
los enciende, hay quién los produzca.

Se juntaron las dos fases porque son el mismo trabajo: la fase 4 (C2, C3) y la 6 (C1, C4–C7) tienen el mismo
disparo, la misma llave y el mismo camino de envío. Lo que las separaba en §11 era el valor, no el costo.

**Código:** `notifications/integration.py` (`record_customer_notice`, `choose_event`), `service.record_event` (devolvía
las entregas `pending` solo para la plataforma: ahora también para el cliente), los servicios y routers de
`contracts` y `sales`, `templates._customer_lines` (C3, C4, C5, C7), y el tope semanal en `preferences`, `limits`,
`repository.count_sent_to` y `dispatcher._prepare`. Tests: `tests/integration/test_customer_notices.py` (61) y
cinco nuevos en `tests/unit/test_notification_templates.py` / `test_notification_limits.py`.

### 18.1 · Las decisiones, y su porqué

**1. La Ley 2300 y los comprobantes: el tope SEMANAL no los alcanza; la hora y el tope diario, sí.**
La Ley 2300 de 2023 regula los contactos de **cobranza** (y la oferta de productos) —§12.2-1 la trajo para eso: *«ya
vencida: máximo uno por semana»*—. Un comprobante de abono no es cobranza: es el acuse de algo que el cliente acaba de
hacer en el mostrador, y lo recibe porque pagó, no para que pague. Con el tope semanal aplicado a todo aviso al
cliente (como quedó en la fase 1, §15.1), el **segundo abono de la semana quedaba `throttled`** —terminal, §4.2— y ese
cliente se quedaba sin su comprobante. Eso rompe el aviso que más vale después del paz y salvo. Quedó así:

| Regla | ¿Alcanza a C1–C7? | Por qué |
|---|---|---|
| Tope **semanal** (Ley 2300, 1 por semana) | **No**, ni lo consume: un comprobante no gasta el cupo de un recordatorio | Es de cobranza. Y la premisa tiene que ser la misma de los dos lados de la cuenta: si el comprobante no es cobranza para dejarlo pasar, tampoco lo es para contarlo |
| **Ventana horaria** (L–V 7–19, sáb 8–15, sin domingos ni festivos) | **Sí** | Es lo **conservador que no rompe**: el comprobante no se pierde, se corre al próximo momento hábil. Ver la salvedad abajo |
| Tope **diario** de 3 (§3) | **Sí** | No es de la ley: es de producto, y §3 lo escribió *«contando transaccionales»*, contra el cliente de 13 contratos |

**Es un parámetro, no una constante:** `customer_contact_limits.transactional_in_weekly_cap`, `false` por defecto. Si el
abogado dice que un comprobante SÍ cuenta como contacto, se pone en `true` y vuelve el comportamiento anterior — sin
código (test `test_the_lawyers_answer_is_configuration_receipts_can_count_again`). **La salvedad, sin adornos:** que
la Ley 2300 no alcance a un comprobante es mi lectura del alcance de la ley, no un concepto legal, y va a la misma
consulta que las otras tres de §12.2 (y que está en pausa, §12.3). Por eso la hora **se dejó**: si la ley sí alcanzara
a los comprobantes, lo que se estaría violando es el horario, y un comprobante corrido a la mañana siguiente cumple las
dos lecturas. El costo de esa prudencia está en §18.3-7.

**2. Idempotencia: dos capas, y la de adentro es la que está probada como red.**
La primera es la de siempre: un reintento con el mismo `Idempotency-Key` devuelve el documento que ya existía y
**no vuelve a pasar por el registro del aviso** — los servicios salen antes, y devuelven `None` como entrega. La
segunda es la llave del aviso (§6.1), que se **construye con el documento** y tiene `unique(company_id, dedupe_key)`
con `on conflict do nothing`: si algún día un camino llegara dos veces al registro, entraría una sola fila. Test por
cada disparo (`test_an_idempotent_retry_does_not_duplicate_the_notice`): mismo `Idempotency-Key` dos veces ⇒ un evento,
una entrega, **un correo en el `RecordingProvider`**. La anulación no tiene `Idempotency-Key` (no la tenía antes): el
segundo intento es `409` porque la venta ya no está `completed`, y el test fija eso.

**3. C2 y C3: sale UNO — el paz y salvo, con lo pagado adentro.**
§2.3 ya lo había decidido para otro caso y aplica igual: *«los transaccionales no se agrupan: cada uno es el acuse de
un hecho puntual»*. El hecho es **un abono**; que deje el contrato en `paid` es una propiedad de ese abono, no un
segundo hecho. Dos correos con segundos de diferencia —uno que dice *«saldo de capital: $0»* y otro que dice *«no nos
debe nada»*— son el mismo aviso dicho dos veces, y el segundo gasta uno de los tres del día (§3). Así que:

- El abono que salda manda **C3**, y C3 dice lo que C2 habría dicho: *«Recibimos $X (recibo #N). Su contrato #M quedó
  saldado el …»*. El comprobante no se pierde: se incluye.
- **La llave es la misma para los dos, `payment:<id>`**. Un abono, un aviso, por construcción: el `unique` hace
  imposible que el mismo abono produzca los dos.
- **Si la empresa apagó C3 y dejó C2**, sale C2 (`choose_event`): apagar el paz y salvo no puede dejar al último abono
  sin su comprobante. Con los dos apagados se registra C3, que es el hecho que pasó.

Y la misma regla, por la misma razón, para **C5 y C7**: una devolución liquidada en nota crédito es una devolución Y
una nota; sale **C5** (el que le dice al cliente que tiene un saldo, y de qué compra salió), con `return:<id>` para los
dos y C7 de respaldo si C5 está apagado.

**4. C7 sobre una devolución: el monto es `total_amount`, el mismo número que salió de la caja o quedó en la nota.**
`sum_sale_return_amount` es el **neto** de F21-33 (bruto menos el descuento prorrateado, `return_line_amounts_sql`), y
es exactamente lo que ya se usa para el `cash_movement` de la devolución y para `credit_note.amount`. El servicio lo
pone en el payload como texto y la plantilla solo lo formatea (`templates.money`): no hay una segunda cuenta que pueda
divergir. Test con el caso real de F21-33: 2 × $500.000 con $100.000 de descuento, devolver 1 ⇒ el correo dice
**$450.000** y no $500.000. En la **anulación**, el monto es el del contra-movimiento, y sale de la misma variable
(`refunded`) que el `record_movement`: si alguien corrige uno, el otro va con él (ver el defecto de §18.4).

**5. C1 en un contrato importado: NO se avisa.**
Ya estaba decidido en §3 (*«`import_contract`: es carga de datos históricos»*) y el código lo confirma: el préstamo se
entregó en otro sistema, el cliente ya tiene su papel, y una migración de 200 contratos serían 200 correos sobre nada —
los primeros de un dominio nuevo, que es cómo se quema. Lo que `import_contract` **sí** hace es escribir la base
`contract` (fase 3): el contrato está vivo, y los avisos que vengan después —abonos, paz y salvo— sí son hechos nuevos.
Test: `test_an_imported_contract_does_not_notify`.

**6. Todos siguen apagados.** `default_enabled = false` en los siete, sin tocar el catálogo. Con el interruptor
apagado el hecho **se registra igual** y sin entregas (§4.3) — test `test_off_the_fact_is_recorded_but_nothing_goes_out`.

### 18.2 · Qué quedó

| Operación | Evento | `dedupe_key` | Payload (lo que lee la plantilla) |
|---|---|---|---|
| `POST /contracts` | `contract_created` (C1) | `contract:<contract_id>` | número, `principal`, `next_due_date` = `add_months(start_date, 1)` |
| `POST /contracts/import` | — | — | — |
| `POST /contracts/{id}/payments` | `payment_registered` (C2) | `payment:<contract_payment_id>` | número, recibo, `amount` (= `total`, neto de descuento), `interest_paid_until`, `capital_balance` |
| ídem, si deja `paid` | `contract_paid_off` (C3) **en lugar de** C2 | `payment:<contract_payment_id>` | lo de C2 + `paid_on` |
| `POST /contracts/{id}/extend-loan` | `loan_extended` (C4) | `extend:<id del sucesor>` | los dos números, `extension_amount`, `capital_balance`, `next_due_date`, `anchor_kept` |
| `POST /sales` con `customer_id` | `sale_receipt` (C6) | `sale:<sale_id>` | número, `total` |
| `POST /sales/{id}/void` | `sale_reversed` (C7) | `sale_void:<sale_id>` | `kind: void`, número, `amount` (el contra-movimiento) |
| `POST /sales/{id}/returns`, en efectivo | `sale_reversed` (C7) | `return:<sale_return_id>` | `kind: return`, venta, devolución, `amount` (neto), `settlement_method`, y desde F21-37 el reparto: `refunded_amount`, `credit_note_amount` |
| ídem, si nace una nota (liquidada en nota, **o en efectivo sobre una venta pagada con nota**, §18.5) | `credit_note_issued` (C5) **en lugar de** C7 | `return:<sale_return_id>` | lo de C7 + `credit_note_number` |

- **Ni prenda, ni artículos, ni cédula, ni el motivo** de una anulación (es una nota interna: *«cobro doble del
  cajero»*). El test de las cinco promesas busca la descripción de la prenda y el código del artículo en asunto, texto
  y HTML de cada correo real que salió.
- **Sin cliente no hay evento** (venta de mostrador, devolución de una venta sin cliente en efectivo): §2.1, *«no es un
  hueco: es el negocio»*. **Cliente sin correo, sí**: evento + entrega `unroutable` (§1).
- **El aviso es el último paso de la transacción del documento**, después de la caja y la auditoría. Test por disparo
  que fuerza una falla **justo después** de registrarlo: ni documento ni aviso. Es la prueba de §5.1 («si el abono se
  revierte, el aviso se revierte con él») que no se podía escribir antes, porque no había productor.
- **El envío inmediato** es `send_after_commit`, al final del endpoint (§16.2-1, `ARCHITECTURE.md` §4). Sin cambios en
  request ni respuesta de ningún endpoint.

### 18.3 · Discrepancias: dónde el código contradijo este documento (y ganó)

1. **§6.1 dice `extend:<contract_id>` sin decir cuál.** Es el **sucesor**: es el documento de la ampliación —ahí apuntan
   el `cash_movement` del delta y la fila de `audit_log`—. El padre también sería único (un contrato se amplía una sola
   vez: queda `superseded`), pero la llave de un transaccional es el documento (§6.1), y el documento es el nuevo.
2. **§6.1 no tenía llave para anulaciones ni devoluciones.** Quedaron `sale_void:<sale_id>` —no `sale:<id>`, que es la
   del comprobante de la misma venta— y `return:<sale_return_id>`, que cubre C5 y C7.
3. **§2.1 lista C3 como un evento aparte que sale «del mismo abono», y C5 y C7 como dos del mismo `create_return`.** Salen
   uno por documento, con la misma llave: §18.1-3.
4. **§3 (*«máximo 3 correos por cliente por día contando transaccionales»*) y §12.3 (*«tope semanal, activo para
   `audience='customer'`»*) no distinguían cobranza de comprobante.** La fase 1 aplicó los dos a todo. Ahora el diario
   sigue igual y el semanal deja pasar los comprobantes: §18.1-1.
5. **La plantilla de C4 decía siempre *«La fecha de cobro no cambió»*.** Es cierto con `keep_anchor` (00053, el
   default) y **falso** con `forgive`/`charge_month`, que siguen valiendo para los contratos firmados bajo esas
   políticas (la columna es SNAPSHOT): ahí el sucesor arranca el ancla el día del recargo. El payload lleva
   `anchor_kept` y la frase solo aparece si es verdad.
6. **La plantilla de C7 decía *«anulación o devolución»*** porque no sabía cuál. Ahora el payload lleva `kind`, y la
   devolución dice cómo se liquidó (*«le devolvimos $X»* o *«se liquidó con la nota crédito #N»*).
7. **§5.1: *«un paz y salvo puede llegar hasta 24 h tarde en el peor caso»*. Con la ventana horaria, más.** Un abono de un
   domingo, un festivo o después de las 19:00 no sale en el envío inmediato: queda `pending` con `scheduled_at` en el
   próximo momento hábil, y lo manda **el job**, que corre una vez al día a una hora que no se fija (§15.2-10). Un paz y
   salvo del sábado a las 16:00 puede llegar el lunes en la noche. Es el costo, dicho, de la prudencia de §18.1-1.
8. **El hecho se escribe siempre, también apagado (§4.3) — y desde este deploy eso incluye cada abono, contrato y venta
   con cliente de TODAS las empresas.** Es lo que el diseño pide (el agregado y el latido), pero es nuevo en volumen: con
   los números de §10, del orden de 70 filas al mes por inquilino. El payload son números, montos y fechas; el
   `customer_id` es la única referencia a una persona.
9. **`record_event` no devolvía las entregas `pending` del cliente**, solo las de la plataforma: la fase 2 las necesitó
   para la invitación y el cliente no tenía productor. Sin el arreglo, todo transaccional esperaba al job.

### 18.4 · Lo que NO quedó, y lo dudoso

- **✅ Cerrado el 25/09/2026 como F21-36 (`QA_AUDITORIA.md`).** Decisión de Mateo: se **rechaza** la anulación de
  una venta con redención de nota crédito (`409 SALE_PAID_WITH_CREDIT_NOTE`), como `SALE_HAS_RETURNS`; la salida es una
  devolución liquidada en nota crédito. El C7 no cambió: una anulación que pasa ya no tiene parte de nota, así que
  `refunded = total` vuelve a ser cierto. **El gemelo** —una devolución liquidada en EFECTIVO sobre una venta pagada
  con nota también sacaba en plata la parte de la nota— **se cerró como F21-37**, y su aviso está en §18.5. Lo que
  sigue es el registro original del hallazgo.
  **Defecto encontrado de paso, NO arreglado (fuera de alcance, y es de dinero):** anular una venta pagada **en parte
  con nota crédito** devuelve en efectivo el total, incluida la parte que se pagó con la nota, y la nota queda
  redimida. Reproducido en local contra la API: venta de $800.000 = $500.000 de nota + $300.000 en efectivo → al anular,
  `cash_movement` de salida por **$800.000** (entraron $300.000) y la redención de $500.000 sigue en pie. El cliente
  convierte una nota —que no es plata— en efectivo, y el cajón descuadra por el monto de la nota. `void_sale` usa
  `row.total` sin mirar `credit_note_redemption`. Hay que decidir si anular **devuelve la nota** o **se rechaza** (como
  `SALE_HAS_RETURNS`, F21-31) — decisión de producto. El aviso C7 dice hoy el número que sale del cajón, porque sale de
  la misma variable; si se corrige el movimiento, el correo se corrige solo.
- **Pregunta legal, en la consulta en pausa (§12.3):** ¿la Ley 2300 alcanza a un comprobante? Si **no**, además del tope
  semanal habría que sacarle la ventana horaria (hoy no hay parámetro para eso: sería un segundo booleano en
  `customer_contact_limits` y una línea en `dispatcher._prepare`). Si **sí**, `transactional_in_weekly_cap: true`.
- **Pregunta de producto para Mateo:** el tope diario de 3 corta el **cuarto comprobante** del día. Un cliente con
  varios contratos que abona cuatro en la misma visita recibe tres; el cuarto queda `throttled`. Es lo que §3 decidió,
  pero §3 pensaba en recordatorios más comprobantes; con solo comprobantes, quizás el tope no debería contarlos. Se dejó
  como estaba: relajarlo es subir `max_per_day`, sin código.
- **La pantalla de preferencias no muestra `transactional_in_weekly_cap`** (el front no se tocó). El campo es aditivo en
  el `GET`/`PATCH` y el front no lo manda, así que no rompe nada; el valor por defecto es el correcto.
- **Webhook de Resend, `delivered`/`bounced`, y verificado en vivo con un correo real:** pendientes, como en §15–§17.
- ~~**R1–R4 (fase 5)** siguen sin productor.~~ Tienen productor desde la fase 5 (§20).

### 18.5 · La devolución de liquidación mixta: UN aviso con los dos montos (F21-37, 25/09/2026)

Desde F21-37 una devolución en efectivo sobre una venta pagada (toda o en parte) con nota crédito **se parte**: lo
pagado con nota vuelve como una **nota nueva** y solo lo pagado en plata sale del cajón (`QA_AUDITORIA.md` §F21-37,
`sales/settlement.py`). La venta de $800.000 = $500.000 de nota + $300.000 en efectivo, devuelta completa, deja
**$300.000 en efectivo y una nota nueva de $500.000**. Una misma devolución, dos formas de liquidarse. ¿Qué aviso sale?

**Uno solo, el de la nota (C5), y dice los dos montos.** Es §18.1-3 aplicado sin cambios: el hecho es **una
devolución**; que haya dejado una nota es una propiedad de ese hecho, no un segundo hecho. Así que:

- **La llave sigue siendo `return:<id>`**, y el `unique` hace imposible un segundo aviso por el efectivo.
- **Sale C5** porque es el más específico: es el único que le dice al cliente que tiene un saldo y con qué número.
  Con C5 apagado y C7 encendido sale C7 (`choose_event`, sin cambios).
- **Cualquiera de los dos dice los dos montos.** C5: *«Por la devolución de su compra #12 se emitió la nota crédito
  #5 por $500.000. Además le devolvimos $300.000 en efectivo.»* C7: *«Le devolvimos $300.000 en efectivo, y el resto
  quedó en la nota crédito #5 por $500.000.»* Callar el efectivo dejaría al cliente sin constancia de plata que
  recibió; decir $800.000 —el total— haría creer que todo salió del cajón o que todo es nota.
- **El payload trae el reparto** además de `amount` (el total neto, como siempre): `refunded_amount` (lo que salió
  del cajón) y `credit_note_amount` (el monto de la nota nueva). Son las **mismas variables** que el `cash_movement` y
  el `credit_note.amount` de la devolución, en la misma transacción: el correo no puede decir un número distinto del
  documento, que es la regla de §18.1-4. La plantilla los formatea, no los calcula.
- **Compatible hacia atrás:** los eventos registrados antes no traen el reparto, y la plantilla cae al `amount` de
  siempre (test `test_a_note_only_return_keeps_its_old_wording`). Una devolución solo en efectivo o solo en nota
  dice lo mismo que antes; un `refunded_amount` de `"0.00"` no produce un «le devolvimos $0».

Tests: `test_a_mixed_return_sends_ONE_notice_that_names_both_amounts` y
`test_a_mixed_return_with_credit_note_off_still_names_both_amounts` (`tests/integration/test_customer_notices.py`,
contra la API real: un evento con `dedupe_key = return:<id>`, una entrega, un correo con $500.000 y $300.000 y sin
$800.000), y `test_a_mixed_return_names_the_note_and_the_cash_in_both_templates` (unitario, las dos plantillas).
Los dos de integración se vieron fallar antes del arreglo: salía C7 diciendo *«Le devolvimos $800.000»*.

---

## 19. Fase 7 — lo implementado (25/09/2026)

**Sin migración.** Todo cupo en `00058`: los cuatro tipos ya estaban en el catálogo con `audience='company'`,
`family='alert'` y `default_enabled = true`, el permiso `notifications.receive_alerts` ya estaba sembrado al rol con
`identity.manage_roles`, y la entrega ya tenía `recipient_user_id`. **Nada se encendió que no estuviera encendido**:
las alertas nacen `true` por catálogo, pero el interruptor general de la empresa sigue apagado (§15.2-5), y es él el
que manda.

**Código:** `notifications/integration.py` (`record_company_alert`), `service.record_event` (la rama de las alertas,
que hasta hoy devolvía «sin productor, nada que planificar»), `repository.list_recipients_with_permission` (el
resumen y las alertas, una sola consulta), `preferences.above_discount_threshold`, `templates.render_alert`,
`dispatcher.send_after_commit` (acepta varias entregas), el `alert_recipients` del `GET /notifications/settings`, y
los servicios y routers de `sales`, `contracts`, `capital` y `cashbox`. Tests: `tests/integration/test_company_alerts.py`
(45, contra la API real) y cinco en `tests/unit/test_notification_templates.py`.

### 19.1 · Las decisiones, y su porqué

**1. Quien hizo el acto NO recibe su propia alerta.**
§2.5 dice para qué existe: *«el valor no está en el aviso, está en que llegue el mismo día a alguien que puede
preguntar»*. Quien anuló la venta no se pregunta a sí mismo por qué la anuló; ya lo sabe, y acaba de escribir el
motivo. Es la regla de §3 sin excepciones —*«un hecho cuyo destinatario es la persona que acaba de hacer clic no es un
correo. Es una pantalla»*— y además la única que no entrena a ignorar: un dueño que retira todas las semanas y recibe
un correo por cada retiro suyo aprende a archivar el remitente, y el día que el retiro lo haga otro, ese correo ya
nadie lo abre. Se consideró el argumento contrario —que la propia alerta sirve de aviso de *cuenta comprometida*
(«alguien usó mi usuario»)—, y se descartó **para esta fase**: eso es una alerta de seguridad, con otro destinatario
(el titular, siempre, tenga o no el permiso) y otra redacción; mezclarla acá la dejaría a medias en las dos cosas.

La consecuencia, dicha: **en una compraventa donde el dueño es el único con el permiso y hace él mismo el acto, no
sale nada.** El hecho queda registrado sin entregas (§4.3), y sigue en `audit_log` y en el resumen diario, que es lo
que había antes de la alerta. Es correcto: no hay nadie más a quien avisarle.

**2. Una llave por DOCUMENTO, en un espacio propio.**

| Operación | Alerta | `dedupe_key` | Por qué así |
|---|---|---|---|
| `POST /sales/{id}/void` | `alert_sale_voided` (A1) | `alert:void:<sale_id>` | Una venta se anula una sola vez |
| `POST /sales` con descuento | `alert_discount` (A2) | `alert:discount:sale:<sale_id>` | El descuento nace con la venta y es inmutable |
| `POST /contracts/{id}/payments` con descuento | `alert_discount` (A2) | `alert:discount:payment:<contract_payment_id>` | Ídem, con el abono |
| `POST /capital/withdrawals` | `alert_capital_withdrawal` (A3) | `alert:withdrawal:<capital_movement_id>` | El retiro es el documento |
| `POST /cashbox/sessions/{id}/reopen` | `alert_cash_reopened` (A4) | `alert:reopen:<session_id>:<closed_at>` | Ver abajo |

- **El prefijo `alert:`** separa estas llaves de las del cliente para el MISMO documento (`sale_void:<id>` es el C7 de
  la misma anulación, §18.3-2): la unicidad es `(company_id, dedupe_key)` sobre toda la tabla, y dos hechos distintos
  del mismo documento no pueden compartir llave.
- **A2 lleva el tipo de documento en la llave** (`sale:` / `payment:`), aunque los UUID no choquen: la llave se lee en
  `GET /notifications/deliveries` y en la base, y tiene que decir de qué documento habla sin ir a buscarlo.
- **A4 no puede ser solo la sesión**: una caja se cierra, se reabre, se vuelve a cerrar y se vuelve a reabrir, y cada
  reapertura es un hecho nuevo. Una llave `alert:reopen:<sesión>` se tragaría la segunda en silencio por el
  `on conflict do nothing` (el mismo error que §16.1 evitó con la invitación). Lo que hace única a una reapertura es
  **el cierre que deshace**: su `closed_at`, que el cierre siguiente cambia. Anclada al hecho, como la llave de mora
  (§6.1): la misma reapertura da la misma llave, la siguiente otra.
- **Dos capas, como en §18.1-2.** Un reintento con el mismo `Idempotency-Key` devuelve el documento que ya existía y
  no pasa por la alerta (venta, abono, retiro); anular o reabrir dos veces es `409` (`CONFLICT` /
  `CASH_SESSION_NOT_CLOSED`), porque esos dos endpoints no llevan llave. La `dedupe_key` es la red de adentro. Test por
  alerta: un evento, dos entregas, dos correos.

**3. Qué dice cada alerta: quién, qué, cuánto, cuándo y el motivo. Del cliente, nada.**
El motivo va —los cuatro actos lo exigen y ya queda en `audit_log`— porque el lector es la empresa y es la primera
pregunta que haría; al cliente no se le dice (§18.2, C7). El cliente **no aparece ni por nombre**: §9.1 admite el
nombre de pila en un correo **al cliente** porque es su propio aviso; acá el cliente es un tercero, y el número del
documento alcanza para preguntar en la app. Ni cédula, ni prenda, ni artículos (test sobre cada correo real).

| Alerta | Además de quién (nombre) y cuándo (hora local de la empresa) |
|---|---|
| A1 | número de la venta, total, lo que salió de la caja (el mismo `refunded` del contra-movimiento y del C7), día de la venta, motivo |
| A2 · venta | número, total antes del descuento, descuento, cobrado, motivo, y el umbral si no es 0 |
| A2 · abono | número del contrato y del recibo, interés del abono (de ahí sale el descuento), descuento, cobrado, motivo, umbral |
| A3 | número del retiro, monto, cuenta, clase (utilidad / devolución de capital), fecha del documento, motivo (`notes`) |
| A4 | día de la caja, cuándo se había cerrado, lo contado y el descuadre de ese cierre (que se revierte), motivo |

**A4 dice lo que el acta pierde.** Reabrir borra `expected_cash`, `counted_cash` y `difference` de la sesión (F21-32);
el `audit_log` los guarda en `before`, y la alerta los cuenta, porque *«reabrió la caja de ayer, que había cerrado con
un faltante de $20.000»* es otra pregunta que *«reabrió la caja de ayer»*.

**Remitente y marca: Prendo**, como el resumen (§8: el destinatario es un usuario de Prendo). La empresa va en el
asunto —`Alerta · <Empresa> · Venta #12 anulada`— porque quien trabaja en dos compraventas tiene que saber de cuál
es. Sin `Reply-To` y sin la firma del inquilino.

**4. El resumen diario SIGUE listando los descuentos (y los descuadres). La alerta no saca nada del resumen.**
Ya lo había decidido §12.2-4 —*«por debajo del umbral el evento igual sale en el resumen; el umbral decide solo la
alerta inmediata»*— y la fase 7 no lo cambia, por tres razones: el resumen es el **registro del día** y la alerta es
la **urgencia**, y un registro que omite lo que ya se avisó deja de sumar; sacarlo haría que el resumen dependiera de
si la alerta salió (apagada, sin destinatarios, rebotada, `dead`), que es exactamente el acoplamiento que §5.1 evita;
y quien recibe el resumen no es necesariamente quien recibe las alertas (son dos permisos, §4.3). La marca
«⚠ sobre el umbral» del resumen y la decisión de la alerta salen ahora de **la misma función**
(`preferences.above_discount_threshold`): no pueden divergir. Lo que el resumen **no** lista uno por uno —las
anulaciones (solo el conteo), los retiros y las reaperturas— tampoco se agregó: el resumen es un tablero, no un
segundo `audit_log`.

**5. Sin Ley 2300, sin base legal; con interruptor y casilla.** El despachador ya aplicaba los límites de contacto solo
a `audience='customer'`, y la base legal (§9.2) es del cliente. El destinatario acá es un usuario de la empresa, con un
permiso que alguien le dio en un rol. Sí mandan el interruptor general y la casilla del evento, **al planificar y otra
vez al enviar** (`dispatcher._prepare`, sin cambios): apagar la alerta entre el acto y el envío la deja `suppressed`.

**6. Inmediata, sin ventana horaria.** Sale en el envío posterior al commit (`send_after_commit`), a cualquier hora:
el test la manda un **domingo a las 23:00**. Sin rezago (`target_date` nula: un acto de hoy no caduca). Si el envío
inmediato no ocurre, la entrega queda `pending` y la barre el job — la garantía de siempre (§5.1), con el costo de
siempre: en ese caso llega al día siguiente.

**A2 y el umbral, en concreto.** Estricto: alerta si `descuento > umbral`. Con el umbral en 0 —como nace— todo
descuento alerta; con el umbral en $10.000, un descuento de $10.000 no. **Por debajo no se registra el evento**, a
diferencia de «apagada», que sí lo registra sin entregas (§4.3): el evento del catálogo es *«descuento por encima del
umbral»*, y un descuento por debajo no es ese hecho — el hecho (el descuento) ya está en el documento, en `audit_log` y
en el resumen.

### 19.2 · Qué quedó

- **Destinatarios**: usuarios `active` con `notifications.receive_alerts`, menos el autor, **una entrega por
  destinatario**, con `recipient_user_id`. Un `invited` o `inactive` no recibe (test explícito con un Exsocio que
  conserva el rol).
- **El hecho, último paso de la transacción**, después del documento, la caja, la auditoría y el aviso al cliente.
  Test por alerta que fuerza una falla justo después de registrarla: ni alerta, ni `audit_log` del acto.
- **`GET /notifications/settings` trae `alert_recipients`**, análogo a `digest_recipients` (aditivo). La pantalla dice
  quién las recibe.
- **Ningún endpoint cambió su request ni su respuesta.** Los servicios devuelven ahora `(documento, tupla de
  entregas)`; el router llama `send_after_commit(db, background, *entregas)` (ARCHITECTURE §4).

### 19.3 · Discrepancias: dónde el código contradijo este documento (y ganó)

1. **§2.5 nombra `apply_sale_discount` / `apply_payment_discount` como si fueran funciones.** Son **acciones de
   `audit_log`**: el descuento no tiene endpoint propio, nace dentro de `create_sale` y `create_payment`. La alerta se
   dispara ahí, cuando `discount_amount > 0`.
2. **§5.1/§16.2-1: `send_after_commit` recibía UNA entrega.** Una alerta son N (una por destinatario), y la misma
   anulación trae también el C7. Se amplió a varias en vez de inventar otra función (ARCHITECTURE §4).
3. **§4.3 no decía si el autor recibe.** Quedó que no (§19.1-1), con `record_event(actor_user_id=…)`.
4. **§6.1 no tenía llaves de alertas**, y la obvia para A4 (`alert:reopen:<sesión>`) era incorrecta: §19.1-2.
5. **§4.1 «el hecho se escribe SIEMPRE» — salvo A2 por debajo del umbral**, que no es el hecho del catálogo (§19.1, al
   final).
6. **§9.1 permite el nombre de pila del cliente «en un correo».** Pensaba en el correo **al** cliente; en una alerta a
   la empresa el cliente no aparece ni por nombre.
7. **A1 sobre una venta con nota crédito ya no existe** (F21-36 la rechaza con `409 SALE_PAID_WITH_CREDIT_NOTE`), así que
   «lo que salió de la caja» es siempre el total. El payload lo trae aparte igual (`refunded_amount`), del mismo
   `refunded` que el contra-movimiento: si la regla cambia, el correo va con ella.

### 19.4 · Operación, orden de deploy, y lo dudoso

- **Una empresa que YA tenga el interruptor encendido empieza a recibir alertas el día del deploy**, sin tocar nada: las
  cuatro nacen `true` por catálogo (§15.1) y hasta hoy no tenían productor. Es lo que el catálogo prometía, pero es un
  cambio de comportamiento que llega con el código y no con un acto. **No se midió en dev** (prohibido tocarla en esta
  fase) cuántas empresas tienen `settings.notifications.enabled = true`; el día del deploy conviene mirarlo —de solo
  lectura, con `BEGIN TRANSACTION READ ONLY`— y avisarle al dueño de cada una.
- **Orden de deploy**: el backend primero o a la vez; el front después. El campo `alert_recipients` es aditivo, pero el
  front nuevo lo lee: contra un backend viejo la lista vendría indefinida. Sin migración, así que no hay nada que
  aplicar antes.
- **Sin `RESEND_API_KEY`** las alertas quedan `skipped_no_provider`, como todo lo demás.
- **Dudoso — el volumen si el umbral queda en 0.** §12.1-4 midió 11 abonos y 13 ventas en septiembre en toda la base;
  con eso, avisar todo descuento es barato. En una empresa con descuentos a diario, cada uno es un correo por
  destinatario. Es lo que §12.2-4 decidió («cerrado de más se nota») y se sube el umbral sin código.
- **Dudoso — el autor excluido y la cuenta comprometida** (§19.1-1). Si Mateo quiere que el titular de la cuenta se
  entere de lo que se hace con su usuario, es una alerta de seguridad aparte, no un cambio de esta regla.
- **No hay alerta de descuadre de arqueo al cierre.** §12.2-4 menciona el umbral de «descuadre grande» para las
  alertas inmediatas, pero §2.5 no lo tiene entre sus cuatro actos, y el catálogo tampoco. El descuadre sigue en el
  resumen (E4) con su marca de umbral. Agregarlo sería un quinto tipo en el catálogo (migración) y una decisión de
  producto; no se hizo.
- **Verificado en vivo con un correo real: pendiente**, como en §15–§18.

---

## 20. Fase 5 — lo implementado (25/09/2026)

**Sin migración.** Todo cupo en `00058` y `00059`: los cuatro tipos ya estaban en el catálogo con su familia
(`reminder` R1/R4, `state` R2/R3) y `default_enabled = false`, `notification_event.target_date` ya existía para el
rezago, y el tope semanal ya distinguía cobranza de comprobante por familia (§18.1-1). **Nada se encendió:** los
cuatro siguen apagados por catálogo y el interruptor de la empresa sigue apagado.

**Código:** `notifications/reminders.py` (nuevo: el planificador puro `plan_reminders` y el paso
`build_all_reminders`), `contracts/integration.list_reminder_contracts` (fechas y montos derivados con `rules`),
`preferences.ReminderSchedule` (los días de antelación como parámetro), el campo `reminders` del
`GET`/`PATCH /notifications/settings`, las plantillas de R1–R5 (`templates._reminder_lines`, `INFORMATIVE_NOTE`,
`COURTESY_NOTE`) y el paso nuevo en `jobs/nightly.py`. Tests: `tests/integration/test_customer_reminders.py` (17,
contra Postgres), `tests/unit/test_notification_reminders.py` (8, el planificador), cuatro en
`test_notification_templates.py` y uno en `test_notifications.py` (la preferencia). Cada uno se vio fallar antes
de implementar (contra un `build_all_reminders` vacío, las plantillas viejas y el esquema sin `reminders`).

### 20.1 · Qué sale y cuándo

El job tiene ahora **cinco pasos**: estados → suscripciones → resumen → **recordatorios** → despacho. El paso nuevo
va después de `recompute_all_statuses` (R2 y R3 leen el estado persistido, §5.2) y antes del despacho (que manda lo
que el paso crea esa misma noche). Una transacción por empresa, las mismas empresas que el resumen (activas y con
suscripción vigente); la falla de una se registra y no tumba el job.

| # | Evento | Día objetivo (se deriva del ancla, con `rules`) | `dedupe_key` |
|---|---|---|---|
| R1 | `installment_due_soon` | `add_months(interest_paid_until, 1) − N`, con N en `installment_days_before` (de fábrica **3 y 0**) | `due_soon:<customer_id>:<día objetivo>` |
| R2 | `installment_overdue` | el día en que entró en mora: `add_months(interest_paid_until, 1)` (solo `in_arrears`) | `arrears:<customer_id>:<día objetivo>` |
| R3 | `extension_started` | el día en que entró en prórroga: `add_months(interest_paid_until, arrears_window_months)` (solo `in_extension`, y solo si cuadra con `extension_ends_at`, §20.3-4) | `extension:<customer_id>:<día objetivo>` |
| R4 | `extension_ending_soon` | `extension_ends_at − N`, con N en `extension_days_before` (de fábrica **3**) | `extension_ending:<customer_id>:<día objetivo>` |
| R5 | `auction_ready_customer` | sin cambios: el día siguiente al fin de la prórroga, en el paso del resumen (§15.1) | `auction_ready:<contract_id>:<extension_ends_at>` |

- **Agrupación (§2.3): un evento por (cliente, día objetivo, tipo)**, con todos sus contratos en
  `payload.contracts` —número, fecha, monto y saldo de capital (§9.1)—, ordenados por número. Tres cuotas de Juana
  que tocan el mismo martes —dos que vencen el viernes y una que vence ese día— son **un** correo. `entity_type`
  del evento es `customer`.
- **Idempotencia:** la llave lleva la fecha objetivo, nunca la de corrida (§6.1): correr dos veces la misma noche,
  o tres días tarde, da la misma llave; el mes siguiente, otra. `on conflict do nothing` como camino normal.
- **La ventana de búsqueda** es de 7 días hacia atrás (`max(7, stale_after_days + 1)`), re-evaluada cada noche. Si
  el job estuvo caído, lo que cayó dentro de esos días se registra y `service.record_event` aplica el rezago de
  siempre: todavía es noticia → `pending`; ya no → `skipped_stale` (§5.3). Lo anterior a 7 días no se registra.
- **Montos:** R1 dice la cuota (`rules.monthly_interest`); R2, R3 y R4 dicen lo que cuesta ponerse al día hoy
  (`monthly_interest × months_between(interest_paid_until, hoy)`). Todo sale de `contracts.integration`:
  `notifications` no calcula una fecha ni un interés.
- **Plantillas** (molde de §8.1, marca de la empresa en el encabezado, enlace de baja, de usted): fechas
  **absolutas** («vence el 6 de septiembre de 2030», nunca «en 3 días», porque un aviso que sale un día tarde dentro
  de la ventana tiene que seguir siendo cierto), «Si ya pagó, no tenga en cuenta este mensaje», y el recuadro con la
  aclaración: **R3 y R4** «informativo … no reemplaza lo pactado en su contrato»; **R5** «aviso de cortesía; la
  notificación formal es la que establece su contrato» (§12.3). Ni prenda ni cédula: test sobre el render.
- **Lo demás no lo decide este paso:** la base legal, el apagado y el rezago los aplica `record_event` como a todo
  evento; la hora hábil y el tope de la Ley 2300, el despachador, en un solo lugar (§14). Los cuatro son familia
  `reminder`/`state`: gastan y respetan el tope semanal; los comprobantes no.
- **Preferencia nueva:** `company.settings.notifications.reminders = {installment_days_before, extension_days_before}`,
  listas de 0 a 30 días, sin repetir, hasta 5 puntos. Faltante = default; nada exige backfill. En el `GET`/`PATCH`
  como `reminders` (aditivo; el `PATCH` se audita dentro de `update_settings`, como el resto).

### 20.2 · Las decisiones, y su porqué

**1. El día del vencimiento es UN aviso, no dos.** `months_owed = months_between(interest_paid_until, hoy)` pasa de
0 a 1 **el mismo día** en que vence la cuota: ese día el contrato entra en mora (o, con ventana de un mes, directo en
prórroga). El «día del vencimiento» que §12.2-1 le pidió a R1 y el «entró en mora» de R2 caen el mismo día sobre el
mismo contrato. Dos correos el mismo día —«vence hoy» y «venció»— son el mismo aviso dicho dos veces. Quedó como
C2/C3 (§18.1-3): **si el evento de estado de ese día (R2, o R3 con ventana 1) está encendido, él lleva el contrato**;
si no, lo lleva R1. El hecho de estado se registra siempre (apagado, sin entrega); lo que cambia es si R1 lo repite.

**2. Por qué la agrupación manda sobre la llave de §6.1.** Ver §20.3-1.

**3. Por qué una ventana fija de búsqueda y no «desde la última corrida», como el resumen.** El resumen necesita
saber hasta dónde reportó para no contar dos veces; acá la `dedupe_key` ya lo garantiza, y re-evaluar 7 días cada
noche cuesta una consulta por empresa sobre sus contratos vivos. Es más simple y no depende de otra fila.

### 20.3 · Discrepancias: dónde el código contradijo este documento (y ganó)

1. **§6.1 da llaves por CONTRATO para R2 y R3 (`arrears:<contract_id>:<interest_paid_until>`,
   `extension:<contract_id>:<extension_ends_at>`) y una de R1 con `<lead_days>`. Con cualquiera de las dos, §2.3 es
   imposible:** una llave por contrato es un evento por contrato, y un evento es un correo; y con `<lead_days>` en la
   llave, dos contratos del mismo cliente en etapas distintas (uno a 3 días, otro que vence hoy) partirían el día en
   dos correos. Ganó §2.3 —*«la decisión que los números de la base obligan»*—: la llave es
   `<tipo>:<customer_id>:<día objetivo>`. **La propiedad que §6.1 buscaba se conserva:** el día objetivo de R2 y R3
   se deriva del ancla (`interest_paid_until`), así que cuando el cliente abona y el ancla avanza, la llave del mes
   siguiente es otra sin que nadie limpie nada.
2. **El día del vencimiento de R1 coincide con la entrada en mora de R2** (§20.2-1). El diseño no lo vio porque §2.2
   se escribió con R1 solo a 3 días, y §12.2-1 le agregó el día del vencimiento después.
3. **R2 «ya vencida, máximo uno por semana» (§12.2-1) quedó como UN aviso por ancla, no uno semanal.** §12.2-1 fijó
   un **tope**, no una cadencia, y la llave anclada al ancla de §6.1 manda uno por mes adeudado: al entrar en mora.
   No se construyó un recordatorio que se repita cada semana mientras siga en mora. Si se quisiera, sería una llave
   con la semana (`arrears_weekly:<cliente>:<lunes>`) y una decisión de producto — y con el tope de la ley, gastaría
   el único contacto de la semana.
4. **§15.2-1 deriva el día de entrada en prórroga del ancla, y eso miente si el ancla se mueve con la prórroga en
   curso.** Un cliente que debe más meses que la ventana puede abonar uno y seguir en prórroga: el ancla avanza, el
   día «derivado» se corre y caería dentro de la ventana de búsqueda — un segundo «entró en prórroga» sobre la misma
   prórroga. `list_reminder_contracts` exige que el día derivado cuadre con el `extension_ends_at` persistido
   (`add_months(entrada, extension_months) == extension_ends_at`); si no, no hay R3. Test con el caso. **El resumen
   (E2) tiene el mismo defecto** en `list_state_entries` y no se tocó (fuera de alcance; el efecto allá es una fila
   de más en un correo interno).
5. **R2 sí puede repetirse tras un abono parcial en mora, y es a propósito.** Si debe dos meses y paga uno, el ancla
   avanza y sigue en mora: la cuota siguiente también está vencida, y es un hecho nuevo — exactamente lo que la llave
   de §6.1 anclada a `interest_paid_until` producía. Si cae dentro de la ventana de búsqueda sale (o queda
   `skipped_stale`), con su fecha real.
6. **§2.2 decía «R4: `extension_ends_at` cae en N días»** sin N. Quedó 3, como R1, y es parámetro.
7. **La plantilla de R1 de la fase 1 traía la fecha arriba y un solo vencimiento.** Con la agrupación, cada contrato
   lleva su fecha (el mismo día pueden tocar cuotas de fechas distintas). Un payload con el formato viejo se sigue
   redactando (la fecha de arriba completa la de cada contrato).

### 20.4 · Operación, deploy, y lo dudoso

- **El deploy tiene que actualizar la Machine `nightly-job`**, no solo la app: `fly deploy` no la toca (F21-10,
  ARCHITECTURE §11), y sin eso el paso nuevo no corre — los recordatorios no nacen nunca y **nadie se entera**, porque
  un paso que no existe no falla. Usar `scripts/deploy_dev.sh` (`e5819ae`), que lleva la Machine a la misma imagen
  conservando su `schedule` (nunca la destruye: borrarla causó el incidente del 27/08). Verificación
  desde la base, de solo lectura: `select max(occurred_on) from notification_event where event_type in
  ('installment_due_soon','installment_overdue','extension_started','extension_ending_soon')` — la primera noche
  registra los hechos (apagados) de cualquier empresa con contratos vivos.
- **La primera noche registra hechos de hasta 7 días atrás**, apagados y sin entrega en toda empresa que no los
  encendió. En una empresa que los encienda, lo de más de 2 días queda `skipped_stale` — es el rastro esperado, no
  una falla. Volumen: del orden de 4 filas por cliente con contrato vivo por mes (§10).
- **Sin migración, sin secretos nuevos.** Los de siempre para que un correo al cliente salga: `RESEND_API_KEY`,
  `FRONTEND_URL` y `NOTIFICATIONS_LINK_SECRET` **en la Machine del job** (§17.3). El front puede ir después: el campo
  `reminders` es aditivo.
- **Dudoso — el tope semanal se come el aviso del día del vencimiento.** Con la ley aplicada tal cual (§12.3-1, un
  contacto por semana) y los días de fábrica (3 y 0), **el recordatorio de 3 días antes sale y el del día del
  vencimiento queda `throttled`** (test `test_weekly_cap_throttles_the_second_reminder_but_not_a_receipt`). Y como el
  día del vencimiento lo lleva R2 si está encendido (§20.2-1), **con R1 y R2 encendidos el R2 también queda
  `throttled`**, y el siguiente contacto posible es R3, meses después. No es un defecto del código: son las dos
  decisiones juntas. Si Mateo prefiere el aviso del día del vencimiento, se deja `installment_days_before: [0]`; si
  prefiere los dos, hay que relajar `max_per_week` — y eso es justo lo que la ley limita.
- **Dudoso — sin prioridad dentro de la misma noche.** Si a un cliente le tocan dos recordatorios de tipos distintos
  la misma noche (R1 de un contrato y R3 de otro), sale el primero que tome el despachador y el otro queda
  `throttled`; el orden entre entregas creadas en la misma transacción no está definido (`claim_due_deliveries`
  ordena por `scheduled_at`, que es el mismo). Lo razonable sería que ganara R3 (la última campana); no se hizo.
- **Dudoso — cambiar un interruptor a mitad del día** puede producir, en una segunda corrida de esa misma noche, R1
  «vence hoy» además del R2 que ya salió (la llave es otra). Caso de borde: el job corre una vez al día.
- **Dudoso — la cláusula del contrato no se verifica** (§9.2-i): el backend escribe `contract` aunque la empresa no
  haya insertado la cláusula en su plantilla.
- **Revisión legal antes de encender** en una empresa real (§12.3): la recomendación sigue en pie.
- **Webhook de Resend y verificado en vivo con un correo real:** pendientes, como en §15–§19.

