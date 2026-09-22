# NOTIFICACIONES.md — Avisos por correo al cliente y a la empresa (spec)

> **Estado: DISEÑADO, sin una línea de código.** El backend no tiene hoy ningún módulo de correo: cero dependencias (`pyproject.toml` no menciona ninguna librería de email), cero plantillas, cero cola, cero tabla. Todo el correo que sale de la plataforma lo manda **Supabase Auth** con su SMTP compartido, que responde `429 INVITE_RATE_LIMITED` a las pocas invitaciones (`app/modules/identity/auth_admin.py:70`). Se va a migrar a **Resend** sobre `prendo.com.co`.
>
> Pedido por Mateo: *"notificar todo lo que valga la pena — contratos, abonos, ventas, vencimiento de cuota, prórroga, remate, paz y salvo, entre otras cosas — al cliente y a la empresa."*
>
> **Principio de diseño:** un aviso es la **consecuencia** de un hecho que ya quedó registrado, nunca un hecho nuevo. De ahí sale todo lo demás: el aviso no puede hacer fallar la operación que lo originó, no puede perderse sin dejar rastro, y no puede depender de un canal que la mitad de los destinatarios no tiene.
>
> **Verificado contra el código y contra la base dev el 21/09/2026.** Lo que es suposición está marcado como tal.

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
| R5 | ~~**Listo para remate**~~ | `in_extension` **y** `extension_ends_at` ya pasó | **Empresa, no cliente** — ver §2.4 y §12.1 | diaria | — | — |

> **R3 es el aviso más valioso de todo el documento y el más fácil de pasar por alto.** `in_extension` es la última campana antes de que la prenda se pueda rematar, y **se dispara sola**, sin que nadie toque nada: `compute_status` lo pone cuando `months_owed` llega a `arrears_window_months` (4 en metales, 1 en tecnología). Hoy el cliente no se entera de que su contrato cambió de estado; se entera cuando viene a pagar y le dicen que su cadena ya no está.

**«Listo para remate» no es un `status`.** Es `in_extension` con `extension_ends_at` ya pasado — exactamente el predicado de `GET /contracts/ready-for-auction`. Cualquier consulta de este documento que lo trate como un estado del enum está mal.

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
| P1 | **Invitación de usuario** | **Ya existe**, lo manda Supabase Auth. Es lo primero que se migra a Resend, porque es lo que se está rompiendo con `INVITE_RATE_LIMITED` |
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
| `suppressed` | Sin autorización, con opt-out, o `email_invalid_at` puesta | Ruidosa en el agregado, invisible por fila |
| `throttled` | Tope de §3 | Silenciosa; solo importa si sube |
| `skipped_stale` | El job estuvo caído y el hecho ya no es noticia (§5) | **La alarma más importante del sistema.** Un `skipped_stale > 0` es la señal que nadie tuvo cuando la Machine desapareció 12 días |
| `dead` | 3 intentos y no salió | **Ruidosa:** entra al resumen de la empresa |
| `bounced` | Rebotó duro | Ruidosa una vez, y marca la dirección (§7) |

### 4.3 · Preferencias: tres niveles, tres preguntas distintas

No se colapsan porque **no son la misma pregunta**, y unificarlas es lo que produce la casilla que nadie sabe contestar — el mismo error que `RECARGOS.md` §8.1 ya descartó para el LTV.

| Nivel | Pregunta que contesta | Dónde vive | Default |
|---|---|---|---|
| **Empresa** | ¿Este negocio le escribe a sus clientes? | `company.settings.notifications` (jsonb) | **Apagado** |
| **Usuario** | ¿A qué empleados les llega el resumen de la empresa? | **un permiso**, no una columna | Solo Admin |
| **Cliente** | ¿Este cliente autorizó que le escriban? | `customer.email_consent_at` | Nulo = no |

**Por qué apagado por defecto en la empresa.** Encenderlo para un inquilino existente dispara la tanda de arranque: LA GRAN LEGAL tiene 22 contratos vivos y 8 contratos ya listos para remate. El primer día mandaría avisos sobre hechos de hace semanas. Es el mismo problema de §5, y se resuelve con la misma regla, pero el interruptor apagado es la primera línea de defensa. **Encender es un acto explícito, con una pantalla que dice cuántos correos van a salir.**

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
| Autorización o revocación de consentimiento de un cliente | Habeas Data (§9.2): la autorización tiene que quedar probada con quién la registró |

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

### 9.2 · Consentimiento: la columna nula es la que manda

**Decidido: sin `customer.email_consent_at`, no se manda nada. Tener correo y tener autorización son dos cosas.**

```sql
alter table public.customer
  add column email_consent_at     timestamptz,   -- null = NO autorizado
  add column email_consent_source text,          -- 'counter' | 'import' | ...
  add column email_opt_out_at     timestamptz,   -- revocación (art. 8, Ley 1581)
  add column email_invalid_at     timestamptz;   -- rebotó duro; no volver a intentar
```

| Por qué así | |
|---|---|
| **La ley pide la autorización, no el dato** | Tener el correo de alguien no autoriza a escribirle. La fecha y el origen son la prueba, y `resend_notification` en `audit_log` completa el quién (§7) |
| **Hace imposible el encendido masivo accidental** | Un inquilino que activa los avisos no le escribe a 200 clientes que nunca dijeron sí: les escribe a los que autorizaron. Los demás quedan `suppressed`, contados y visibles |
| **Los 2 correos que existen hoy no tienen autorización** | Se capturaron antes de que esto existiera. **Nacen `suppressed`** y hay que volver a pedirla. Es un costo real y se paga: dos clientes |
| **El opt-out es obligatorio y hace doble trabajo** | Todo correo al cliente lleva *"no me escriban más"*, que escribe `email_opt_out_at`. Es la revocación que exige el art. 8 **y** el mecanismo que evita que un molesto se convierta en una queja de spam que ensucia el dominio de todos |

### 9.3 · Si el correo está mal escrito y le llega a un tercero

Es el caso que no tiene vuelta atrás, y hay que separar dos cosas:

- **Rebota** → se detecta. `bounced`, `email_invalid_at`, cero reintentos, y el cliente aparece en la lista de "revisar correo". **Falla ruidosa.**
- **Se entrega a otra persona** → **no se detecta nunca.** `juan.perez@gmail.com` por `juan.peres@gmail.com` es una dirección que existe, de un desconocido, y Resend reporta `delivered`. **Falla silenciosa, y es la peor del sistema.**

**No hay mitigación después del envío. Toda la mitigación es previa, y son tres:**

1. **Que el cuerpo no lleve cédula ni prenda (§9.1).** Es la única defensa que funciona contra lo indetectable: si llega a un tercero, ese tercero se enteró de que existe un contrato, no de quién es ni de qué dejó empeñado.
2. **Validar el formato en el backend** — hoy no se hace (§1, §13). No atrapa el dedazo verosímil, pero saca la basura.
3. **Confirmar la dirección la primera vez.** El primer correo a un cliente es un *"confirme que este correo es suyo"* que exige una acción; hasta que la haga, los demás quedan `pending`. **Y esa acción va por `POST`, nunca por un `GET` de un solo uso** — el proyecto ya reprodujo ese bug el 03/09/2026: los generadores de vista previa de WhatsApp y los escáneres de Gmail/Outlook **queman el enlace antes que el destinatario** (`auth_admin.py::_app_link`). Un enlace de confirmación auto-consumido por un escáner confirmaría direcciones solo. **Es la misma razón por la que P2, el enlace de acceso, se queda pasándose a mano por WhatsApp.**

> **Suposición marcada:** no sé si la Ley 1581 exige un aviso de privacidad con formato específico en cada comunicación comercial, ni si un recordatorio de cobro cuenta como comunicación comercial. **Esto lo tiene que revisar un abogado, no un documento de diseño** (§12, pregunta 1).

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

| # | Qué | Por qué en este orden |
|---|---|---|
| **1** | **El resumen diario a la empresa (§2.4), empezando por E1 "listos para remate"** | **El primer envío que hay que construir.** Cuatro razones: (a) **100 % entregable hoy** — `app_user.email` es `NOT NULL`, 27 de 27; (b) **cero riesgo de Habeas Data** — el dato se queda dentro de la empresa, va a sus propios usuarios; (c) **cero ambigüedad de marca** — el destinatario es un usuario de Prendo; (d) **ejercita todo el andamio** (Resend, las dos tablas, estados, reintentos, idempotencia, el tercer paso del job) sobre una población donde un bug no cuesta nada. Y el valor es real y medible: **8 contratos listos para rematar en dev ahora mismo**, sin que nadie los mire |
| **2** | **Migrar la invitación (P1) de Supabase Auth a Resend** | Es lo único que está **roto hoy**: `INVITE_RATE_LIMITED` con el SMTP compartido. Reusa todo lo de la fase 1 y no toca al cliente final. **No toca «Generar enlace»**, que es lo que hace que el alta de usuarios funcione sin correo y que no se rompe por esto |
| **3** | **Consentimiento y captura (§1c, §9.2) + validar el correo en el backend** | **Va antes de cualquier correo al cliente, no después.** Sin las columnas de consentimiento, todo envío al cliente es un incumplimiento; sin captura, hay 2 destinatarios. Esta fase no manda ni un correo y es la que habilita las tres siguientes |
| **4** | **Paz y salvo (C3) + abono (C2)** | El primer correo al cliente. Se empieza por el que el cliente **quiere**: el comprobante de que no debe nada. La consecuencia de un fallo es un correo de menos, no una sorpresa. Sirve de prueba real del consentimiento de la fase 3 |
| **5** | **Recordatorios de cuota y prórroga (R1–R4), agrupados por cliente** | El de más valor de negocio y el de más riesgo: llega sin que nadie lo pida, lleva plata y fechas, y es el que estampida si el job falla (§5.3). Exige la ventana de rezago y el tope de §3 **funcionando y probados**, no planeados |
| **6** | **Contrato creado (C1), ampliación (C4), nota crédito (C5), venta (C6/C7)** | Valor real pero menor: el cliente estaba presente cuando pasó y se fue con el papel |
| **7** | **Alertas inmediatas a la empresa (§2.5)** | Deliberadamente al final: su valor depende de que el resumen diario ya tenga la confianza de quien lo recibe |
| **8** | **WhatsApp** | Fuera de alcance. Entra como `channel` nuevo sobre eventos que ya existen (§4.1), y el día que llegue será el canal principal del cliente. **Diseñar para que quepa es parte del trabajo de hoy; construirlo no** |

**Lo que hay que tener listo antes de la fase 1:** el dominio verificado en Resend (ya está), el tope diario confirmado (§10), `notifications.receive_digest` en el seed de permisos, el interruptor por empresa **apagado**, y el tercer paso del job **después** de `recompute_all_statuses` (§5.2). Y **recrear la Fly Machine `nightly-job`** contra la imagen nueva en el mismo despliegue: `fly deploy` **no la actualiza** y esa es, literalmente, la causa de F21-10.

---

## 12. Preguntas de negocio pendientes

Ninguna se puede contestar desde el código. Van en orden de cuánto bloquean.

1. **¿Le avisamos al cliente que su prenda está lista para remate?** La decidí como **no** (§2.2, R5: el aviso de remate va a la empresa) y quiero que quede claro que es **provisional**. El argumento para no hacerlo: avisar que un bien se va a rematar tiene peso legal en Colombia, y hacerlo por un correo cuya entrega no se puede probar es peor que no prometerlo — deja a la compraventa diciendo "le avisamos" sin poder demostrarlo. El argumento para hacerlo: es el aviso que más le importa al cliente y el que más rescata contratos. **Esto lo contesta un abogado, no un diseño.** Y con él: ¿el aviso de prórroga (R3) tiene el mismo peso?
2. **¿Hace falta autorización explícita de Habeas Data para un recordatorio de cobro, o la cubre la relación contractual?** Diseñé por lo estricto: sin `email_consent_at` no sale nada (§9.2). Si la relación contractual ya lo cubre, se puede backfillear el consentimiento de los clientes con contrato vivo y el producto arranca con muchos más destinatarios. Si no, la fase 3 es obligatoria antes de la 4. Es la pregunta que más cambia el calendario.
3. **¿Cuántos días antes se avisa la cuota, y cuántas veces?** Puse 3 días como parámetro sin decidir el valor. Y la de fondo: ¿se avisa **también** cuando ya venció (R2)? Un recordatorio es un favor; un cobro repetido es otra cosa, y la frontera la pone el negocio, no el sistema. **No reusar `grace_days`** (§4.3).
4. **¿El resumen diario le llega también al dueño cuando no hay nada que reportar?** Un correo que dice "todo en orden" prueba que el sistema vive y entrena a abrirlo; treinta seguidos entrenan a archivarlo. Mi recomendación: **sí los primeros 30 días, después solo cuando haya algo** — pero es una decisión de producto.
5. **¿Puede un inquilino redactar sus propios correos?** Lo decidí como **no** (§4.4), con el argumento de que la entregabilidad es un recurso compartido. Si comercialmente hace falta ofrecerlo, no es una fila en `document_template`: es un producto con revisión previa a la activación.
6. **¿Cuál es el umbral de "descuento grande" y de "descuadre grande" para las alertas inmediatas (§2.5)?** Un monto fijo se desactualiza y un porcentaje no dice nada sobre un contrato chico. Hoy no hay con qué medirlo: hay 11 abonos y 13 ventas en septiembre en toda la base. Recomendación: nacer con el umbral en 0 —avisar **todos** los descuentos, que son pocos— y subirlo cuando moleste. **Cerrado de más se nota; abierto de más no** (es el mismo criterio con que se resolvió `TERMINAL_STATUSES` en `rules.py`).
7. **¿`stale_after_days` en cuánto?** Cuántos días de atraso hacen que un recordatorio deje de mandarse (§5.3). Puse el mecanismo, no el número. Mi recomendación: **2 días** — un aviso de "vence en 3 días" mandado el día del vencimiento todavía sirve; mandado una semana después, no.
8. **¿El correo del cliente es de la empresa o de la plataforma?** Un cliente de LA GRAN LEGAL que también es cliente de otra compraventa en Prendo hoy son **dos filas de `customer`**, una por inquilino, cada una con su autorización. Es coherente con todo el modelo (RLS por `company_id`) y creo que es correcto: autorizó a **una** compraventa. Pero significa que un opt-out en una no vale en la otra, y que puede recibir dos correos de dos inquilinos el mismo día. Vale decirlo antes de que alguien lo reporte como un bug.

---

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
- **Un cliente sin `email_consent_at` produce `suppressed`**, aunque tenga correo.
- **Ni la cédula ni la descripción de la prenda aparecen en ningún cuerpo renderizado.** Test sobre el render, no sobre la plantilla — un test que mira la plantilla no cubre el `payload`.
- **El tope por cliente y día se hace cumplir en un solo lugar**, no en cada productor de eventos. Un punto de verdad, como el alcance de sede en `SUCURSALES.md` §8.4.
- **Códigos de error nuevos en `API_GUIDE.md` §15**, con `tests/unit/test_error_catalog.py` en verde **en las dos direcciones** — un código sin documentar rompe la suite. Previsibles: `NOTIFICATIONS_DISABLED`, `CUSTOMER_NOT_NOTIFIABLE`, `NOTIFICATION_ALREADY_SENT`.
- **Permisos nuevos en el seed** (`notifications.receive_digest`, `notifications.receive_alerts`) y en el mapa de `scripts/qa/map_endpoints.py`.
- **Etiquetas en español** para las acciones nuevas de `audit_log` en `frontend-starter/src/features/audit/labels.ts` — si no, la pantalla muestra `resend_notification` en crudo. Ya pasó con doce acciones.
- **Verificado en vivo, no solo en tests:** un correo real recibido, con el remitente de §8 tal como se ve en Gmail y en Outlook. *"Push ok" no prueba nada.*
