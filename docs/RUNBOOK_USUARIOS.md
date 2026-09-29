# Runbook — alta de usuarios y "no se pudo guardar la contraseña"

> Abrir este archivo cuando alguien reporte que **no puede crear un usuario** o que **no puede poner su contraseña**. Empieza por §1 (el diagnóstico ya resuelto), sigue por §4 (árbol de decisión) si el síntoma es otro.

---

## 1. El bug de "no se pudo guardar la contraseña" — causa encontrada el 03/09/2026

**Síntoma reportado** (empresa *La Legal*): el admin invita a alguien, genera el enlace, se lo pasa. La persona lo abre, ve la pantalla de "Crea tu contraseña", la escribe, y al guardar sale **"No se pudo guardar la contraseña. Intenta de nuevo."** Reintentar nunca funciona, así que el usuario nunca queda creado.

**Por qué nadie podía reproducirlo:** a quien probaba el flujo abriendo el enlace *directamente* le funcionaba siempre. Cuatro reproducciones limpias en vivo, todas exitosas.

### La causa

El enlace que Supabase devuelve (`action_link`) es un **GET de un solo uso**:

```
https://<proyecto>.supabase.co/auth/v1/verify?token=<token>&type=invite
```

Basta con **pedir esa URL** para quemarla. No hace falta un navegador ni una persona:

```bash
curl -A "WhatsApp/2.23" "$ACTION_LINK"
#  → 302 …/auth/callback#access_token=eyJhbGci...      ← el token se consumió

curl "$ACTION_LINK"
#  → 302 …/auth/callback#error=access_denied&error_code=otp_expired
```

Eso es exactamente lo que hacen los **generadores de vista previa**: WhatsApp, Telegram y Slack piden la URL apenas se pega en el chat, para armar la tarjetita con título e imagen. Los escáneres de correo hacen lo mismo (Gmail, Outlook Safe Links, antivirus corporativos).

Entonces:

1. El admin pega el enlace en WhatsApp.
2. WhatsApp lo pide para la previa → **el token se quema ahí mismo**, sin que nadie lo toque.
3. La persona toca el enlace minutos después → llega a `/auth/callback` con `error_code=otp_expired`, **sin sesión**.
4. La app le muestra igual el formulario de contraseña (no sabía distinguir el caso).
5. Al guardar, `updateUser` falla porque no hay sesión → *"No se pudo guardar la contraseña. Intenta de nuevo."*

**El rastro que dejaba en la base confundía todavía más:** el usuario quedaba con `last_sign_in_at` puesto — lo puso el crawler — pero sin contraseña. Parecía que la persona había entrado y no había guardado nada.

### El arreglo (03/09/2026)

El backend ya no entrega el `action_link` de GoTrue. Entrega un enlace **a nuestra propia app**, con el `hashed_token` que `generate_link` también devuelve:

```
https://<app>/auth/callback?token_hash=<hashed_token>&type=invite|recovery
```

`/auth/callback` lo canjea con `supabase.auth.verifyOtp({ token_hash, type })`, que es un **POST**. Un crawler que haga GET sobre esa URL solo se baja el HTML de la SPA y **no quema nada**.

De regalo desaparece un segundo problema: acá no hay redirect de Supabase de por medio, así que ya no importa si la URL está en la lista de "Redirect URLs" permitidas (ver §3).

Y si aun así llega un enlace muerto (uno viejo, o uno realmente vencido), la pantalla ahora lo dice: **"Este enlace ya se usó o venció"** y pide que el administrador genere uno nuevo, en vez de mandar a reintentar algo que no puede funcionar. Desde el 24/09 (front `cf1285a`) el canje además **espera un clic en «Continuar»**: al cargar la página no se gasta el token, así que tampoco lo quema un escáner de correo que ejecute la página. Y si el canje falla por red, la pantalla ofrece «Intentar de nuevo» en vez de declararlo muerto.

Código: `backend-starter/app/modules/identity/auth_admin.py::_app_link` · `frontend-starter/src/features/auth/pages/AuthCallbackPage.tsx` · `frontend-starter/src/lib/auth/supabase.ts` (`initialUrl`).

---

## 2. El flujo completo, paso a paso

```
Admin  ──POST /identity/invitations──►  Backend
                                          ├─ crea el usuario en Supabase Auth (service_role)
                                          └─ crea app_user  → status = "invited"

           send_email: true                     send_email: false  ← el camino normal
     Supabase manda el correo            El backend devuelve el enlace y el admin lo entrega
     (plantilla no editable: frágil)     (a prueba de crawlers, sin cuota)
                     │                                   │
                     └───────────────┬───────────────────┘
                                     ▼
              La persona abre  /auth/callback?token_hash=…&type=invite
                                     │
                        verifyOtp (POST) → sesión activa
                                     ▼
                        Elige contraseña → updateUser
                                     ▼
                  Primer request al backend → status: invited → active
```

**Endpoints:**

| Acción | Endpoint | Permiso |
|---|---|---|
| Invitar | `POST /api/v1/identity/invitations` | `identity.manage_users` |
| Enlace para recuperar contraseña | `POST /api/v1/identity/users/{id}/recovery-link` | `identity.manage_users` |

Ambos se auditan. **El enlace nunca se escribe en un log ni en `audit_log`**: es una credencial — quien lo tenga puede entrar como esa persona.

**No hay registro público** (`disable_signup: true`, verificado en vivo). El alta es solo por invitación.

---

## 3. La otra trampa: `redirect_to` que Supabase ignora en silencio

Aplica al camino del **correo** (`send_email: true`), que todavía usa la plantilla de Supabase.

Si el `redirect_to` no está en la lista de **Redirect URLs** permitidas del proyecto (Authentication → URL Configuration), Supabase **no falla**: la reemplaza por la *Site URL* y sigue. Comprobado hoy, en vivo:

| Se pidió | Supabase devolvió |
|---|---|
| `https://la-legal-front-end.vercel.app/auth/callback` | `https://la-legal-front-end-git-dev-…vercel.app` ← **sin `/auth/callback`** |
| `https://la-legal-front-end-git-dev-…vercel.app/auth/callback` | igual, correcto |

Consecuencia cuando cae en la Site URL sin `/auth/callback`: **la persona entra a la app con sesión activa y nadie le pide contraseña.** Después cierra sesión y no puede volver a entrar, porque nunca puso una.

**Resuelto (03/09/2026):** Mateo agregó a *Redirect URLs* la URL de producción. Verificado antes y después: ahora Supabase respeta las dos.

**Y las plantillas de correo NO se pueden editar** en el plan actual del proyecto (04/09/2026). Así que el enlace que manda Supabase conserva los dos problemas que el copiado a mano ya no tiene: depende de esa lista, y lo puede quemar una vista previa.

**La salida fue dejar de depender del correo, no arreglarlo.** El único camino que lo exigía era el alta de una empresa nueva, que invitaba al primer admin con `send_email=true` y tiraba el enlace. Desde el 04/09 el alta **devuelve el enlace** y lo entrega el super-admin. Con eso:

| Camino | Cómo llega el enlace | ¿Depende del correo? |
|---|---|---|
| Alta de una empresa nueva | Lo devuelve el panel de plataforma | **No** |
| Invitar a un empleado | "Generar enlace" en el diálogo | **No** |
| Recuperar contraseña (con admin cerca) | "Generar enlace" en su ficha | **No** |
| Cambiar la propia contraseña | En `/perfil`, con la actual | **No** |
| "¿Olvidaste tu contraseña?" del login | Correo de Supabase | **Sí** — es el único, y es el que puede fallar |

Ese último queda como salida de emergencia y **su peor caso ya no es silencioso**: si el enlace llega quemado, la pantalla dice "Este enlace ya se usó o venció".

---

## 4. Árbol de decisión

| Lo que reporta la persona | Causa más probable | Qué hacer |
|---|---|---|
| **"No se pudo guardar la contraseña"** | Enlace quemado por una vista previa (§1) | Generar uno nuevo. Con el arreglo de hoy ya no debería pasar; si pasa, la pantalla ahora dice "Este enlace ya se usó". |
| **"Este enlace ya se usó o venció"** | El enlace se abrió antes — el admin lo probó, o se reenvió uno viejo | Generar uno nuevo y abrirlo apenas llegue. Nunca "probar" un enlace antes de entregarlo. |
| **"Link inválido o expirado"** | Se abrió `/auth/callback` sin token (marcador, historial, refresh después de canjear) | Generar uno nuevo. |
| **Entró a la app sin que le pidieran contraseña** | `redirect_to` cayó en la Site URL (§3) | Arreglar la lista de Redirect URLs. Mientras tanto, usar "Generar enlace" en vez del correo. |
| **"Mínimo 8 caracteres" / no la acepta** | Validación del formulario | Contraseña de 8 o más. |
| **No llega el correo** | Desde el 24/09 (backend `fbf7b8a`) la invitación sale por **nuestro** correo (Resend) y no por Supabase. Mirar su entrega en Configuración → Notificaciones → «Correos recientes»: `failed` se reintenta solo (+1 h/+6 h/+24 h), `dead` no. Si revisaste spam y no está | Usar **"Generar enlace"** (no depende del correo). |
| **`INVITE_RATE_LIMITED` al invitar** | Solo puede pasar si el API perdió `RESEND_API_KEY` o `FRONTEND_URL`: entonces vuelve al correo de Supabase, con su cuota. La respuesta de invitar lo delata con `invite_delivery: "email_supabase"` | Usar **"Generar enlace"** y revisar los secrets del API en Fly. |
| **"Este usuario está inactivo"** al pedir enlace de recuperación | Es a propósito | Reactivarlo primero — darle el enlace sería deshacer la desactivación sin dejar registro. |
| **"Ya invitaste a esta persona"** (`USER_ALREADY_INVITED`) | Se invitó dos veces | Abrir su ficha en Usuarios → **Generar enlace de activación**. Invitar de nuevo anularía el enlace anterior. |
| **"Ese correo ya tiene una cuenta"** (`EMAIL_ALREADY_REGISTERED`) | El correo está registrado en otra empresa | Usar otro correo, o revisar con el super-admin dónde está esa cuenta. |
| **"Ya no tiene cuenta de acceso"** (`AUTH_ACCOUNT_MISSING`) | Lo borraron desde el panel de Supabase; la fila quedó huérfana | Desactivarlo e invitar de nuevo a esa persona. |
| **"No puedes desactivar tu propia cuenta"** | Es a propósito | Que lo haga otro administrador. |
| **Aparece "Activo" pero no puede entrar** | Ya no debería pasar (arreglado 04/09). Si pasa, es un usuario de antes del arreglo | Generar el enlace desde su ficha para que ponga contraseña. |

---

## 5. Cómo diagnosticar en vivo

**¿La persona llegó a poner contraseña?** Se ve en `auth.users`: si `last_sign_in_at` está puesto pero nunca hubo un `updated_at` posterior de varios segundos, abrió el enlace y no guardó nada.

**Reproducir el consumo por GET** (usa un usuario de prueba, quema el enlace):

```bash
cd backend-starter
SR=$(grep -m1 '^SUPABASE_SERVICE_ROLE_KEY=' .env | cut -d= -f2-)
SU=$(grep -m1 '^SUPABASE_URL=' .env | cut -d= -f2-)
curl -s -X POST "$SU/auth/v1/admin/generate_link" \
  -H "apikey: $SR" -H "Authorization: Bearer $SR" -H "Content-Type: application/json" \
  -d '{"type":"recovery","email":"UNO_DE_PRUEBA@ejemplo.com"}' -o /tmp/link.json
# el primer GET lo quema; el segundo ya sale con otp_expired
```

**Verificar qué está servido de verdad** antes de culpar al código:

```bash
JS=$(curl -s https://la-legal-front-end.vercel.app/ | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1)
curl -s "https://la-legal-front-end.vercel.app$JS" | grep -c "Este enlace ya se usó"
```

**Limpiar usuarios de prueba** cuando termines — quedan en `auth.users` y en `app_user`.

---

## 7. "No se pueden crear contratos" — casi siempre es la caja

**Caso real (LA GRAN LEGAL, 23/08 → 03/09/2026): once días sin poder crear un solo contrato.** No era un bug de contratos: **nunca habían abierto una sesión de caja.** El desembolso del préstamo sale en efectivo, y el efectivo exige caja abierta — así que cada intento moría con `CASH_SESSION_NOT_OPEN`, para todos los usuarios, siempre.

Lo que lo volvió invisible fueron dos mensajes:

1. **La franja global decía "No se pudo consultar el estado de la caja"** en vez de "Caja cerrada". `GET /cashbox/sessions/current` devolvía `NOT_FOUND` y el front esperaba `CASH_SESSION_NOT_OPEN`; como nunca coincidía, caía en la rama de error. Toda la rama de caja cerrada del banner —con su botón "Abrir caja" y su "pídele a un responsable que la abra"— era **código muerto que nunca se había visto**. Arreglado el 03/09 (`NoOpenCashSessionError`).
2. **El diálogo no le decía nada útil a quien no puede abrir la caja.** Sin `cashbox.open_close` salía "Caja cerrada" + "Entendido", sin nombrar la acción ni a quién pedírsela. Arreglado el mismo día.

### Antes de buscar un bug en contratos, revisar en este orden

| # | Comprobación | Cómo se ve cuando falla |
|---|---|---|
| 1 | **¿Hay una sesión de caja abierta hoy?** | La franja bajo la barra superior dice "Caja cerrada". El diálogo al guardar dice lo mismo. |
| 2 | ¿El rol tiene `contracts.create`? | El menú no muestra "Nuevo contrato" y la ruta redirige al inicio. |
| 3 | ¿Hay una categoría de **nivel 3** para empeño? | El selector de categoría sale vacío con el aviso "créalas en Catálogos". |
| 4 | ¿Esa categoría, o algún padre suyo, tiene **plazo** y **ventana de mora**? | Error explícito al guardar, nombrando la categoría. |
| 5 | ¿La suscripción está vigente? | Pantalla de bloqueo (`SUBSCRIPTION_EXPIRED`). |

Consulta directa para responder las cinco de una:

```sql
select c.name,
  (select count(*) from cash_session s where s.company_id=c.id and s.status='open') as caja_abierta,
  (select count(*) from category ct where ct.company_id=c.id and ct.level=3
     and ct.applies_to in ('pawn','both') and ct.active)                            as categorias_hoja,
  (select count(*) from account a where a.company_id=c.id and a.type='cash')        as cuentas_efectivo,
  (select sub.expires_at from subscription sub where sub.company_id=c.id)           as vence
from company c order by c.name;
```

**Ojo con el orden de los permisos:** un rol con `contracts.create` pero sin `cashbox.open_close` depende de que otra persona abra la caja cada día. Es una decisión legítima (quien no maneja el arqueo no lo abre), pero hay que saberla: si el administrador no abre la caja, sus asesores no pueden trabajar.

## 8. Auditoría completa de los flujos de identidad (04/09/2026)

Pedida por Mateo tras el incidente: *"analiza todos los flujos y escenarios de identidad… todo lo que pueda pasar, para evitar en el futuro errores como los que el cliente vio hoy"*.

Se recorrieron los ocho flujos contra el proyecto dev, con una empresa espejo creada para eso. **Seis defectos encontrados, los seis arreglados y verificados en vivo.** Todos comparten la misma forma: *el sistema sabía qué pasaba y no lo decía, o decía otra cosa.*

### Los estados de un usuario, y qué significan de verdad

| Estado | Qué significa **ahora** | Qué se ve en la lista |
|---|---|---|
| `invited` | Existe, tiene enlace, **todavía no ha entrado con contraseña propia** | Invitado |
| `active` | **Ya entró con su propia contraseña** — puede entrar solo | Activo |
| `inactive` | Desactivado a propósito. El backend le niega todo | Inactivo |

> **Lo que cambió.** Antes, `active` significaba solo "hizo algún request con un JWT válido" — y abrir el enlace de invitación **ya produce un JWT válido**. Ver defecto 1.

### Los seis defectos

**1. `invited → active` sin que existiera ninguna contraseña.** *(el más grave)*

El código asumía: *"si llegó hasta acá con un JWT válido, ya completó el flujo de invitación (puso contraseña)"*. Falso. Comprobado: canjear el enlace y hacer **un solo request** dejaba al usuario en `active` sin clave; después Supabase le negaba el login con un 400. **El admin veía "Activo" en la lista —todo en orden— mientras esa persona estaba bloqueada para siempre**, y nada en pantalla lo delataba.

Arreglo: el claim `amr` del token distingue exactamente los dos casos (`otp` para una sesión de enlace, `password` para un login de verdad). Y el front, apenas la persona guarda su contraseña, entra con ella — así la activación es inmediata y de paso se comprueba que la clave recién creada sirve.

**2. Reinvitar al mismo correo → HTTP 500 en texto plano.**

Y es lo más normal del mundo hacerlo: *"no le llegó, mándaselo otra vez"*. Reventaba el índice único de `app_user` sin envelope de error, así que el front lo mostraba como "Ocurrió un error inesperado". Peor: Supabase **ya había regenerado el enlace**, dejando muerto el que el admin quizá acababa de mandar por WhatsApp. Ahora es un 409 que nombra la acción correcta — generar el enlace desde la ficha de esa persona.

**3. Invitar un correo ya registrado → 502 "No se pudo invitar en Supabase Auth".**

Un 502 se lee como "el sistema está roto" y manda a reintentar en círculos — que es exactamente la forma que toma el reporte *"no se pueden crear usuarios"*. Ahora es un 409 que dice qué hacer.

**4. No se podía cambiar la propia contraseña.**

No existía en ninguna parte de la app. Quien quería cambiarla —porque alguien se la vio, porque el admin se la generó— dependía del correo de recuperación (limitado a unos pocos envíos por hora) o de pedirle un enlace al administrador, **que es una credencial que el administrador también ve**. Ahora está en `/perfil`, y se verifica la actual entrando con ella: Supabase no la pide, así que sin eso bastaba una pantalla desatendida un minuto.

**5. Un usuario borrado desde el panel de Supabase seguía listado como si nada**, y darle acceso moría con un 502. Es un dato descuadrado, no una falla; ahora lo dice y explica cómo repararlo.

**6. Desactivarse a uno mismo lo impedía solo la UI.** Ocultar no es proteger: un admin que no fuera el último podía dejarse fuera de su propia empresa con un request a mano.

### Lo que sí estaba bien (comprobado, no supuesto)

- **Empleado desactivado con sesión abierta:** el backend le niega el request, el cliente cierra la sesión y la pantalla de ingreso explica *"Tu usuario o tu empresa están inactivos. Contacta a tu administrador."* Verificado en el navegador.
- **Último administrador:** no se puede desactivar, ni cambiarle el rol, ni quitarle el permiso al único rol que lo tiene. Los tres caminos están cerrados.
- **Aislamiento entre empresas:** invitar con un rol de otra empresa, o tocar un usuario ajeno, responde "no existe en esta empresa" — nunca confirma que exista en otra.
- **El enlace nunca se escribe en un log ni en `audit_log`**, y toda acción sensible queda auditada con quién la hizo y sobre quién.

### Lo que queda anotado, sin arreglar

- **Desactivar no cierra la sesión de Supabase.** El efecto neto es correcto —el backend la rechaza y el front cierra sesión—, pero durante hasta **30 segundos** el cache de `CurrentUser` deja pasar requests de alguien recién desactivado. Aceptable para el caso de uso (un empleado que se va), no para una expulsión urgente.
- **El correo no se puede cambiar** desde la app. Es la identidad en Supabase Auth y cambiarlo es otro flujo, con verificación.
- **Las plantillas de correo** (invitación y recuperación) siguen usando `{{ .ConfirmationURL }}`, así que ese camino conserva los dos problemas que el enlace copiado ya no tiene: depende de la lista de Redirect URLs y lo pueden quemar los escáneres. Ver §3.

### La regla que resume las seis

**Un estado que el sistema muestra tiene que ser el estado real, y un error tiene que nombrar la acción que falta.** Los seis defectos eran la misma cosa: el sistema sabía qué pasaba —que no había contraseña, que ese correo ya existía, que la cuenta estaba borrada— y en su lugar mostraba un badge verde o un 502.

## 6. Reglas que salieron de acá

- **Un token de un solo uso no puede viajar en una URL que alguien pueda pedir por GET.** Media internet abre los enlaces antes que el destinatario.
- **Un mensaje de error que sirve para todas las causas no sirve para ninguna.** "Intenta de nuevo" es el peor consejo posible cuando reintentar es imposible.
- **Una configuración que se ignora en silencio es peor que una que falla.** Supabase descarta un `redirect_to` no permitido sin avisar, y el síntoma aparece tres pasos después.
- **Que el flujo funcione cuando *tú* lo pruebas no significa que funcione.** La diferencia estaba en cómo llegaba el enlace, no en el código.
- **Un código de error es un contrato entre dos capas, y nadie lo compila.** El backend decía `NOT_FOUND` y el front escuchaba `CASH_SESSION_NOT_OPEN`; ni el tipado ni los tests lo notaron porque el test miraba solo el status. Un test que verifica el status y no el código no cubre nada.
- **Una rama de UI que nunca se ha visto no está escrita, está pendiente.** El banner tenía "Caja cerrada" con su botón y su aviso desde hacía meses, perfectamente redactados, y ningún usuario los vio jamás.
- **Un diálogo que dice "no puedes" sin decir "quién sí" es un callejón sin salida.** La persona no vuelve a intentarlo: deja de usar la función.
