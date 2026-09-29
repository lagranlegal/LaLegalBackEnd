# Operación — ambientes, deploy, trampas y runbooks

> **Qué es.** Cómo se despliega y se opera el ambiente de hoy (dev), las trampas que ya costaron tiempo y los
> runbooks de lo que más falla. Para montar producción: [`PRODUCCION.md`](PRODUCCION.md). Para cómo está
> construido el backend: [`ARQUITECTURA.md`](ARQUITECTURA.md).
>
> **La regla que resume todo el documento: guardar no es aplicar.** Cada capa tiene un paso extra entre guardar
> y surtir efecto, y ninguna avisa. Se verifica el efecto sobre lo **servido**, nunca la pantalla de configuración.

## 1. Ambientes

**Hoy solo existe dev**, y es lo que usa el primer cliente: sus datos reales conviven con los de prueba en la misma
base (Ley 1581: tratarla como producción).

| Pieza | Dónde | Notas |
|---|---|---|
| Front | Vercel, **`dev.prendo.com.co`** | Production Branch de Vercel = **`dev`**; el apex `prendo.com.co` y `www` redirigen 308 a `dev.` |
| API | Fly.io, **`api-dev.prendo.com.co`** | la app se llama `compraventa-backend-dev` (Fly no renombra); región `sjc`, junto a la base; `auto_stop`, así que el primer request tras un rato tarda unos segundos |
| Job nocturno | Fly Machine `nightly-job` en la misma app, `--schedule daily` | fuera del process group: ver §3 |
| Base, Auth, Storage | un proyecto Supabase (el ref sale de `SUPABASE_URL` en `.env`) | signups públicos cerrados |
| Correo | Resend sobre `prendo.com.co` | invitaciones, recuperación y avisos |
| Repos | `backend-starter` y `frontend-starter`, rama por defecto **`dev`** | los workflows programados de GitHub **solo corren desde la rama por defecto**: si alguien la cambia, los guardianes dejan de correr sin avisar |

**Un hostname por ambiente.** `dev.` y `api-dev.` son de dev para siempre; el apex y `api.` quedan reservados
para prod. La URL de la app queda embebida en las Redirect URLs de Supabase, en los enlaces ya enviados, en CORS,
en el CSP y en los marcadores del cliente: un hostname que cambia de ambiente hace que todo eso abra, el día del
corte, **otra base con datos reales y sin un solo error**. Las URLs viejas (`*.vercel.app`, `*.fly.dev`) siguen
vivas pero el CSP del front bloquea la API vieja: **nunca** ponerlas en un `.env`.

## 2. Desplegar dev

**Orden, sin excepciones:**

1. **Migraciones** en la base remota: `supabase db push --linked` (aplica **todas** las pendientes de golpe).
   - Una migración **aditiva** va antes del deploy; una que **contrae** (NOT NULL, DROP COLUMN) va **después**,
     cuando ningún código desplegado dependa de lo que se quita. Si hace falta "aplicar A → deploy → aplicar B",
     el paso A va con `psql`, porque `db push` aplicaría las dos.
   - Una migración nueva va también en la base **local** de tests (`supabase db reset` o `migration up`).
2. **Push** del backend (`git push origin dev`).
3. **`./scripts/deploy_dev.sh`** — frena si hay cambios sin commitear o sin pushear, o migraciones sin aplicar;
   hace `fly deploy`; actualiza la Machine del job a la **misma imagen** con `flyctl machine update` (nunca la
   destruye); corre los dos guardianes y comprueba que la API responde. **Nunca un `fly deploy` pelado**: deja el
   job con la imagen vieja.
4. **Verificar** lo servido (§4.1) y, si hubo cambio de contrato de API, `npm run gen:api` en el front contra el
   `/openapi.json` en vivo.
5. **Push del front** (Vercel despliega solo desde `dev`). **Si el cambio toca los dos repos, backend primero**:
   el front genera sus tipos del backend desplegado.

El agente no despliega: el clasificador de permisos bloquea `fly deploy`, `secrets set`, `machine update/start`
y a veces `db push`/`git push`. **El deploy lo corre Mateo**; el agente deja el orden escrito.

## 3. El job nocturno

Qué hace y en qué orden: [`ARQUITECTURA.md`](ARQUITECTURA.md) §11. Lo operativo:

- **No se actualiza con `fly deploy` ni con `fly secrets set`**: no pertenece al process group de la app. Se
  actualiza con `flyctl machine update <id> --image <imagen del release>` (lo hace `deploy_dev.sh`). **No se
  destruye ni se recrea**: recrearla es justo lo que la dejó una vez sin `schedule`, y borrarla "por huérfana" ya
  dejó doce días sin vencer suscripciones ni recalcular contratos (una prenda lista para remate no aparecía).
- **Su ausencia es silenciosa**: no hay health check. Por eso los guardianes.
- **¿Corrió anoche?** `select max(occurred_on) from notification_event where event_type = 'company_daily_digest';`
  (el resumen se registra salga o no), o buscar `job_nocturno_completado` en los logs.
- **Hipótesis abierta**: cada `machine update` podría reiniciar el reloj del `--schedule daily` (con deploys
  seguidos, el job no corre). Cómo medirla: un día sin deploys, ver si ese `max(occurred_on)` avanza. Si se
  confirma, `deploy_dev.sh` debería lanzar una corrida (`flyctl machine start <id>`) al terminar.

### Los guardianes

| Script | Vigila | Salida |
|---|---|---|
| `scripts/qa/verificar_job_nocturno.py` | que la Machine exista, tenga `schedule` y corra la imagen desplegada; imprime el comando exacto para arreglarla | 0 sano · 1 roto · **2 no se pudo verificar** |
| `scripts/qa/verificar_cadenas.py` | invariantes sobre datos vivos (cadenas de ampliación, estados) | igual |

"No se pudo verificar" no es "está sano": por eso existe el 2. Corren en cada `deploy_dev.sh` y a diario en
GitHub Actions (`.github/workflows/guardianes.yml`, desde la rama por defecto; un workflow nuevo se corre a mano
una vez antes de confiar en su horario).

## 4. Trampas del entorno

### 4.1 Guardar no es aplicar, capa por capa

| Guardaste… | …y todavía falta |
|---|---|
| `git push` | Vercel despliega el front; **Fly no despliega nada** |
| `fly deploy` | la Machine del job sigue con la imagen vieja (§3) |
| `fly secrets set` | reinicia la app, **no** la Machine del job |
| una `VITE_*` en Vercel | se hornea en el build: **sin redeploy no hace nada**, y el dashboard muestra el valor nuevo |
| una plantilla de correo en Supabase | la cachea unos minutos |
| un artifact republicado | el enlace compartido puede servir una versión **clavada**: hay que mover el pin a mano |
| un workflow en una rama | `schedule`/`workflow_dispatch` solo corren desde la rama por defecto |

**Verificar el bundle servido**, no el commit ni el dashboard:

```bash
JS=$(curl -s https://dev.prendo.com.co/ | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1)
curl -s "https://dev.prendo.com.co$JS" | grep -c "TextoQueAcabasDeAgregar"   # > 0
curl -s "https://dev.prendo.com.co$JS" | grep -c 'api-dev\.prendo\.com\.co'   # > 0
curl -s https://api-dev.prendo.com.co/openapi.json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["paths"]), "rutas")'
```

Y un arreglo desplegado no prueba que arregle lo que se midió: se vuelve a medir sobre lo servido.

### 4.2 Bases y cuentas

- **Dos bases.** Los tests corren contra el Postgres **local** (`supabase start`, `127.0.0.1:54322`); `.env`,
  `psql` y `db push` apuntan a la **remota**. **Sin Docker levantado, `pytest` pasa con casi todo saltado**: un
  "95 passed" no es la suite.
- **Dos cuentas de Supabase.** El CLI de la máquina está autenticado con otra cuenta y `supabase projects list`
  muestra un proyecto ajeno. **El ref correcto sale siempre de `SUPABASE_URL`.**
- **Nunca `supabase config push`**: empuja el `config.toml` local completo, que trae `enable_signup = true`
  (reabriría los registros públicos), pisa el Site URL y baja el límite de correos. Auth se toca con un `PATCH`
  quirúrgico a la Management API, comparando antes y después ([`PRODUCCION.md`](PRODUCCION.md) §1.8).
- **Lecturas sobre la remota con `BEGIN TRANSACTION READ ONLY` explícito.** `PGOPTIONS` con
  `default_transaction_read_only` **no llega** a Supavisor: la variable dice `off` y un `UPDATE` pasa. Una barrera
  que se ignora en silencio no es una barrera.
- **Datos reales: el primer cliente (LA GRAN LEGAL), «La Legal» y «Empresa Demo Front» no se tocan** sin
  autorización explícita. Pruebas y capturas contra empresas `ZZ AI — *` (§8). Nunca copiar nombres, cédulas o
  fotos de clientes reales a un documento, un test o un informe.

### 4.3 Front, dominio y Auth

- **Reemplazar una `VITE_*`**: `vercel env rm` + `vercel env add … --no-sensitive` (las *sensitive* se rechazan en
  Production y, como el `rm` ya pasó, la variable queda borrada), `vercel env pull` para confirmar que están **las
  tres**, y recién entonces `vercel redeploy`. La key de Supabase que va al front es solo la anon/publishable; la
  `service_role` jamás.
- **El CSP no vive en `vercel.json`** (no interpola variables): `connect-src`/`img-src` los genera `vite.config.ts`
  desde `VITE_API_URL`/`VITE_SUPABASE_URL`; `vercel.json` conserva lo que solo vale como header. El build falla a
  propósito si faltan las variables. El script anti-parpadeo del tema va por hash SHA-256 en el CSP: si se edita,
  el hash cambia, y su fallo no deja error de JS.
- **Site URL y Redirect URLs** (Supabase → Authentication → URL Configuration): el backend manda
  `redirect_to = {FRONTEND_URL}/auth/callback`; si no está en la lista, **Supabase la ignora en silencio** y cae en
  el Site URL. **Desde que `/` es la landing, el Site URL cae en la página de venta**, y no se arregla apuntándolo
  a `/inicio` (las plantillas concatenan `{{ .SiteURL }}/auth/callback`): la defensa es que el `redirect_to` esté
  en la lista. `FRONTEND_URL` del backend y esa lista tienen que coincidir exactamente. Sin comodín para previews
  de Vercel, a propósito.
- **HSTS**: `max-age=63072000; includeSubDomains` en `vercel.json` (todo subdominio nuevo tiene que servir HTTPS
  válido). **`preload` no**, todavía: salir de esa lista tarda meses; se decide con prod estable.
- **Un dominio en Fly**: `flyctl certs add` + `A` **y `AAAA`** (la IPv6 es dedicada; sin `AAAA`, Fly pide un TXT).
  Un certificado en «Issuing…» varios minutos se parece a un DNS mal puesto: esperar antes de tocar. Los redirects
  del apex en Vercel se configuran por API (su CLI no los soporta).
- **CORS**: dev acepta `localhost:5173/3000`, `*.vercel.app` y `CORS_ALLOW_ORIGINS`; prod **solo**
  `CORS_ALLOW_ORIGINS` (sin ese secret, rechaza todo). Un `vite preview` local contra la API de dev no pasa:
  probar en vivo exige desplegar.
- **Playwright sí está** en esta máquina, vía el caché de npx, sin navegador propio: se lanza con
  `channel: 'chrome'`. "No hay herramienta X en este entorno" es una afirmación con fecha de vencimiento.
- **Los cambios de permisos tardan hasta 60 s** en verse (caché en los dos lados).

### 4.4 Correo

- **Resend** envía todo (3.000/mes en el plan de hoy). Sin `RESEND_API_KEY` en la **app** (no solo en el job), la
  invitación vuelve al correo de Supabase, con su cuota y su plantilla; la respuesta de invitar lo delata con
  `invite_delivery: "email_supabase"`.
- **DMARC**: publicar `p=none` primero; **un Gmail cualquiera no recibe reportes `rua`** de otro dominio: hace
  falta un agregador. Pendiente, junto con la prueba de spam en Gmail/Outlook/corporativo.
- **El dominio solo envía**: `contacto@prendo.com.co` no es un buzón hasta que alguien lo cree o redirija.
- **Al diagnosticar un enlace**, el `iat` del token es cuándo se **canjeó**, no cuándo se envió; borrar los correos
  viejos de la bandeja antes de probar.
- Estado de cada entrega: Configuración → Notificaciones → «Correos recientes». `failed` se reintenta solo
  (+1 h, +6 h, +24 h); `dead` no.

## 5. Tests

- `supabase start` (Docker) antes; `pytest -q tests/unit tests/rls` y `pytest -q tests/integration`.
- La suite completa tarda más de lo que aguanta una llamada de herramienta del agente: se corre **por tramos**
  (`tests/unit tests/rls`, y `tests/integration` en grupos de archivos), cada uno con un tope de tiempo, p. ej.
  `perl -e 'alarm 280; exec @ARGV' .venv/bin/python -m pytest -q tests/integration/test_contracts.py`.
- `ruff check . && ruff format --check . && mypy app`. La CI (`ci.yml`) corre lo mismo en cada push a `dev`/`main`
  y en cada PR, con Postgres efímero. **Una CI que siempre falla no dice nada**: se mantiene verde.
- Método de QA y bugs abiertos: [`QA.md`](QA.md).

## 6. Runbook: alta de usuarios y "no pude poner la contraseña"

### 6.1 El flujo

```
Admin ──POST /identity/invitations──► Backend ── crea el usuario en Supabase Auth (service_role)
                                          └──── app_user status = invited
     El enlace llega por NUESTRO correo (Resend) o el admin lo copia con «Generar enlace»
                                          ▼
   /auth/callback?token_hash=…&type=invite  →  clic en «Continuar»  →  verifyOtp (POST) → sesión
                                          ▼
                 elige contraseña (updateUser) → entra con ella → status: active
```

| Acción | Endpoint | Permiso |
|---|---|---|
| Invitar | `POST /api/v1/identity/invitations` | `identity.manage_users` |
| Enlace de activación o recuperación | `POST /api/v1/identity/users/{id}/recovery-link` | `identity.manage_users` |
| Alta de empresa (devuelve el enlace del primer admin) | `POST /api/v1/platform/companies` | super-admin |

Todos se auditan; **el enlace nunca se escribe en un log ni en `audit_log`**: quien lo tenga entra como esa
persona. Ningún camino de alta depende del correo: «Generar enlace» por WhatsApp sirve siempre, porque el canje es
por POST tras un clic y una vista previa no lo quema. Cambiar la propia contraseña está en `/perfil` (pide la
actual). El correo no se puede cambiar desde la app.

### 6.2 Árbol de decisión

| Lo que reporta la persona | Causa más probable | Qué hacer |
|---|---|---|
| «No se pudo guardar la contraseña» | enlace ya consumido | generar uno nuevo |
| «Este enlace ya se usó o venció» | el admin lo "probó", o se reenvió uno viejo | generar uno nuevo; **nunca probar un enlace antes de entregarlo** |
| «Link inválido o expirado» | abrió `/auth/callback` sin token (marcador, refresh tras canjear) | generar uno nuevo |
| Entró sin que le pidieran contraseña | un `redirect_to` cayó en el Site URL (§4.3) | arreglar la lista de Redirect URLs; mientras, «Generar enlace» |
| No llega el correo | mirar «Correos recientes» | «Generar enlace» (no depende del correo) |
| `INVITE_RATE_LIMITED` | la app perdió `RESEND_API_KEY` o `FRONTEND_URL` y volvió al correo de Supabase | «Generar enlace» y revisar los secrets en Fly |
| «Este usuario está inactivo» al pedir enlace | a propósito | reactivarlo primero (darle el enlace deshacería la desactivación sin registro) |
| `USER_ALREADY_INVITED` | se invitó dos veces | ficha del usuario → «Generar enlace» (invitar de nuevo anularía el anterior) |
| `EMAIL_ALREADY_REGISTERED` | el correo tiene cuenta en otra empresa | otro correo, o revisar con el super-admin |
| `AUTH_ACCOUNT_MISSING` | lo borraron desde el panel de Supabase | desactivarlo e invitar de nuevo |
| «No puedes desactivar tu propia cuenta» / último admin | a propósito | que lo haga otro administrador |

Desactivar no cierra la sesión de Supabase: el backend rechaza sus requests en cuanto vence el caché de usuario
(hasta 30 s). Suficiente para un empleado que se va, no para una expulsión urgente.

### 6.3 Diagnóstico

- ¿Llegó a poner contraseña? En `auth.users`: `last_sign_in_at` puesto sin un `updated_at` posterior = abrió el
  enlace y no guardó.
- Reproducir el consumo por GET contra un usuario **de prueba**: `POST {SUPABASE_URL}/auth/v1/admin/generate_link`
  con la service role leída de `.env` (nunca pegada en un comando que quede en un doc); el primer GET al
  `action_link` lo quema, el segundo sale con `otp_expired`. Borrar después los usuarios de prueba (`auth.users` y
  `app_user`).
- Verificar lo servido antes de culpar al código (§4.1).

## 7. Runbook: "no se pueden crear contratos" — casi siempre es la caja

Un cliente pasó once días sin crear un contrato: **nunca había abierto una sesión de caja**, y el desembolso en
efectivo la exige. Antes de buscar un bug en contratos, en este orden:

| # | Comprobación | Síntoma |
|---|---|---|
| 1 | ¿Hay turno de caja abierto hoy? | franja «Caja cerrada»; al guardar, `CASH_SESSION_NOT_OPEN` |
| 2 | ¿El rol tiene `contracts.create`? | no aparece «Nuevo contrato» |
| 3 | ¿Hay categorías de nivel 3 para empeño? | el selector sale vacío |
| 4 | ¿La categoría o algún ancestro define plazo y ventana de mora? | error que nombra la categoría |
| 5 | ¿Con LTV, se registró el avalúo? | `CONTRACT_APPRAISAL_REQUIRED` |
| 6 | ¿La suscripción está vigente? | pantalla de bloqueo (`SUBSCRIPTION_EXPIRED`) |

```sql
begin transaction read only;
select c.name,
  (select count(*) from cash_session s where s.company_id=c.id and s.status='open') as caja_abierta,
  (select count(*) from category ct where ct.company_id=c.id and ct.level=3
     and ct.applies_to in ('pawn','both') and ct.active)                            as categorias_hoja,
  (select count(*) from account a where a.company_id=c.id and a.type='cash' and a.active) as cajones,
  (select sub.expires_at from subscription sub where sub.company_id=c.id)           as vence
from company c order by c.name;
rollback;
```

Un rol con `contracts.create` y sin `cashbox.open_close` depende de que otra persona abra la caja cada día: es
legítimo, pero hay que saberlo.

## 8. Runbook: alta de un cliente nuevo

1. El super-admin crea la empresa en el panel de plataforma (roles semilla, cuentas iniciales, caja principal,
   suscripción) y entrega **en persona o por WhatsApp** el enlace del primer admin.
2. `python scripts/qa/verificar_sedes.py` — sale con 1 si la premisa de una caja por empresa se rompió
   ([`DOMINIO.md`](DOMINIO.md) §12).
3. El admin configura: datos de la empresa (NIT, dirección, teléfono salen en los impresos), logo, plantilla de
   contrato (con la cláusula de autorización de avisos si va a encender recordatorios), categorías con plazo,
   ventana y LTV, cuentas reales, usuarios.
4. **Abrir la caja** el primer día (§7).
5. Si trae contratos de otro sistema, **checklist de corte**:
   1. Crear los **clientes** primero (el import exige `customer_id`).
   2. Congelar contratos nuevos en el sistema viejo (idealmente un fin de semana).
   3. Exportar los contratos **vivos** con las columnas del import ([`API_GUIDE.md`](API_GUIDE.md) §7).
   4. Cargar fila por fila contra `POST /contracts/import` con `Idempotency-Key = legacy_code` (re-ejecutable sin
      duplicar).
   5. **Conciliar**: número de contratos y suma de `capital_balance` por estado contra el reporte del sistema viejo.
      Si no cuadra, no se opera.
   6. Operar en la app; el sistema viejo queda de solo lectura. Los rezagados, por el formulario de contrato
      existente.
6. Encender avisos por empresa solo después de revisar la cláusula y, idealmente, con revisión legal
   ([`DOMINIO.md`](DOMINIO.md) §9).

## 9. El laboratorio de QA

- **`scripts/qa/lab_zzai.py`** crea (idempotente) ocho empresas `ZZ AI — <frente>` en la Supabase dev (Identidad
  A/B, Contratos, Caja, Inventario, Reportes, Documentos, UI): usuarios por rol semilla, un rol a medida «Gestor
  usuarios» con solo `identity.manage_users`, **un rol por cada uno de los 43 permisos** en Identidad A, el árbol
  de categorías con herencia repartida a propósito, proveedores, las cinco cuentas y tres clientes ficticios.
  `--verificar` cuenta lo que hay sin escribir.
- **Una empresa por frente** para que dos pruebas no compartan caja ni stock (una caja abierta es estado global de
  la empresa); la B existe para probar aislamiento.
- **Las credenciales viven fuera del repo** (el repo es público). Nunca se escriben en un doc.
- Las notificaciones de las empresas de laboratorio van **apagadas**: sus correos usan un dominio que no es
  nuestro (hallazgo abierto LAB-01 en [`QA.md`](QA.md)).
- Contratos en cualquier estado se siembran con `POST /contracts/import` (`scripts/qa/seed_contratos.py`).
- El super-admin es la cuenta de Mateo: la usa quien orquesta, no los agentes.
- Qué hace cada script y cómo correrlo: [`../scripts/qa/README.md`](../scripts/qa/README.md).
