# PRODUCCION.md — Runbook para montar y operar producción de Prendo

> Escrito el 27/09/2026. **Hoy producción no existe**: todo corre en dev. Este documento es el paso a paso
> para crearla, verificarla y operarla. Está pensado para que Mateo lo siga a mano y para que un agente
> futuro lo ejecute sin reconstruir contexto.
>
> **Cómo leerlo.** Cada paso trae tres cosas: el **comando exacto**, **qué debe verse** y **cómo verificar
> el efecto** (no basta con que el comando no dé error: en este proyecto guardar no es aplicar). Lo que no se
> pudo comprobar al escribirlo está marcado **⚠️ SUPUESTO**. Nada de este documento contiene contraseñas ni
> llaves: donde va un secreto dice `<…>` y de dónde sale.
>
> **Base verificada** (27/09/2026, solo lectura): `Dockerfile`, `fly.dev.toml`, `fly.prod.toml`,
> `scripts/deploy_dev.sh`, `scripts/qa/verificar_job_nocturno.py`, `scripts/qa/verificar_cadenas.py`,
> `app/core/{settings,db,security}.py`, `app/common/cors.py`, `app/jobs/nightly.py`,
> `app/modules/platform/{router,schemas}.py`, `supabase/{config.toml,seed.sql,migrations/}` (todas las migraciones
> de la carpeta), `.github/workflows/guardianes.yml`, `docs/DOMINIO.md` §9, y del front `vercel.json`,
> `package.json`, `vite.config.ts`, `.env.example`, `docs/DEPLOY.md`; `docs/OPERACION.md` §6.
> En vivo: `fly apps list`, `fly machines list`, `fly secrets list` (solo nombres), `fly certs list`, y
> lecturas `GET` de la API de Vercel (dominios, rama de producción, plan del team).

## Contenido

- [0 · Prerrequisitos y decisiones](#0--prerrequisitos-y-decisiones)
- [1 · Supabase prod](#1--supabase-prod)
- [2 · Correo (Resend)](#2--correo-resend)
- [3 · Fly: backend prod](#3--fly-backend-prod)
- [4 · Vercel: front prod](#4--vercel-front-prod)
- [5 · DNS](#5--dns)
- [6 · Primer super-admin y primera empresa](#6--primer-super-admin-y-primera-empresa)
- [7 · Verificación post-deploy (smoke tests)](#7--verificación-post-deploy-smoke-tests)
- [8 · Operación](#8--operación)
- [9 · Migrar el primer cliente real de dev a prod](#9--migrar-el-primer-cliente-real-de-dev-a-prod)
- [10 · Checklist final (una página)](#10--checklist-final-una-página)
- [Apéndice · Supuestos no verificados](#apéndice--supuestos-no-verificados)

## Lo que hay hoy (medido el 27/09/2026)

| Pieza | Dev (existe) | Prod (a crear) |
|---|---|---|
| Base | Supabase `driyubkodnsqxbtxcmaz` («lagranlegal's Dev», AWS us-west-2) | proyecto nuevo, `PROD_REF` |
| Backend | Fly `compraventa-backend-dev` (org `personal`, región `sjc`): Machine API 512 MB + Machine `nightly-job` programada | Fly `prendo-api-prod` |
| Hostname API | `api-dev.prendo.com.co` (cert `Issued`) | `api.prendo.com.co` |
| Front | Vercel `la-legal-front-end` (team `mateos-projects-85710491`, **plan Hobby**), Production Branch **`dev`** | ver §4 |
| Hostname front | `dev.prendo.com.co`; `prendo.com.co` y `www` redirigen **308** a dev | `prendo.com.co` |
| Repos | `lagranlegal/LaLegalBackEnd` y `lagranlegal/LaLegalFrontEnd`; rama por defecto `dev`; `main` está en el commit inicial del 15/08 (184 y 213 commits atrás) | `main` = lo que corre en prod |

Convenciones del documento:

```bash
export PROD_REF=<ref del proyecto Supabase de prod>   # sale de la URL del dashboard, NO de `supabase projects list`
export APP=prendo-api-prod
export REGION=<región de Fly elegida en 0.1>           # p. ej. iad
export DEV_REF=driyubkodnsqxbtxcmaz
```

Los secretos se cargan con `read -s VAR` (no quedan en el historial) y nunca se imprimen.

---

## 0 · Prerrequisitos y decisiones

Nada de esta sección toca plataformas. Son las decisiones que Mateo tiene que tomar **antes** del primer
comando, porque varias no se pueden deshacer (nombre de la app de Fly, región y org del proyecto Supabase).

### 0.1 · Región: la base y la app juntas

La regla del proyecto (lección del 27/08, escrita en `fly.dev.toml` y `fly.prod.toml`): **la app va en la
región de Fly más cercana a la base**, no al usuario. Cada request hace varias consultas SQL; el usuario
hace un solo salto por carga de página. En dev: Supabase us-west-2 (Oregon) ↔ Fly `sjc`.

| Opción | Supabase | Fly | Comentario |
|---|---|---|---|
| **A (recomendada)** | `us-east-1` (N. Virginia) | `iad` (Ashburn) | el tráfico de Colombia sale por Miami; es lo más cerca de Bogotá con buena oferta en ambos proveedores |
| B | `sa-east-1` (São Paulo) | `gru` | lo que dice hoy `fly.prod.toml`; más lejos de Bogotá en la práctica |
| C | `us-west-2` (Oregon) | `sjc` | igual que dev: conocido, pero lo más lejano de Colombia |

⚠️ SUPUESTO: las latencias Colombia↔Virginia vs. Colombia↔São Paulo **no se midieron**. Si se quiere
decidir con datos, medir antes con `curl -w '%{time_connect}'` desde Colombia contra un endpoint de cada
región.

**Ley 1581:** cualquiera de las tres es transferencia internacional de datos personales (igual que hoy con
Oregon); debe constar en la política de tratamiento.

Lo que la región decide en el resto del documento: `primary_region` en `fly.prod.toml` (§3.0), `--region`
de la Machine del job (§3.6) y el host del pooler en `DATABASE_URL` (§3.2).

### 0.2 · Dueño de las cuentas

- **Supabase:** el proyecto de dev vive en la org «lagranlegal's» (nombre del cliente) y el CLI local está
  logueado en **otra** cuenta (`jaras97`). Decidir **en qué org se crea prod** — una de Prendo/Mateo, no la
  del cliente — antes de crearla: mover un proyecto entre orgs no es trivial.
- **Fly:** hoy todo está en la org `personal`. Sirve; si algún día entra otra persona a operar, conviene una
  org de Prendo.
- **GitHub:** los repos están en la org `lagranlegal`. No bloquea prod, pero es el mismo tema de propiedad.
- **Vercel:** el team está en plan **Hobby**. ⚠️ SUPUESTO a confirmar en los términos de Vercel: el plan
  Hobby es para uso no comercial; un SaaS que cobra debería estar en **Pro**. Decidirlo antes de §4.

### 0.3 · Plan de Supabase y respaldo

- **Pro** como mínimo: el Free pausa proyectos inactivos y no tiene backups diarios descargables.
- **PITR** (point-in-time recovery) recomendado desde el día en que entren datos reales: es la única forma
  de deshacer un error de datos al minuto. ⚠️ SUPUESTO: Supabase exige un compute add-on mínimo para
  activar PITR; confirmarlo en el dashboard al contratarlo.

### 0.4 · Costos aproximados (estimación, confirmar en cada dashboard)

| Pieza | Estimación mensual (USD) |
|---|---|
| Supabase Pro | ~25 (incluye créditos de cómputo para la instancia más chica) |
| PITR 7 días + compute que exija | ~100 o más |
| Fly: 1 Machine shared-cpu-1x 512 MB siempre encendida | ~3–5 (x2 si se escala a 2) |
| Fly: Machine del job (corre minutos al día) | centavos |
| Vercel Pro (si aplica, 0.2) | ~20 por miembro |
| Resend | 0 en plan gratis (3.000/mes, compartido con dev) o ~20 en el primer plan pago |
| **Total** | **~50 sin PITR; ~150 con PITR** |

### 0.5 · Las otras decisiones

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| D1 | Región (0.1) | A / B / C | A: `us-east-1` + `iad` |
| D2 | Org de Supabase prod (0.2) | Prendo/Mateo vs. cliente | de Prendo |
| D3 | Plan Supabase + PITR (0.3) | Pro / Pro+PITR | Pro+PITR antes de datos reales |
| D4 | Front de prod en Vercel (§4) | proyecto **separado** vs. mismo proyecto con Production Branch `main` | **separado** |
| D5 | Vercel Hobby → Pro (0.2) | — | Pro si el ToS lo exige |
| D6 | LA GRAN LEGAL (§9) | migrar sus datos de dev a prod, o arrancar limpio en prod | decidir antes de §6.2 |
| D7 | Correo (§2) | Resend gratis compartido con dev, o plan pago / cuenta aparte | cuenta o plan aparte antes de encender avisos al cliente |
| D8 | Buzón `contacto@prendo.com.co` | Google Workspace / Zoho / reenvío | necesario: la landing lo promete y hoy no recibe |
| D9 | Hora del job nocturno (§3.6) | `--schedule daily` (hora que decide Fly) o disparo externo a hora fija | aceptar `daily` al inicio; medir a qué hora corre |
| D10 | Escalado (§3.7) | 1 o 2 Machines de API | 1 al inicio; 2 cuando haya más de un cliente |

### 0.6 · Herramientas en la máquina de quien ejecuta

`flyctl` autenticado (`fly auth whoami`), `supabase` CLI (probado con 2.30.4), `psql`, `jq`, `curl`,
`openssl`, `vercel` CLI autenticado en el team, y el `.venv` del backend (los guardianes usan
`.venv/bin/python`). Un gestor de contraseñas para: password de la base de prod, service role de prod,
`NOTIFICATIONS_LINK_SECRET` de prod y las dos API keys de Resend de prod.

### 0.7 · Preparar el código (en `dev`, por PR; nada de esto despliega)

1. **`backend-starter/fly.prod.toml`** tiene tres errores que hay que corregir **antes** de `fly apps create`:
   - `app = "compraventa-backend-prod"` → **`app = "prendo-api-prod"`**. Fly no renombra apps: si se crea
     con el nombre viejo, queda así para siempre.
   - `primary_region = "gru"` → **la región de D1** (p. ej. `"iad"`).
   - Falta el bloque de memoria (queda en 256 MB; dev ya tuvo que subir a 512 MB). Agregar:
     ```toml
     [[vm]]
       size = "shared-cpu-1x"
       memory = "512mb"
     ```
   - En los comentarios del mismo archivo: el comando del job dice `--app compraventa-backend-prod --region
     gru` y le falta `--name nightly-job` y `--env ENVIRONMENT=production`. Corregirlo con el de §3.6.
2. **`scripts/deploy_prod.sh`** (nuevo), copiado de `deploy_dev.sh` con: `APP="prendo-api-prod"`,
   `CONFIG="fly.prod.toml"`, `API_URL="https://api.prendo.com.co"`; exigir estar en `main`; el paso 2
   cambia `supabase migration list --linked` por `supabase migration list --db-url "$PROD_DB_URL"` (ver
   §1.4: **nunca** `supabase link` a prod); el paso 5 corre los guardianes con `FLY_APP=prendo-api-prod` y
   `QA_DATABASE_URL` de prod. Mientras ese script no exista, el deploy de prod se hace a mano siguiendo
   §8.1 paso por paso.
3. `.github/workflows/guardianes.yml`: el paso de prod ya está escrito y comentado con `FLY_APP:
   prendo-api-prod`. Se descomenta en §3.8.
4. Suites completas en verde (backend con Docker arriba y sin skips; front `npm run test` y `npm run build`).
5. **Merge `dev` → `main`** en los dos repos, por PR. Activar protección de rama en `main` (PR obligatorio
   y CI verde). **No** cambiar la rama por defecto del repo: tiene que seguir siendo `dev`, porque los
   workflows programados de GitHub solo corren desde la rama por defecto (F21-30, explicado en
   `guardianes.yml`).

   Verificación: `git log -1 origin/main` en cada repo = el commit que se probó en dev.

---

## 1 · Supabase prod

### 1.1 · Crear el proyecto

Dashboard de Supabase, **logueado en la cuenta dueña de la org de D2** → New project:

- Nombre: `prendo-prod`. Región: la de D1. Plan: el de D3.
- Password de la base: generada por el gestor de contraseñas, larga, **sin** caracteres raros si se puede
  (va dentro de URLs; si los tiene, hay que codificarla en porcentaje, ver 1.4).
- Anotar `PROD_REF`: es el segmento de la URL del dashboard (`/project/<ref>`) y el subdominio de
  `https://<ref>.supabase.co`. **No** sacarlo de `supabase projects list`: el CLI está logueado en otra cuenta
  y muestra otros proyectos (ver `frontend-starter/docs/DEPLOY.md` §«dos cuentas»).

Qué debe verse: el proyecto en estado *Healthy* en el dashboard.

Verificación:

```bash
curl -s -o /dev/null -w '%{http_code}\n' "https://$PROD_REF.supabase.co/auth/v1/health"
# 401 (pide apikey) o 200: cualquiera de los dos prueba que el proyecto existe y responde. 000 o timeout = ref mal escrito.
```

### 1.2 · Base de datos: SSL, backups, PITR

- Settings → Database → **Enforce SSL on incoming connections**: activado.
- Database → Backups: confirmar que el plan muestra backups diarios. Si D3 incluye PITR, activarlo ahí.
- Network restrictions: dejar abiertas. Restringirlas exigiría IPs de egreso fijas en Fly y no se ha probado.

Verificación: la pantalla de Backups muestra el primer backup al día siguiente. **Anotar en el calendario
mirarlo**: un backup que nunca se vio no está configurado.

### 1.3 · Data API: el esquema `public` NO se expone

**Requisito de configuración.** Settings → Data API (o API → *Exposed schemas*): quitar `public` de la
lista de esquemas expuestos. El backend no usa la Data API (se conecta directo a Postgres) y el front usa
de Supabase solo Auth y Storage (verificado: el único uso de `supabase-js` fuera de Auth es
`supabase.storage.from(...)` en `src/lib/storage/photos.ts`). Storage y Auth no dependen de esta lista.

Qué debe verse: `public` ausente de *Exposed schemas*.

Verificación del efecto (la anon key es pública; sale de Settings → API Keys):

```bash
read -s ANON_PROD   # pegar la anon/publishable key de prod
curl -s -w '\n%{http_code}\n' "https://$PROD_REF.supabase.co/rest/v1/permission?select=code&limit=1" \
  -H "apikey: $ANON_PROD" | tail -c 300
# Esperado: HTTP 404 con código PGRST106 (esquema no expuesto) o PGRST205 (tabla no encontrada).
# Cualquier 200 —aunque sea con una lista vacía— significa que el requisito NO se cumple: volver a la pantalla.
```

(En dev la misma consulta da `404 PGRST205`, medido el 27/09/2026.)

### 1.4 · Llaves de firma JWT asimétricas

El backend solo acepta tokens `RS256` o `ES256` (`app/core/security.py`, `algorithms=["RS256","ES256"]`).
Settings → JWT Keys: la clave de firma **en uso** tiene que ser ECC (P-256) o RSA, no solo el secreto HS256
heredado. ⚠️ SUPUESTO: los proyectos nuevos ya nacen con clave asimétrica; si no, hay que crear una y
rotarla a «en uso» desde esa pantalla.

Verificación:

```bash
curl -s "https://$PROD_REF.supabase.co/auth/v1/.well-known/jwks.json" | jq '[.keys[] | {alg, kid}]'
# Esperado: al menos una clave con alg "ES256" o "RS256". Lista vacía = el backend rechazará TODOS los logins (401).
```

### 1.5 · Aplicar las migraciones — con `--db-url`, nunca con `supabase link`

🔴 **No hacer `supabase link --project-ref <prod>`.** `scripts/deploy_dev.sh` verifica migraciones con
`supabase migration list --linked`, y el link es uno solo por carpeta (`supabase/.temp/project-ref`, hoy
`driyubkodnsqxbtxcmaz`). Linkear prod haría que el próximo deploy de dev mire la base de prod.

Cadena de conexión: dashboard de prod → **Connect** → *Session pooler* (puerto **5432**). Formato
aproximado (copiar el host exacto del dashboard, cambia según región):
`postgresql://postgres.<PROD_REF>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
El CLI exige la URL **codificada en porcentaje** (`supabase db push --help`): si el password tiene `@ : / ? # %`,
codificarlo.

```bash
cd backend-starter
read -s PROD_DB_URL; export PROD_DB_URL     # pegar la URL completa del session pooler
supabase migration list --db-url "$PROD_DB_URL"          # todas en la columna Local, ninguna en Remote
supabase db push --db-url "$PROD_DB_URL" --dry-run       # debe listar desde 00001 hasta la última de supabase/migrations/
supabase db push --db-url "$PROD_DB_URL"
```

Qué debe verse: `Finished supabase db push.` sin errores.

Verificación:

```bash
supabase migration list --db-url "$PROD_DB_URL"   # cada versión con Local y Remote iguales
ls supabase/migrations | wc -l                    # mismo número que filas aplicadas
```

### 1.6 · Aplicar el seed — **obligatorio y aparte**

🔴 `supabase db push` **no aplica `supabase/seed.sql`**. El seed solo corre solo en `supabase db reset`
local (`config.toml` → `[db.seed]`). Y en ese archivo, y **solo** ahí, viven:

- el catálogo base de permisos (contratos, abonos, clientes, catálogos, inventario, ventas, caja…; las
  migraciones solo insertan los permisos agregados después), y
- los **tres planes**: `pawn_only`, `store_only`, `full`.

Sin el seed, `POST /api/v1/platform/companies` no encuentra plan y **no se puede crear ninguna empresa**, y
los roles semilla saldrían sin la mayoría de sus permisos. Es idempotente (todo `on conflict (code) do
nothing`), así que re-ejecutarlo no daña.

```bash
psql "$PROD_DB_URL" -v ON_ERROR_STOP=1 -f supabase/seed.sql
```

Qué debe verse: dos líneas `INSERT 0 <n>` y ningún `ERROR`.

### 1.7 · Verificación del esquema (solo lectura)

Correr la misma consulta en **prod y en dev** y comparar. En dev, siempre dentro de una transacción de solo
lectura explícita (Supavisor ignora `PGOPTIONS`; la solo-lectura la da el `BEGIN`).

```sql
begin transaction read only;
select 'migraciones', count(*)::text from supabase_migrations.schema_migrations
union all select 'permisos', count(*)::text || ' / ' || md5(string_agg(code, ',' order by code)) from public.permission
union all select 'planes', string_agg(code, ',' order by code) from public.plan
union all select 'tipos_evento', count(*)::text || ' / ' || md5(string_agg(code, ',' order by code)) from public.notification_event_type
union all select 'bucket', coalesce((select id || ' public=' || public || ' limit=' || file_size_limit
                                      from storage.buckets where id = 'company-files'), 'FALTA')
union all select 'policy_storage', coalesce((select policyname from pg_policies
                                      where schemaname='storage' and tablename='objects' and policyname='tenant_isolation'), 'FALTA')
union all select 'hook_grant', has_function_privilege('supabase_auth_admin',
                                      'public.custom_access_token_hook(jsonb)', 'execute')::text
union all select 'rol_authenticated', pg_has_role(current_user, 'authenticated', 'member')::text;
rollback;
```

```bash
psql "$PROD_DB_URL" -f verificacion.sql       # guardar el bloque de arriba como verificacion.sql
```

Esperado en prod:

| Fila | Valor |
|---|---|
| `migraciones` | igual al número de archivos en `supabase/migrations/` |
| `permisos` | **mismo conteo y mismo md5 que dev** |
| `planes` | `full,pawn_only,store_only` |
| `tipos_evento` | mismo conteo y md5 que dev |
| `bucket` | `company-files public=false limit=8388608` |
| `policy_storage` | `tenant_isolation` |
| `hook_grant` | `true` |
| `rol_authenticated` | `true` (el backend hace `SET LOCAL ROLE authenticated` en cada request; sin esto, todo endpoint de negocio falla) |

Si `bucket` o `policy_storage` dicen `FALTA`: la migración `00013_storage_buckets.sql` se **salta en
silencio** cuando no encuentra `storage.buckets` (guarda pensada para CI). En un proyecto hospedado no
debería pasar; si pasa, re-ejecutar ese archivo con `psql "$PROD_DB_URL" -v ON_ERROR_STOP=1 -f
supabase/migrations/00013_storage_buckets.sql` (es idempotente) y repetir la verificación.

### 1.8 · Auth: por Management API, **nunca `supabase config push`**

🔴 `supabase config push` empuja el `config.toml` **local** completo: trae `enable_signup = true` (reabre
registros públicos), `site_url = "http://127.0.0.1:3000"` y límites de correo de desarrollo. Nunca se usa,
ni en dev ni en prod.

La vía es un `PATCH` a `https://api.supabase.com/v1/projects/{ref}/config/auth` **con solo los campos
necesarios**, con un Personal Access Token creado en la **cuenta dueña de la org de prod**
(supabase.com/dashboard/account/tokens) y revocado al terminar.

**1.8.1 · Guardar el antes y la referencia de dev**

```bash
read -s SUPABASE_PAT
curl -s "https://api.supabase.com/v1/projects/$PROD_REF/config/auth" \
  -H "Authorization: Bearer $SUPABASE_PAT" > /tmp/prod-auth-antes.json
jq 'keys | length' /tmp/prod-auth-antes.json        # > 0; un {"message":...} = token de otra cuenta
```

Para copiar de dev los valores de producto (largo mínimo de contraseña, expiración de JWT y OTP, límite de
correo, plantillas), hacer el mismo `GET` contra `driyubkodnsqxbtxcmaz` con un PAT de la **cuenta dueña de
dev** (es otra cuenta) a `/tmp/dev-auth.json`. Estos archivos contienen la config de SMTP: borrarlos al final.

**1.8.2 · Confirmar los nombres de campo antes de mandarlos**

```bash
for k in disable_signup external_anonymous_users_enabled site_url uri_allow_list \
         hook_custom_access_token_enabled hook_custom_access_token_uri \
         smtp_host smtp_port smtp_user smtp_pass smtp_admin_email smtp_sender_name rate_limit_email_sent \
         mailer_subjects_invite mailer_templates_invite_content \
         mailer_subjects_recovery mailer_templates_recovery_content; do
  jq -e --arg k "$k" 'has($k)' /tmp/prod-auth-antes.json >/dev/null || echo "NO EXISTE: $k"
done
# Esperado: ninguna línea. Un campo que no existe se ignora en silencio en el PATCH.
```

⚠️ SUPUESTO: esos son los nombres actuales de la Management API; este paso existe justamente para no
depender de eso.

**1.8.3 · El PATCH** (después de §2, que da la API key de SMTP):

```bash
read -s RESEND_SMTP_PROD     # la key "prod-smtp-supabase" de §2.2
jq -n --arg pass "$RESEND_SMTP_PROD" \
      --argjson rate "$(jq '.rate_limit_email_sent' /tmp/dev-auth.json)" '{
  disable_signup: true,
  external_anonymous_users_enabled: false,
  site_url: "https://prendo.com.co",
  uri_allow_list: "https://prendo.com.co/auth/callback",
  hook_custom_access_token_enabled: true,
  hook_custom_access_token_uri: "pg-functions://postgres/public/custom_access_token_hook",
  smtp_host: "smtp.resend.com", smtp_port: "465", smtp_user: "resend", smtp_pass: $pass,
  smtp_admin_email: "no-responder@prendo.com.co", smtp_sender_name: "Prendo",
  rate_limit_email_sent: $rate
}' | curl -s -X PATCH "https://api.supabase.com/v1/projects/$PROD_REF/config/auth" \
      -H "Authorization: Bearer $SUPABASE_PAT" -H "Content-Type: application/json" -d @- \
  | jq '{disable_signup, site_url, hook_custom_access_token_enabled}'
```

Reglas del valor:

- `site_url` = la raíz del front de prod, **igual** a `FRONTEND_URL` del backend (§3.2), sin `/` final. No
  apuntarlo a `/inicio`: las plantillas arman `{{ .SiteURL }}/auth/callback?...`.
- `uri_allow_list` de prod: **sin** localhost, **sin** `*.vercel.app`, **sin** `dev.prendo.com.co`.
- Copiar de `/tmp/dev-auth.json` los demás valores de producto que dev tenga distintos del default
  (p. ej. `password_min_length`, `jwt_exp`, `mailer_otp_exp`), en un segundo PATCH o en el mismo JSON.
  **Nunca** copiar `site_url` ni `uri_allow_list` de dev.

**1.8.4 · Plantillas de correo** (editables porque ya hay SMTP propio). La fuente son los archivos del
repo del front, que usan `{{ .SiteURL }}` y `{{ .TokenHash }}` (nada de URLs de dev en el HTML enviado):

```bash
cd frontend-starter/docs
jq -n --rawfile inv correo-invitacion.html --rawfile rec correo-recuperacion.html \
      --slurpfile dev /tmp/dev-auth.json '{
  mailer_subjects_invite:  $dev[0].mailer_subjects_invite,
  mailer_templates_invite_content: $inv,
  mailer_subjects_recovery: $dev[0].mailer_subjects_recovery,
  mailer_templates_recovery_content: $rec }' \
| curl -s -X PATCH "https://api.supabase.com/v1/projects/$PROD_REF/config/auth" \
    -H "Authorization: Bearer $SUPABASE_PAT" -H "Content-Type: application/json" -d @- >/dev/null
```

Alternativa manual: Authentication → Emails → Templates, pegar cada archivo. ⚠️ Supabase **cachea** las
plantillas unos minutos: un correo enviado justo después puede salir con la vieja. Esperar antes de probar.

**1.8.5 · Verificación del efecto**

```bash
curl -s "https://api.supabase.com/v1/projects/$PROD_REF/config/auth" \
  -H "Authorization: Bearer $SUPABASE_PAT" > /tmp/prod-auth-despues.json
diff <(jq -S 'del(.smtp_pass)' /tmp/prod-auth-antes.json) <(jq -S 'del(.smtp_pass)' /tmp/prod-auth-despues.json)
# Solo deben aparecer los campos que se pidieron. Algo más = revisar antes de seguir.
jq '{disable_signup, site_url, uri_allow_list, hook_custom_access_token_enabled, hook_custom_access_token_uri, smtp_host}' /tmp/prod-auth-despues.json

# El efecto real de "signups cerrados": un registro público tiene que fallar.
curl -s -X POST "https://$PROD_REF.supabase.co/auth/v1/signup" -H "apikey: $ANON_PROD" \
  -H "Content-Type: application/json" -d '{"email":"prueba-signup@prendo.com.co","password":"x-Prueba-12345"}' | jq '.code, .error_code, .msg'
# Esperado: error (422 / signup_disabled). Si devuelve un usuario, signups están ABIERTOS: parar y corregir.
rm -f /tmp/prod-auth-*.json /tmp/dev-auth.json
```

Después: **revocar el PAT** en supabase.com/dashboard/account/tokens. El hook se prueba de verdad en §6.1
(necesita un usuario).

---

## 2 · Correo (Resend)

Prod manda correo por **dos caminos distintos**, y los dos tienen que funcionar:

| Camino | Qué manda | Cómo sale | Remitente |
|---|---|---|---|
| Auth de Supabase | invitación por correo, «¿Olvidaste tu contraseña?» | SMTP de Supabase → Resend (`smtp.resend.com:465`, usuario `resend`) | `no-responder@prendo.com.co` |
| Backend | invitación con enlace propio, comprobantes, recordatorios, resumen diario, alertas | API de Resend con `RESEND_API_KEY`, desde el request **y** desde la Machine del job | `notificaciones@prendo.com.co` (default de `NOTIFICATIONS_FROM_ADDRESS`) |

### 2.1 · Dominio

`prendo.com.co` ya está verificado en Resend (DKIM `resend._domainkey` y el CNAME `send` → `send.forge.rmta.net`,
medidos en DNS el 27/09/2026). **No se tocan esos registros.** Prod usa el mismo dominio.

### 2.2 · Dos API keys nuevas para prod

Resend → API Keys → Create, permiso **Sending access**, restringida al dominio `prendo.com.co`:

- `prod-smtp-supabase` → va en `smtp_pass` del PATCH de §1.8.3.
- `prod-backend` → va en el secret `RESEND_API_KEY` de Fly (§3.2).

No reutilizar las de dev: así se puede revocar una sin tumbar la otra. Guardar las dos en el gestor.

Verificación: la lista de API keys de Resend muestra las dos nuevas; su «Last used» se llena en §7.

### 2.3 · Cuota (D7)

El plan gratis de Resend son 3.000 correos/mes **por cuenta**, y dev y prod comparten cuenta y dominio: el QA
de dev consume la cuota de prod. ⚠️ SUPUESTO: el tope diario del plan gratis (se cree que 100/día) **no está
verificado**; importa porque el resumen diario y los recordatorios salen en la misma corrida del job.
La estimación de diseño de los avisos (NOTIFICACIONES §10, en la historia de git) es de ~155 correos/mes por inquilino del tamaño de LA GRAN LEGAL. Antes de encender
avisos al cliente en prod: confirmar el tope diario y decidir plan pago o cuenta aparte.

### 2.4 · DMARC y buzón de contacto

- **DMARC:** medido el 27/09/2026, `_dmarc.prendo.com.co` **ya existe** con `p=none` y reportes a un
  monitor de Postmark. Lo pendiente no es crearlo sino **endurecerlo** (`p=quarantine`) después de leer
  algunas semanas de reportes y confirmar que solo Resend manda en nombre del dominio.
- **`contacto@prendo.com.co` no existe:** el dominio no tiene registro MX (medido el 27/09/2026) y la landing
  promete ese canal en «Solicitar demostración». Crear el buzón (D8) y su MX en la raíz. No choca con Resend,
  que usa el subdominio `send`.

Verificación del buzón: mandar un correo desde una cuenta externa a `contacto@prendo.com.co` y verlo llegar.

---

## 3 · Fly: backend prod

### 3.0 · Antes de empezar

- `fly.prod.toml` corregido y mergeado en `main` (§0.7 paso 1). Verificar **en el archivo**, no de memoria:

  ```bash
  cd backend-starter && git checkout main && git pull
  grep -E '^(app|primary_region)|memory|ENVIRONMENT' fly.prod.toml
  # app = "prendo-api-prod" · primary_region = "<D1>" · memory = "512mb" · ENVIRONMENT = "production"
  ```

- §1 completo (la base tiene esquema, seed y Auth).

### 3.1 · Crear la app

```bash
fly apps create prendo-api-prod --org personal
```

Qué debe verse: `New app created: prendo-api-prod`. Verificación: `fly apps list` la muestra (sin deploy
todavía). **El nombre no se puede cambiar después.**

### 3.2 · Secrets

Diez secrets. Nombres (idénticos a dev más `PUBLIC_API_URL`) y de dónde sale cada valor:

| Secret | Valor en prod | De dónde sale |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres.<PROD_REF>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:6543/postgres` | Supabase prod → Connect → **Transaction pooler** (puerto **6543**), cambiando el esquema a `postgresql+asyncpg://`. Mismo formato que la `DATABASE_URL` de dev en `backend-starter/.env` (sin parámetros extra). El código usa `NullPool` + `statement_cache_size=0` justamente para este pooler |
| `SUPABASE_URL` | `https://<PROD_REF>.supabase.co` | — |
| `SUPABASE_JWKS_URL` | `https://<PROD_REF>.supabase.co/auth/v1/.well-known/jwks.json` | — |
| `SUPABASE_SERVICE_ROLE_KEY` | la `service_role` (o *secret key*) de prod | Supabase prod → Settings → API Keys. **Solo** aquí; nunca en el front |
| `JWT_AUDIENCE` | `authenticated` | default |
| `FRONTEND_URL` | `https://prendo.com.co` (sin `/` final) | tiene que ser **igual** al Site URL de §1.8.3 |
| `CORS_ALLOW_ORIGINS` | `https://prendo.com.co` | con `ENVIRONMENT=production` **no hay red**: fuera de esta lista el navegador bloquea todo (`app/common/cors.py`). Sin dev, sin `*.vercel.app` |
| `RESEND_API_KEY` | key `prod-backend` | §2.2 |
| `NOTIFICATIONS_LINK_SECRET` | aleatorio largo, **distinto al de dev** | generarlo en el gestor de contraseñas (o `openssl rand -base64 48`) y guardarlo ahí. Cambiarlo después invalida los enlaces de baja ya enviados: se rota solo si se filtra |
| `PUBLIC_API_URL` | `https://api.prendo.com.co` | sin él, la cabecera `List-Unsubscribe` sale con `https://prendo-api-prod.fly.dev` (funciona, pero expone el nombre interno) |

No van como secret: `ENVIRONMENT` (ya en `[env]` del toml), `NOTIFICATIONS_FROM_ADDRESS` (el default sirve),
`SENTRY_DSN` (nada lo usa, ver §8.5), `FLY_APP_NAME` (lo pone Fly).

Carga sin que los valores pasen por el historial de la terminal:

```bash
read -s DB_TX_URL; read -s SRK_PROD; read -s RESEND_BACKEND; read -s LINK_SECRET
fly secrets import --stage -a prendo-api-prod <<EOF
DATABASE_URL=$DB_TX_URL
SUPABASE_URL=https://$PROD_REF.supabase.co
SUPABASE_JWKS_URL=https://$PROD_REF.supabase.co/auth/v1/.well-known/jwks.json
SUPABASE_SERVICE_ROLE_KEY=$SRK_PROD
JWT_AUDIENCE=authenticated
FRONTEND_URL=https://prendo.com.co
CORS_ALLOW_ORIGINS=https://prendo.com.co
RESEND_API_KEY=$RESEND_BACKEND
NOTIFICATIONS_LINK_SECRET=$LINK_SECRET
PUBLIC_API_URL=https://api.prendo.com.co
EOF
fly secrets list -a prendo-api-prod
```

Qué debe verse: los **10 nombres**, estado `Staged` (todavía no hay máquinas). `fly secrets list` nunca
muestra valores; para comprobar uno sin imprimirlo, después del deploy:
`fly ssh console -a prendo-api-prod -C 'sh -c "printenv FRONTEND_URL"'` (este no es secreto).

### 3.3 · Deploy de la API

```bash
cd backend-starter
fly deploy --config fly.prod.toml --app prendo-api-prod
```

Qué debe verse: build de la imagen (`Dockerfile`: Python 3.12, `uvicorn app.main:app` en el puerto 8000),
una Machine creada en la región de D1 y `1 desired, 1 placed, 1 healthy`.

Verificación:

```bash
fly status -a prendo-api-prod               # 1 Machine, grupo app, STATE started, CHECKS 1 total, 1 passing
fly machines list -a prendo-api-prod        # región = D1, tamaño shared-cpu-1x:512MB
curl -fsS https://prendo-api-prod.fly.dev/api/v1/health     # {"status":"ok"}
curl -fsS https://prendo-api-prod.fly.dev/openapi.json | jq -r '"\(.info.title) · \(.paths|length) rutas"'
curl -fsS https://api-dev.prendo.com.co/openapi.json   | jq -r '"\(.info.title) · \(.paths|length) rutas"'
# Mismo título ("Prendo API") y mismo número de rutas si main == dev.
```

**El health check es superficial:** `/api/v1/health` devuelve `{"status":"ok"}` sin tocar la base
(`app/main.py`). Que pase **no** prueba que `DATABASE_URL` sirva. Eso lo prueba §6.1 (el primer login, que
consulta `app_user`) y §7. Si hay que confirmarlo antes, los logs muestran errores de conexión al primer
request autenticado: `fly logs -a prendo-api-prod --no-tail`.

### 3.4 · Dominio `api.prendo.com.co`

```bash
fly ips list -a prendo-api-prod             # anotar la IPv4 (compartida) y la IPv6 (dedicada)
fly ips allocate-v6 -a prendo-api-prod      # SOLO si la lista no trae IPv6
fly certs add api.prendo.com.co -a prendo-api-prod
```

Crear en GoDaddy `A api → <IPv4>` y **`AAAA api → <IPv6>`** (§5). El AAAA no es opcional: con IPv4 compartida,
Fly lo usa para validar el certificado (así quedó `api-dev`). Luego:

```bash
fly certs check api.prendo.com.co -a prendo-api-prod     # repetir hasta "Issued"
```

Puede quedarse varios chequeos en *Awaiting/Issuing* con el DNS bien: esperar, no tocar el DNS.

Verificación: `curl -fsS https://api.prendo.com.co/api/v1/health` → `{"status":"ok"}`, sin error de TLS.

### 3.5 · CORS en vivo

```bash
curl -s -o /dev/null -D - -X OPTIONS https://api.prendo.com.co/api/v1/me \
  -H 'Origin: https://prendo.com.co' -H 'Access-Control-Request-Method: GET' | grep -i '^access-control-allow-origin'
# access-control-allow-origin: https://prendo.com.co
curl -s -o /dev/null -D - -X OPTIONS https://api.prendo.com.co/api/v1/me \
  -H 'Origin: https://dev.prendo.com.co' -H 'Access-Control-Request-Method: GET' | grep -ci '^access-control-allow-origin'
# 0  (dev NO debe ser aceptado por prod)
```

### 3.6 · Machine del job nocturno

**Por qué es un paso aparte.** El job (`python -m app.jobs.nightly`: recalcula estados de contratos, vence
suscripciones, arma resúmenes y recordatorios y despacha correos) corre en una Fly Machine **programada y sin
process group**, a propósito (`fly.dev.toml`, docstring de `scripts/qa/verificar_job_nocturno.py`). La
consecuencia, que ya costó dos incidentes (borrado el 27/08; F21-10, 11 noches con imagen vieja):

- **`fly deploy` no la actualiza.** Queda con la imagen vieja.
- **`fly secrets set` tampoco.** Queda con los secrets viejos.
- Solo `fly machine update <id> --image <imagen>` la pone al día, conservando su `schedule`.
- **Nunca se destruye ni se recrea** una vez creada.

Creación (una sola vez, después de §3.3):

```bash
IMG=$(fly releases -a prendo-api-prod --json | python3 -c 'import json,sys; r=json.load(sys.stdin)[0]; print(r.get("ImageRef") or r.get("imageRef") or "")')
echo "$IMG"          # registry.fly.io/prendo-api-prod:deployment-…   (vacío = parar; no existe ":latest")
fly machine run "$IMG" \
  --app prendo-api-prod --name nightly-job --region "$REGION" \
  --vm-size shared-cpu-1x --schedule daily --restart on-failure \
  --env ENVIRONMENT=production \
  -- python -m app.jobs.nightly
```

Detalles que importan:

- `--name nightly-job`: es el nombre que buscan `deploy_dev.sh` (y el futuro `deploy_prod.sh`) y el guardián.
- `--env ENVIRONMENT=production`: la Machine **no** lee el `[env]` del toml (no es del grupo `app`). En dev
  no lo tiene y toma el default `"dev"` de `Settings`; hoy solo afecta a CORS, pero en prod no debe
  comportarse como dev el día que algo más lea esa variable.
- El `--` es obligatorio: sin él, flyctl toma el `-m` de `python -m` como flag propia.
- Los secrets de la app entran a la Machine al crearla (y en cada `machine update`).

Qué debe verse: una Machine `nightly-job` creada. Verificación y primera corrida manual:

```bash
fly machines list -a prendo-api-prod        # nightly-job: sin PROCESS GROUP, misma IMAGE que la del grupo app
JOB=$(fly machines list -a prendo-api-prod --json | python3 -c 'import json,sys; print([m["id"] for m in json.load(sys.stdin) if m.get("name")=="nightly-job"][0])')
fly machine start "$JOB" -a prendo-api-prod
fly logs -a prendo-api-prod --machine "$JOB" --no-tail | grep -E 'job_nocturno_completado|Traceback|Error'
# Esperado: una línea "job_nocturno_completado: 0 contrato(s) recalculado(s), 0 suscripción(es) vencida(s); …"
FLY_APP=prendo-api-prod .venv/bin/python scripts/qa/verificar_job_nocturno.py     # exit 0: existe, tiene schedule, imagen al día
```

Si el log muestra un error de conexión a la base: la Machine no tiene los secrets (se creó antes de
`fly secrets import`) → `fly machine update "$JOB" --image "$IMG" -a prendo-api-prod --yes`.

**La hora (D9).** `--schedule daily` no fija la hora: la decide Fly. Hay además una hipótesis abierta
(`OPERACION.md` §3) de que cada `machine update` reinicia ese reloj. En prod eso define a qué hora les
llega el resumen a las empresas. Primera semana: anotar la hora de cada corrida
(`fly logs … | grep job_nocturno_completado`). Si hace falta hora fija: un workflow de GitHub con `cron` que
haga `flyctl machine start <JOB> -a prendo-api-prod` (necesita un token que pueda arrancar Machines, no uno de
solo lectura). El job es idempotente (llaves construidas, `DOMINIO.md` §9), así que una corrida extra
no duplica correos.

### 3.7 · Escalado (D10)

`fly.prod.toml` deja la API siempre encendida (`min_machines_running = 1`, `auto_stop_machines = false`) y con
health check cada 15 s. Con **una** Machine, cada deploy tiene un corte de segundos y una falla del host
tumba la API hasta que Fly la reemplace. Para dos:

```bash
fly scale count 2 --process-group app --region "$REGION" -a prendo-api-prod
fly status -a prendo-api-prod     # 2 Machines del grupo app, las dos passing; nightly-job sin tocar
```

Costo: el doble del cómputo de la API. Efectos aceptados de tener dos (verificados en el código): el límite
de tasa del endpoint público de baja es **por Machine** (`app/common/rate_limit.py`) y los cachés de usuario
(30 s) y de permisos de rol (60 s) son **por Machine** (`app/core/security.py`): tras editar un rol o
desactivar un usuario, la otra Machine puede tardar hasta un minuto en verlo.

### 3.8 · Guardián en GitHub Actions

1. En `backend-starter/.github/workflows/guardianes.yml`, descomentar el paso «Verificar la Machine de prod»
   (`FLY_APP: prendo-api-prod`), por PR a `dev` (la rama por defecto; los workflows programados solo corren
   desde ahí).
2. Confirmar que el secret `FLY_API_TOKEN` del repo puede leer **las dos** apps.
3. Correrlo una vez a mano: Actions → Guardianes → **Run workflow**. Un workflow programado que nunca se vio
   correr no está programado.

Verificación: la corrida manual termina en verde con los dos pasos (dev y prod).

`verificar_cadenas.py` (invariantes de datos) **no** va en GitHub a propósito: necesitaría la credencial de
una base con datos personales. Se corre a mano con `QA_DATABASE_URL` apuntando a prod (§8.6).

---

## 4 · Vercel: front prod

### 4.0 · El problema que decide la estrategia (medido el 27/09/2026)

El proyecto `la-legal-front-end` tiene la Production Branch en **`dev`**, y sus **cuatro dominios**
(`dev.prendo.com.co`, `prendo.com.co`, `www.prendo.com.co`, `la-legal-front-end.vercel.app`) tienen
**`gitBranch: null`**: son dominios de *Production*, sirven lo que sea que construya la Production Branch.

Consecuencia: el plan escrito en `frontend-starter/docs/DEPLOY.md` («mover la Production Branch a `main`»)
haría que **`dev.prendo.com.co` pase a servir el build de `main`, con la base de prod**, sin ningún aviso.
La afirmación «dev, intacto — no se mueve» de ese documento hoy **no es cierta**. Además, las variables del
scope *Preview* de ese proyecto son viejas (de hace ~38 días): los builds de `dev` como Preview saldrían con
un backend viejo.

Verificación del estado (solo lectura), para repetirla antes de empezar:

```bash
cd frontend-starter
vercel api /v9/projects/prj_oPo2pjek9Hujoy4KHWQo53v6CQJI/domains --scope mateos-projects-85710491 \
  | jq -r '.domains[] | "\(.name)  gitBranch=\(.gitBranch)  redirect=\(.redirect)"'
vercel api /v9/projects/prj_oPo2pjek9Hujoy4KHWQo53v6CQJI --scope mateos-projects-85710491 | jq -r '.link.productionBranch'
```

### 4.1 · Estrategia recomendada (D4): un proyecto de Vercel **separado** para prod

Se deja `la-legal-front-end` **exactamente como está** (Production Branch `dev`, variables de dev,
`dev.prendo.com.co`, `la-legal-front-end.vercel.app`) y se crea un proyecto nuevo solo para prod, con
Production Branch `main`. Dev no cambia de build en ningún momento y no hay variables de Preview que
mantener. Lo único que se mueve entre proyectos son los dos dominios de prod (`prendo.com.co` y `www`).

Lo que hay que tener en cuenta: `vercel.json` habilita deploys de `main` **y** `dev` y lo leen los dos
proyectos (es el mismo repo). Por eso cada proyecto lleva un *Ignored Build Step* que descarta la rama del
otro (4.1.3).

**4.1.1 · Crear el proyecto** — Dashboard de Vercel, team `mateos-projects-85710491` (con el plan de D5) →
Add New → Project → Import Git Repository → `lagranlegal/LaLegalFrontEnd`.

- Nombre: `prendo-front-prod`. Framework: Vite (autodetectado). Build: `npm run build`. Output: `dist`.
  Root directory: la raíz del repo.
- En la misma pantalla, *Environment Variables*, scope **Production** (valores de prod, no sensibles):

  | Variable | Valor |
  |---|---|
  | `VITE_API_URL` | `https://api.prendo.com.co` |
  | `VITE_SUPABASE_URL` | `https://<PROD_REF>.supabase.co` |
  | `VITE_SUPABASE_ANON_KEY` | anon/publishable key de prod (Supabase prod → API Keys). **Nunca** la service role: todo `VITE_*` queda en el JS público |

- Si el primer build corre antes de tener las variables, **falla a propósito** (`vite.config.ts` aborta si
  faltan `VITE_API_URL` o `VITE_SUPABASE_URL`, porque el CSP se arma con ellas). Es inofensivo.

**4.1.2 · Production Branch** — `prendo-front-prod` → Settings → Git → Production Branch = **`main`**.

**4.1.3 · Ignored Build Step en los dos proyectos** — Settings → Git → Ignored Build Step → *Custom*.
Vercel **cancela** el build si el comando sale con 0 y lo **ejecuta** si sale con 1.

| Proyecto | Comando | Efecto |
|---|---|---|
| `prendo-front-prod` | `[ "$VERCEL_GIT_COMMIT_REF" = "main" ] && exit 1 \|\| exit 0` | solo construye `main` |
| `la-legal-front-end` (dev) | `[ "$VERCEL_GIT_COMMIT_REF" = "dev" ] && exit 1 \|\| exit 0` | solo construye `dev` (hoy también construiría `main` como Preview con variables viejas) |

⚠️ SUPUESTO: la semántica 0 = cancelar / 1 = construir es la documentada por Vercel; verificarla con el primer
push (un push a `dev` no debe crear deployment en `prendo-front-prod`).

**4.1.4 · Variables por CLI sin romper el link de dev.** La carpeta `frontend-starter/.vercel` está linkeada
a `la-legal-front-end`; **no** hacer `vercel link` ahí hacia prod. Para trabajar con el proyecto de prod por
CLI, usar una carpeta aparte:

```bash
mkdir -p ~/prendo-vercel-prod && cd ~/prendo-vercel-prod
vercel link --yes --project prendo-front-prod --scope mateos-projects-85710491
vercel env ls production                  # las tres VITE_*
vercel env pull --environment=production /tmp/.env.prod.check && cut -d= -f1 /tmp/.env.prod.check && rm /tmp/.env.prod.check
```

Para reemplazar una `VITE_*`: `vercel env rm VAR production --yes`, luego
`printf '<valor>' | vercel env add VAR production --no-sensitive` (con *sensitive* en Production el `add` falla
con `invalid_visibility` **después** del `rm`, y la variable queda borrada), `vercel env pull` para confirmar
que están **las tres**, y **redeploy** (§4.3).

**4.1.5 · Primer deploy de prod** — push a `main` (o Deployments → Redeploy). Verificar sobre la **URL del
deployment** (`prendo-front-prod-….vercel.app`), antes de mover dominios:

```bash
U=https://<url-del-deployment-de-main>
curl -s "$U" | grep -o '<meta http-equiv="Content-Security-Policy"[^>]*>'
#   connect-src 'self' https://api.prendo.com.co https://<PROD_REF>.supabase.co
B=$(curl -s "$U" | grep -o '/assets/index-[^"]*\.js' | head -1)
curl -s "$U$B" | grep -c 'api\.prendo\.com\.co'                        # > 0
curl -s "$U$B" | grep -c 'api-dev\.prendo\.com\.co\|driyubkodnsqxbtxcmaz\|compraventa-backend-dev'   # 0
curl -sI "$U" | grep -iE 'strict-transport|x-content-type|referrer-policy'   # headers de vercel.json
```

⚠️ Si el deployment tiene *Deployment Protection* (login de Vercel) el `curl` devuelve la página de Vercel;
en ese caso verificar desde el navegador o con un *bypass token*.

**4.1.6 · Mover `prendo.com.co` y `www` al proyecto de prod** (fuera de horario: entre quitar y agregar, el
apex no sirve nada unos segundos o minutos).

1. `la-legal-front-end` → Settings → Domains → quitar `www.prendo.com.co` y `prendo.com.co`.
2. `prendo-front-prod` → Settings → Domains → Add `prendo.com.co` (sin redirect) y `www.prendo.com.co`
   con **redirect 308 → `prendo.com.co`**.
3. `dev.prendo.com.co` y `la-legal-front-end.vercel.app` **no se tocan**.

⚠️ SUPUESTO: al mover un dominio entre proyectos del mismo team, Vercel no pide volver a verificarlo ni
cambiar el DNS (los registros A del apex y el CNAME de `www` son del team, no del proyecto). Si pide un TXT de
verificación, agregarlo en GoDaddy y esperar.

Verificación del efecto:

```bash
curl -sI https://prendo.com.co     | grep -iE '^HTTP|strict-transport'          # 200 y HSTS
curl -sI https://www.prendo.com.co | grep -iE '^HTTP|^location'                 # 308 → https://prendo.com.co/
B=$(curl -s https://prendo.com.co | grep -o '/assets/index-[^"]*\.js' | head -1)
curl -s "https://prendo.com.co$B" | grep -c 'api\.prendo\.com\.co'              # > 0  (prod)
B=$(curl -s https://dev.prendo.com.co | grep -o '/assets/index-[^"]*\.js' | head -1)
curl -s "https://dev.prendo.com.co$B" | grep -c 'api-dev\.prendo\.com\.co'      # > 0  (dev sigue siendo dev)
```

### 4.2 · Alternativa (no recomendada): mismo proyecto, Production Branch `main`

Solo si D4 decide no crear un segundo proyecto. Orden estricto, sin pushes a `dev` en el medio:

1. Atar `dev.prendo.com.co` a la rama `dev`: Settings → Domains → `dev.prendo.com.co` → Edit → Git Branch =
   `dev` (o `vercel api -X PATCH /v9/projects/<id>/domains/dev.prendo.com.co -d '{"gitBranch":"dev"}'`).
   ⚠️ SUPUESTO: Vercel puede rechazarlo mientras `dev` sea la Production Branch; entonces hacerlo
   inmediatamente después del paso 4. `la-legal-front-end.vercel.app` pasará a servir prod: aceptarlo o
   atarlo también.
2. Reescribir las tres `VITE_*` del scope **Preview, rama `dev`** con los valores de dev
   (`vercel env add VAR preview dev --no-sensitive`).
3. Reescribir las tres `VITE_*` del scope **Production** con los valores de prod. No redesplegar.
4. Settings → Git → Production Branch = `main`. Push a `main`.
5. Redesplegar `dev` y verificar que `dev.prendo.com.co` sirve el bundle con `api-dev.prendo.com.co`.
6. Quitar el redirect del apex y poner `www` → apex 308.

Riesgo que queda: cualquier cambio futuro de dominios o variables en ese proyecto puede volver a cruzar los
ambientes. Por eso se recomienda 4.1.

### 4.3 · Regla permanente: las `VITE_*` se hornean

Las `VITE_*` se leen en `vite build`, no en el navegador. Cambiar una en el dashboard **no cambia nada**
hasta el próximo build, y el síntoma es ninguno: la app sigue hablando con el valor viejo y el dashboard
muestra el nuevo. Después de tocar una: redeploy **y** verificar el bundle servido (los `grep` de 4.1.5), no
el dashboard. Un rollback de Vercel trae las variables del build viejo.

### 4.4 · HSTS y CSP

- HSTS: `vercel.json` ya manda `max-age=63072000; includeSubDomains` en los dos proyectos. **No** agregar
  `preload` hasta que prod lleve tiempo estable (salir de esa lista tarda meses; `DEPLOY.md` §HSTS).
  Consecuencia de `includeSubDomains`: todo subdominio nuevo de `prendo.com.co` tiene que servir HTTPS.
- CSP: nada que tocar; se arma en el build desde `VITE_API_URL` y `VITE_SUPABASE_URL`.

---

## 5 · DNS

GoDaddy (NS `ns45/ns46.domaincontrol.com`). Estado medido el 27/09/2026 y lo que prod agrega:

| Nombre | Tipo | Valor | Prod |
|---|---|---|---|
| `@` | A | `216.198.79.1`, `64.29.17.1` (Vercel) | **no cambia** (el dominio pasa de proyecto dentro de Vercel) |
| `www` | CNAME | `4cf851dda4aeceb9.vercel-dns-017.com.` | **no cambia** (el redirect lo hace Vercel) |
| `dev` | CNAME | el mismo de Vercel | **no se toca** |
| `api-dev` | A / AAAA | `66.241.124.156` / `2a09:8280:1::16e:d34e:0` | **no se toca** |
| `api` | A / AAAA | — | **nuevo**: IPv4 compartida / IPv6 dedicada de `prendo-api-prod` (§3.4). Los dos |
| `resend._domainkey` | TXT | DKIM de Resend | no cambia |
| `send` | CNAME | `send.forge.rmta.net.` | no cambia |
| `_dmarc` | TXT | `v=DMARC1; p=none; …` (existe) | endurecer más adelante (§2.4) |
| `@` | MX | **no existe** | **nuevo** cuando se cree el buzón de `contacto@` (D8) |
| CAA | — | no existe | opcional; si se agrega, permitir la CA de Vercel **y** la de Fly (Let's Encrypt) o se rompe la renovación de certificados |

Verificación después de crear `api`:

```bash
dig +short A api.prendo.com.co        # la IPv4 de fly ips list
dig +short AAAA api.prendo.com.co     # la IPv6 de fly ips list
fly certs check api.prendo.com.co -a prendo-api-prod    # Issued
```

---

## 6 · Primer super-admin y primera empresa

### 6.1 · Super-admin de plataforma

No hay tabla de super-admins: es un usuario de Supabase Auth con **`app_metadata.platform_role =
"super_admin"`** (`app/core/security.py`, `require_super_admin`). No tiene fila en `app_user`, así que el hook
no le agrega `company_id` y **no puede ser a la vez usuario de una empresa**: si Mateo también va a trabajar
dentro de una empresa, necesita otro correo para eso.

Como los signups están cerrados, se crea por la Admin API con la service role de prod, desde una terminal
local (nunca desde el front):

```bash
read -s SRK_PROD
export SA_EMAIL=<correo del super-admin de prod>
curl -s -X POST "https://$PROD_REF.supabase.co/auth/v1/admin/users" \
  -H "apikey: $SRK_PROD" -H "Authorization: Bearer $SRK_PROD" -H "Content-Type: application/json" \
  -d "{\"email\":\"$SA_EMAIL\",\"email_confirm\":true,\"app_metadata\":{\"platform_role\":\"super_admin\"}}" \
  | jq '{id, email, app_metadata}'
# Esperado: un id y app_metadata con "platform_role": "super_admin" (y "provider": "email")
```

Fijar la contraseña con un enlace de recuperación armado igual que lo arma el backend (canje por POST con
`token_hash`, que un crawler no quema):

```bash
HT=$(curl -s -X POST "https://$PROD_REF.supabase.co/auth/v1/admin/generate_link" \
  -H "apikey: $SRK_PROD" -H "Authorization: Bearer $SRK_PROD" -H "Content-Type: application/json" \
  -d "{\"type\":\"recovery\",\"email\":\"$SA_EMAIL\"}" | jq -r '.hashed_token // .properties.hashed_token')
echo "https://prendo.com.co/auth/callback?token_hash=$HT&type=recovery"
# Abrir ESE enlace directamente en el navegador. No pegarlo en WhatsApp/Slack/correo.
```

Verificación del efecto (también prueba `DATABASE_URL`, JWKS y la firma asimétrica):

```bash
read -s ANON_PROD; read -s SA_PASS
TOKEN=$(curl -s -X POST "https://$PROD_REF.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: $ANON_PROD" -H "Content-Type: application/json" \
  -d "{\"email\":\"$SA_EMAIL\",\"password\":\"$SA_PASS\"}" | jq -r .access_token)
echo "$TOKEN" | cut -d. -f2 | python3 -c 'import sys,base64,json; s=sys.stdin.read().strip(); s+="="*(-len(s)%4); d=json.loads(base64.urlsafe_b64decode(s)); print(d.get("app_metadata"), d.get("aud"), "company_id" in d)'
#   {'provider': 'email', ..., 'platform_role': 'super_admin'} authenticated False
echo "$TOKEN" | cut -d. -f1 | python3 -c 'import sys,base64,json; s=sys.stdin.read().strip(); s+="="*(-len(s)%4); print(json.loads(base64.urlsafe_b64decode(s))["alg"])'
#   ES256 o RS256
curl -s https://api.prendo.com.co/api/v1/platform/plans -H "Authorization: Bearer $TOKEN" | jq -r '.[].code'
#   full / pawn_only / store_only  → la API llega a la base y el seed está aplicado
```

Y en el navegador: login en `https://prendo.com.co` → entra y ve `/platform`.

Si el login falla con un error de hook: Authentication → Hooks en el dashboard de prod, y la fila
`hook_grant` de §1.7.

### 6.2 · Primera empresa

⚠️ **Decidir D6 antes.** Si LA GRAN LEGAL se va a migrar con sus datos (§9), **no** crearla a mano aquí: la
migración conserva sus UUID y crear una empresa vacía con el mismo nombre solo estorba. Para probar prod
antes de eso, crear una empresa de humo con nombre inconfundible (p. ej. `ZZ Prendo Smoke`) y suspenderla
al terminar §7 (suspender nunca borra datos).

Desde `/platform` en el navegador, o por API:

```bash
curl -s -X POST https://api.prendo.com.co/api/v1/platform/companies \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{
    "name": "ZZ Prendo Smoke",
    "plan_code": "full",
    "subscription_expires_at": "2026-12-31",
    "first_admin_email": "<correo del admin de la empresa>",
    "first_admin_full_name": "<nombre>",
    "send_email": false
  }' | jq '{id, name, status, plan_code, subscription_expires_at, link: (.admin_invite_link != null)}'
```

Qué debe verse: `201`, `status: "active"`, `plan_code: "full"`, `link: true`. El `admin_invite_link` es una
credencial de un solo uso: se entrega por un canal directo (en persona o por WhatsApp; su canje es por POST,
así que la vista previa de WhatsApp no lo quema — `OPERACION.md` §6).

Verificación del efecto:

1. El admin abre el enlace, crea su contraseña en `/auth/callback` y entra a `/inicio`.
2. De solo lectura en la base de prod:

   ```sql
   begin transaction read only;
   select name from public.role where company_id = '<id>' order by name;         -- Admin, Asesor, Bodega, Moderador
   select status from public.app_user where company_id = '<id>';                 -- active (después del paso 1)
   select type, name from public.account where company_id = '<id>';             -- al menos la caja (cash)
   select count(*) from public.role_permission rp join public.role r on r.id = rp.role_id
    where r.company_id = '<id>' and r.name = 'Admin';                            -- = count(*) de public.permission
   rollback;
   ```

   (Columnas verificadas contra `00003_identity.sql` y `00024_accounts.sql`; el alta la hace
   `create_company_defaults` en `app/modules/platform/service.py`: suscripción, registradora, cuentas por
   defecto y los cuatro roles semilla.)

---

## 7 · Verificación post-deploy (smoke tests)

Con la empresa de humo de §6.2 (o la primera real, si ya se decidió). Cada prueba dice qué mirar; si una
falla, no se abre prod a clientes.

| # | Prueba | Cómo | Esperado |
|---|---|---|---|
| 1 | API viva | `curl -fsS https://api.prendo.com.co/api/v1/health` | `{"status":"ok"}` |
| 2 | API = código de `main` | `curl -fsS https://api.prendo.com.co/openapi.json \| jq -r '.info.title, (.paths\|length)'` | `Prendo API` y el mismo número de rutas que dev si `main` = `dev` |
| 3 | API llega a la base y seed aplicado | `GET /api/v1/platform/plans` con el token del super-admin (§6.1) | `full`, `pawn_only`, `store_only` |
| 4 | CORS | los dos `OPTIONS` de §3.5 | prod acepta `https://prendo.com.co`; rechaza `dev.prendo.com.co` |
| 5 | Front de prod | Chrome (Playwright con `channel: 'chrome'`, o a mano) a `https://prendo.com.co` | landing en `/`; **0 errores de consola ni de CSP** |
| 6 | `www` y HSTS | `curl -sI https://www.prendo.com.co` y `curl -sI https://prendo.com.co` | 308 → apex; `strict-transport-security` presente |
| 7 | Bundle correcto | los `grep` de §4.1.5 contra `https://prendo.com.co` | `api.prendo.com.co` > 0; `api-dev`/`driyubkodnsqxbtxcmaz` = 0 |
| 8 | Login de empresa | el admin de §6.2 entra a `/inicio` | panel carga; en la pestaña Red, `GET /api/v1/me` → 200 |
| 9 | Caja | abrir la caja del día | abre; sin caja abierta no se pueden crear contratos (`OPERACION.md` §7) |
| 10 | Storage | crear un cliente con foto de cédula y volver a abrirla | la foto sube a `company-files/{company_id}/customers/…` y la URL firmada la muestra |
| 11 | Flujo de dinero | contrato → abono → venta → cierre de caja | montos, estado del contrato y acta de cierre correctos |
| 12 | Correo de Auth | «¿Olvidaste tu contraseña?» con el admin de la empresa | llega desde `no-responder@prendo.com.co`; el enlace es `https://prendo.com.co/auth/callback?token_hash=…&type=recovery` y funciona |
| 13 | Correo del backend | invitar un usuario **con** correo desde la empresa | llega desde el remitente de la plataforma; en Resend → Emails figura *Delivered*; el enlace apunta a `prendo.com.co` |
| 14 | Signups cerrados | el `POST /auth/v1/signup` de §1.8.5 | error; nunca un usuario nuevo |
| 15 | Data API cerrada | el `GET /rest/v1/permission` de §1.3 | 404 (`PGRST106`/`PGRST205`) |
| 16 | Job nocturno | `fly machine start <JOB>` y los logs de §3.6 | `job_nocturno_completado`; `verificar_job_nocturno.py` con `FLY_APP=prendo-api-prod` → exit 0 |
| 17 | Invariantes de datos | `QA_DATABASE_URL='<DATABASE_URL de prod>' .venv/bin/python scripts/qa/verificar_cadenas.py` | exit 0 (abre la transacción en solo lectura) |
| 18 | Dev intacto | `dev.prendo.com.co` y `api-dev.prendo.com.co` | siguen en dev: bundle con `api-dev`, login con usuarios de dev |
| 19 | Enlace viejo de dev | un enlace de invitación de dev generado antes | sigue llevando a `dev.prendo.com.co`, nunca a prod |

Al terminar: suspender la empresa de humo desde `/platform` (o `POST
/api/v1/platform/companies/{id}/suspend`) si no va a usarse.

---

## 8 · Operación

### 8.1 · Deploy de rutina

Los dos repos son independientes, y eso da el orden: **backend primero, front después** (el front nuevo puede
leer campos que el backend viejo no tiene; al revés, los campos nuevos son aditivos y el front viejo los
ignora). Mergear el PR del front a `main` **dispara el build de Vercel en ese momento**: no mergearlo antes de
que el backend esté desplegado.

Backend, hasta que exista `scripts/deploy_prod.sh` (§0.7): los mismos cinco pasos de `deploy_dev.sh`, a mano,
desde `main`:

```bash
cd backend-starter && git checkout main && git pull
[ -z "$(git status --porcelain)" ] && [ "$(git rev-parse HEAD)" = "$(git rev-parse @{u})" ] && echo limpio

# 1. Migraciones pendientes (ver 8.2 antes de aplicar)
supabase migration list --db-url "$PROD_DB_URL"
supabase db push --db-url "$PROD_DB_URL" --dry-run
supabase db push --db-url "$PROD_DB_URL"

# 2. API
fly deploy --config fly.prod.toml --app prendo-api-prod

# 3. Job a la MISMA imagen (fly deploy no lo toca)
IMG=$(fly releases -a prendo-api-prod --json | python3 -c 'import json,sys; r=json.load(sys.stdin)[0]; print(r.get("ImageRef") or r.get("imageRef") or "")')
JOB=$(fly machines list -a prendo-api-prod --json | python3 -c 'import json,sys; print([m["id"] for m in json.load(sys.stdin) if m.get("name")=="nightly-job"][0])')
fly machine update "$JOB" --image "$IMG" -a prendo-api-prod --yes

# 4. Guardianes
FLY_APP=prendo-api-prod .venv/bin/python scripts/qa/verificar_job_nocturno.py
QA_DATABASE_URL="$DB_TX_URL" .venv/bin/python scripts/qa/verificar_cadenas.py
curl -fsS https://api.prendo.com.co/openapi.json | jq -r '"\(.info.title) · \(.paths|length) rutas"'
```

⚠️ SUPUESTO: `fly machine update` sin `--skip-start` **arranca** la Machine, o sea que cada deploy corre el job
una vez más (es lo que hace hoy `deploy_dev.sh`). El job es idempotente, así que no duplica nada; lo que no
está medido es si eso mueve la hora de las corridas siguientes (hipótesis abierta en `OPERACION.md` §3).

Front: mergear el PR `dev` → `main` del repo del front. Verificar el bundle servido (§4.1.5 contra
`https://prendo.com.co`), no el dashboard.

**Después de cualquier `fly secrets set`** en prod: el rolling restart actualiza la API, **no** el job. Correr
el paso 3 de arriba con la imagen actual.

### 8.2 · Migraciones: expand → deploy → contract

No hay migraciones *down*. Toda migración de prod sigue este orden:

1. **Expand** (aditiva: tabla nueva, columna nullable, índice): se aplica **antes** del deploy. El código
   viejo sigue funcionando con ella.
2. **Deploy** del código que usa lo nuevo.
3. **Contract** (NOT NULL, DROP, renombres): **en un deploy posterior**, cuando ya ningún código desplegado
   usa lo viejo.

🔴 `supabase db push` aplica **todas** las pendientes juntas. Si la migración de *contract* está en `main`
junto con la de *expand*, el paso 1 aplica las dos antes del deploy y rompe el código que está corriendo.
Regla práctica: **la migración de contract no se mergea a `main` hasta que el deploy del paso 2 esté vivo.**
Siempre mirar el `--dry-run` antes del `push`: lista exactamente qué va a aplicar.

Antes de una migración riesgosa (que reescriba datos): confirmar que el último backup/PITR es reciente
(Database → Backups) y, si la base es chica, guardar una copia propia:
`supabase db dump --db-url "$PROD_DB_URL" --data-only -f prod-antes-<fecha>.sql` (contiene datos personales:
guardarla cifrada y borrarla después).

Si una migración quedó aplicada fuera del CLI (por `psql`), registrarla para que `db push` no la repita:
`supabase migration repair --status applied <versión> --db-url "$PROD_DB_URL"`.

Y **nunca** `supabase link` a prod (§1.5).

### 8.3 · Rollback

| Qué | Cómo | Ojo |
|---|---|---|
| Backend | `fly releases -a prendo-api-prod --image` → tomar la imagen anterior → `fly deploy --config fly.prod.toml -a prendo-api-prod --image <imagen anterior>` **y** `fly machine update <JOB> --image <la misma> -a prendo-api-prod --yes` | solo es seguro si la migración de ese deploy fue aditiva (8.2) |
| Front | Vercel → `prendo-front-prod` → Deployments → el anterior → *Instant Rollback* / *Promote* (o `vercel rollback` desde la carpeta linkeada de §4.1.4) | trae las `VITE_*` horneadas en ese build viejo |
| Base (error de esquema) | migración nueva que corrija hacia adelante | no hay *down* |
| Base (error de datos) | PITR al minuto anterior al error (si D3 lo incluye) | pierde todo lo escrito después, de **todas** las empresas: último recurso |

### 8.4 · Backups y prueba de restauración

- Supabase Pro hace backups diarios; PITR si se contrató. **Storage no entra en esos backups** (son las fotos
  de cédulas, contratos firmados y artículos): hay que copiar el bucket `company-files` aparte, con un script
  que use la service role y lo deje en un almacenamiento cifrado y de acceso restringido (Ley 1581). Ese
  script no existe todavía.
- **Una restauración que nunca se probó no es un backup.** Antes de meter datos reales, y después cada
  trimestre:
  1. Crear un proyecto Supabase temporal (misma org).
  2. Restaurar ahí el último backup (Database → Backups → *Restore to a new project*, ⚠️ SUPUESTO: disponible
     en el plan contratado) o, portable: `supabase db dump --db-url "$PROD_DB_URL" -f esquema.sql` y
     `--data-only -f datos.sql`, y cargarlos con `psql` en el temporal.
  3. Verificar: la consulta de §1.7, conteos por tabla y la consulta de saldos de §9.2 iguales a prod, y
     `verificar_cadenas.py` con `QA_DATABASE_URL` apuntando al temporal → exit 0. (`verificar_saldos.py`
     **no** sirve contra prod: lee por la Data API `/rest/v1/…`, que en prod está cerrada por §1.3, y está
     atado a la configuración de dev del módulo `qa`.)
  4. Anotar la fecha y cuánto tardó. Borrar el proyecto temporal y los archivos de dump.

### 8.5 · Monitoreo — hoy no existe ninguno

- **`SENTRY_DSN` existe en `app/core/settings.py` pero nada lo usa**: no hay SDK de Sentry en `pyproject.toml`
  ni código que lo inicialice. Cargar ese secret **no** activa nada. O se integra Sentry (backend y front), o
  se borra la variable para que no parezca que hay monitoreo.
- **Health check superficial**: `/api/v1/health` no toca la base. Fly reinicia la Machine si el proceso muere,
  pero una base caída o un `DATABASE_URL` roto no lo tumban. No cambiar ese endpoint (reiniciar Machines por
  una caída de Supabase no arregla nada); si se quiere, agregar uno aparte con `select 1` solo para el monitor
  externo.
- **Mínimo antes de clientes reales**: un monitor externo de uptime (UptimeRobot, Better Stack o similar) sobre
  `https://api.prendo.com.co/api/v1/health` y `https://prendo.com.co`, con alerta al celular de Mateo.
- **Logs**: `fly logs -a prendo-api-prod --no-tail` solo trae el buffer reciente. Para investigar algo de hace
  días hace falta un log drain; hoy no hay.
- **El job**: el guardián de GitHub (§3.8) vigila que la Machine exista, tenga `schedule` e imagen al día; **no**
  que haya corrido. Revisar a mano la primera semana (§8.6); una alerta por ausencia del log
  `job_nocturno_completado` en 26 h queda pendiente.

### 8.6 · Job nocturno en operación

- ¿Corrió anoche? `fly logs -a prendo-api-prod --machine <JOB> --no-tail | grep job_nocturno_completado`, o
  en `fly machine status <JOB> -a prendo-api-prod` el último evento de salida con código 0.
- Desde la base, de solo lectura: `select max(occurred_on) from public.notification_event;` avanza cada noche
  cuando hay empresas con contratos vivos (`DOMINIO.md` §9).
- ¿No corrió? `fly machine start <JOB> -a prendo-api-prod` (idempotente) y averiguar por qué: el guardián
  dice si perdió el `schedule` o la imagen.
- **Nunca** `fly machine destroy` de `nightly-job` ni ponerle process group (el porqué completo está en el
  docstring de `scripts/qa/verificar_job_nocturno.py`).

### 8.7 · Rotación de credenciales

| Credencial | Si se rota | Además |
|---|---|---|
| Password de la base | Supabase → Database → Reset password; `fly secrets set DATABASE_URL=…` | `machine update` del job (§8.1 paso 3) |
| Service role | nueva key en Supabase; `fly secrets set SUPABASE_SERVICE_ROLE_KEY=…` | `machine update` del job |
| `RESEND_API_KEY` | nueva en Resend; `fly secrets set` | `machine update` del job; revocar la vieja |
| Key SMTP de Supabase | nueva en Resend; PATCH de `smtp_pass` (§1.8) | revocar la vieja |
| `NOTIFICATIONS_LINK_SECRET` | **solo si se filtró**: invalida los enlaces de baja ya enviados | `machine update` del job |
| PAT de Supabase, tokens de Fly/Vercel personales | crear por tarea y revocar al terminar | el `FLY_API_TOKEN` de GitHub, idealmente de solo lectura |

---

## 9 · Migrar el primer cliente real de dev a prod

**Contexto.** LA GRAN LEGAL (el cliente real) opera hoy en la **base de dev**, mezclada con empresas de prueba
y laboratorios de QA. Sus datos incluyen datos personales de sus clientes (cédulas, fotos de documentos):
**Ley 1581**. Llevarla a prod es un proyecto aparte, con ensayo obligatorio, y solo si D6 lo decide. Si D6
decide arrancar limpio, se crea en prod como cualquier empresa (§6.2) y esta sección aplica solo en su parte
de limpieza de dev (9.8).

Nada de esta sección se hace sin autorización explícita de Mateo y aviso al cliente.

### 9.0 · Qué se copia y qué no

| Tipo | Tablas | Cómo |
|---|---|---|
| La empresa | `company` (por `id`) | tal cual, mismo UUID |
| Datos del tenant | **toda tabla con columna `company_id`** (clientes, contratos y sus ítems y abonos, inventario, productos, ventas, devoluciones, notas crédito, caja, cuentas, registradoras, gastos, capital, roles, usuarios, plantillas, contadores, auditoría, notificaciones, suscripción y sus eventos…) | filas con `company_id = <LGL>`, mismos UUID |
| Tablas hijas sin `company_id` | `role_permission` (se filtra por los `role_id` de la empresa) | con **remapeo** de `permission_id` |
| Catálogos globales | `permission`, `plan`, `notification_event_type` | **no se copian**: prod ya los tiene por el seed y las migraciones, **con otros UUID** en `permission` y `plan` |
| Usuarios | `auth.users` de los `app_user` de la empresa | por Admin API (9.4) |
| Archivos | objetos de Storage bajo `company-files/<company_id>/` | copia de objeto a objeto (9.5) |

Remapeos obligatorios (los UUID de los catálogos globales difieren entre dev y prod):

- `role_permission.permission_id` → exportar el **`code`** del permiso y resolverlo en prod por `code`.
- `subscription.plan_id` → exportar el **`code`** del plan y resolverlo en prod por `code`.
- `notification_event.event_type` y afines usan el `code` como llave: comprobar que el catálogo es idéntico
  (fila `tipos_evento` de §1.7, mismo md5 en las dos bases).

La lista de tablas **no se escribe de memoria**; se saca de la base de dev el día del ensayo:

```sql
begin transaction read only;
select table_name from information_schema.columns
 where table_schema = 'public' and column_name = 'company_id' order by 1;
-- y las que referencian a tablas de tenant sin tener company_id:
select conrelid::regclass as tabla, confrelid::regclass as referencia
  from pg_constraint where contype = 'f' and connamespace = 'public'::regnamespace
   and conrelid::regclass::text not in (select 'public.'||table_name from information_schema.columns
                                        where table_schema='public' and column_name='company_id')
 order by 1;
rollback;
```

### 9.1 · Prerrequisitos

- Prod completa y verificada (§1–§7), con la **prueba de restauración** de §8.4 hecha.
- Mismas migraciones aplicadas en dev y prod (`supabase migration list` contra las dos: mismas versiones).
  Si difieren, el export no encaja en el esquema.
- Un **proyecto Supabase temporal** para el ensayo (misma región que prod), con las migraciones y el seed
  aplicados exactamente como en §1.5–§1.6.
- El `company_id` de LA GRAN LEGAL en dev, leído de solo lectura (`select id, name, status from
  public.company order by name;`) y confirmado con Mateo. **No** confundirla con las empresas de prueba.

### 9.2 · Foto «antes» (en dev, solo lectura, misma transacción que el export)

Estas cifras son la prueba de que la migración no perdió ni cambió nada. Se toman **en la misma transacción**
que el export (9.3), para que sean del mismo instante:

```sql
-- conteo por tabla (generar una línea por cada tabla de 9.0)
select 'contract', count(*) from public.contract where company_id = :'cid'
union all select 'customer', count(*) from public.customer where company_id = :'cid'
-- … una por tabla …
;
-- cartera de empeño
select status, count(*), sum(capital_balance) from public.contract where company_id = :'cid' group by status order by 1;
-- saldo de cada cuenta (derivado de sus movimientos, 00048)
select a.name, a.type,
       coalesce(sum(case m.direction when 'in' then m.amount else -m.amount end), 0) as saldo
  from public.account a left join public.cash_movement m on m.account_id = a.id
 where a.company_id = :'cid' group by a.id, a.name, a.type order by a.name;
-- inventario al costo
select status, count(*), sum(cost) from public.inventory_item where company_id = :'cid' group by status order by 1;
```

La misma consulta se corre después en prod (9.6) y **tiene que dar idéntico, fila por fila**.

### 9.3 · Export consistente (en dev)

Un solo archivo de `psql` con transacción **`repeatable read, read only`** (una foto consistente de todas las
tablas; y solo lectura explícita, porque Supavisor ignora `PGOPTIONS`). Escribir el UUID de la empresa
**literal** donde dice `<CID>`: psql no interpola variables dentro de `\copy`. (`\set cid` queda para las
consultas normales de 9.2, que sí usan `:'cid'`.)

```sql
\set cid '<company_id de LA GRAN LEGAL>'
begin transaction isolation level repeatable read read only;
-- 9.2 (foto antes) va aquí, con \o antes.txt
\copy (select * from public.company where id = '<CID>') to 'company.csv' csv header
\copy (select * from public.customer where company_id = '<CID>') to 'customer.csv' csv header
-- … una línea por tabla de 9.0 …
\copy (select rp.role_id, p.code from public.role_permission rp join public.role r on r.id = rp.role_id join public.permission p on p.id = rp.permission_id where r.company_id = '<CID>') to 'role_permission.csv' csv header
\copy (select s.*, pl.code as plan_code from public.subscription s join public.plan pl on pl.id = s.plan_id where s.company_id = '<CID>') to 'subscription.csv' csv header
\copy (select u.id, u.email, u.raw_user_meta_data from auth.users u join public.app_user au on au.id = u.id where au.company_id = '<CID>') to 'auth_users.csv' csv header
commit;
```

Los CSV contienen datos personales: generarlos en una carpeta cifrada, nunca en el repo ni en `/tmp`
compartido, y borrarlos al terminar (9.8).

### 9.4 · Usuarios de Auth conservando el UUID

`app_user.id` **es** el `id` de `auth.users` (no hay FK, pero el Custom Access Token Hook busca el
`app_user` por ese id, y la auditoría guarda quién hizo qué por ese id). Si el usuario nace en prod con otro
UUID, no le llegan `company_id`/`role_id` en el token y no puede entrar.

Por cada fila de `auth_users.csv`:

```bash
curl -s -X POST "https://$PROD_REF.supabase.co/auth/v1/admin/users" \
  -H "apikey: $SRK_PROD" -H "Authorization: Bearer $SRK_PROD" -H "Content-Type: application/json" \
  -d '{"id":"<uuid de dev>","email":"<email>","email_confirm":true,"user_metadata":<raw_user_meta_data>}' \
  | jq '{id, email}'
# El id devuelto TIENE que ser el mismo que se mandó.
```

⚠️ SUPUESTO **no verificado**: que el `POST /admin/users` de GoTrue acepte `id` y lo respete. Es lo primero
que se prueba en el proyecto temporal; si lo ignora, **parar**: la alternativa (insertar en `auth.users` y
`auth.identities` con SQL) depende de privilegios sobre el esquema `auth` que Supabase restringe, y hay que
estudiarla aparte. Nunca inventar UUIDs nuevos sin remapear `app_user`, auditoría y cada columna que guarde
un usuario.

Contraseñas: **no viajan**. Después del corte, cada usuario fija una nueva con «¿Olvidaste tu contraseña?» o
con el «Generar enlace» del admin (canje por POST). ⚠️ SUPUESTO: GoTrue también acepta un `password_hash`
en ese mismo endpoint, lo que permitiría conservar las contraseñas; no se recomienda (obliga a leer y mover
hashes) salvo que Mateo lo pida.

Si el correo del super-admin de prod coincide con el de un usuario de LA GRAN LEGAL, chocan (un correo = un
usuario de Auth = una sola fila en `app_user`). Resolverlo antes.

### 9.5 · Storage

Copiar cada objeto de `company-files/<company_id>/…` de dev a prod **con la misma ruta** (las filas de la base
guardan la ruta, y el primer segmento es el `company_id`, que se conserva). Por la API de Storage con la
service role de cada proyecto: listar por prefijo (`POST /storage/v1/object/list/company-files`), descargar
(`GET /storage/v1/object/company-files/<ruta>`) y subir (`POST /storage/v1/object/company-files/<ruta>`) con
el mismo `Content-Type`. El script no existe todavía; se escribe y se prueba en el ensayo.

Verificación: mismo número de objetos y misma suma de tamaños bajo el prefijo en las dos bases
(`select count(*), sum((metadata->>'size')::bigint) from storage.objects where bucket_id = 'company-files'
and name like '<company_id>/%';`), y abrir en la app de prod dos o tres fotos de cédula.

### 9.6 · Import (en el temporal para el ensayo; en prod el día del corte)

- Una sola transacción, conectado como `postgres` (no aplica RLS).
- Orden de carga: padres antes que hijos (`company` → `subscription` → `role` → `role_permission` →
  `app_user` → catálogos del tenant → clientes → contratos → … → auditoría y notificaciones). El orden exacto
  sale del ensayo.
- Los remapeos de 9.0: cargar `role_permission.csv` y `subscription.csv` a tablas temporales y resolver
  `code` → `id` de prod al insertar.
- Si hay dependencias circulares que impidan cualquier orden, la salida es `set local session_replication_role
  = replica` (desactiva triggers y chequeos de FK para esa transacción). ⚠️ SUPUESTO: que el rol `postgres`
  de Supabase pueda fijarlo. Si se usa, **documentar por qué** y comprobar después que no quedaron huérfanos.
- Al final de la misma transacción, antes del `commit`: correr la consulta de 9.2 y compararla con
  `antes.txt`. Si difiere en una sola cifra: `rollback`.

Verificación después del `commit`:

```bash
diff antes.txt despues.txt                                   # vacío
QA_DATABASE_URL='<DATABASE_URL de prod (o del temporal)>' .venv/bin/python scripts/qa/verificar_cadenas.py   # exit 0
```

Y en la app: login de un usuario de LA GRAN LEGAL (después de fijar contraseña), ver sus contratos con los
mismos estados y saldos, sus fotos, su caja con el mismo saldo, y su historial de auditoría.

### 9.7 · El día del corte

1. **Ensayo completo** en el proyecto temporal, de principio a fin, con un export fresco, y tomar el tiempo.
   Hasta que el ensayo no dé `diff` vacío, no hay corte.
2. Avisar a LA GRAN LEGAL con anticipación: ventana fuera de su horario (sugerido: noche o domingo), qué
   cambia (la dirección pasa de `dev.prendo.com.co` a `prendo.com.co`; cada usuario crea contraseña nueva) y
   pendientes que viajan con ella (por ejemplo, el descuadre de su cajón que ya conoce).
3. Inicio de la ventana: **suspender la empresa en dev** (`/platform` → suspender). Bloquea login y API para
   sus usuarios, así que nadie escribe después de la foto.
4. Export (9.3) con la foto «antes» en la misma transacción.
5. Usuarios (9.4), Storage (9.5), import (9.6) en prod.
6. Verificación 9.6 completa. Si falla y no se arregla dentro de la ventana: **reactivar la empresa en dev**
   (vuelven a trabajar donde estaban, sin pérdida) y borrar lo importado en prod (`rollback` si no se hizo
   `commit`; si ya se hizo, suspender la empresa en prod y limpiar con calma).
7. Si todo cuadra: entregar a cada usuario su enlace de contraseña por un canal directo y acompañar el primer
   login del admin.

La empresa **no se reactiva en dev** después de un corte exitoso: dos bases con la misma empresa viva son dos
verdades.

### 9.8 · Después del corte (Ley 1581)

- Dev deja de tener finalidad para los datos personales de LA GRAN LEGAL: con la empresa suspendida,
  **anonimizar o borrar** sus datos personales en dev (clientes, fotos del bucket bajo su `company_id`) en
  cuanto prod lleve unas semanas estable. Decisión de Mateo; dejarla registrada.
- Borrar los CSV del export, `antes.txt`/`despues.txt` y el proyecto temporal del ensayo.
- Actualizar la política de tratamiento si cambió la región de los datos (D1).

---

## 10 · Checklist final (una página)

Marcar cada casilla **solo** cuando su verificación dio lo esperado, no cuando el comando terminó.

**Decisiones (§0)**
- [ ] D1 región · D2 org Supabase · D3 plan/PITR · D4 Vercel separado · D5 plan Vercel · D6 LA GRAN LEGAL · D7 correo · D8 buzón · D9 hora del job · D10 escalado
- [ ] `fly.prod.toml`: `prendo-api-prod`, región D1, `[[vm]] 512mb` — mergeado en `main`
- [ ] `dev` → `main` mergeado en los dos repos; `main` protegida; rama por defecto sigue siendo `dev`

**Supabase (§1)**
- [ ] Proyecto creado; `PROD_REF` anotado desde la URL del dashboard
- [ ] Enforce SSL; backups diarios visibles; PITR si D3
- [ ] `public` fuera de *Exposed schemas* → `GET /rest/v1/permission` = 404
- [ ] JWKS con clave `ES256`/`RS256`
- [ ] `db push --db-url` (nunca `link`): todas las migraciones Local = Remote
- [ ] **`psql -f supabase/seed.sql`** aplicado
- [ ] §1.7: permisos y tipos de evento con el mismo md5 que dev; 3 planes; bucket y policy; `hook_grant` y `rol_authenticated` en `true`
- [ ] Auth por PATCH (nunca `config push`): signups cerrados (el signup de prueba falla), Site URL y Redirect URL de prod, hook habilitado, SMTP Resend, plantillas; PAT revocado

**Correo (§2)**
- [ ] Dos API keys de prod en Resend (SMTP y backend)
- [ ] Tope diario de Resend confirmado y D7 decidido antes de encender avisos al cliente
- [ ] Buzón `contacto@` + MX creado y probado

**Fly (§3)**
- [ ] `prendo-api-prod` creada; 10 secrets (con `PUBLIC_API_URL` y `NOTIFICATIONS_LINK_SECRET` propio)
- [ ] Deploy: 1 Machine `app` en región D1, 512 MB, check passing; `openapi.json` = dev
- [ ] `api.prendo.com.co`: A + AAAA; certificado `Issued`; health por HTTPS
- [ ] CORS: acepta `prendo.com.co`, rechaza `dev.prendo.com.co`
- [ ] `nightly-job` creada con `--name`, `--schedule daily`, `--env ENVIRONMENT=production`; primera corrida con `job_nocturno_completado`; `verificar_job_nocturno.py` exit 0
- [ ] Paso de prod descomentado en `guardianes.yml` y corrido a mano en verde

**Vercel (§4)**
- [ ] `prendo-front-prod` con Production Branch `main` y las 3 `VITE_*` de prod
- [ ] Ignored Build Step en los dos proyectos
- [ ] Bundle del deployment de `main` con `api.prendo.com.co` y sin rastros de dev
- [ ] `prendo.com.co` sirve prod; `www` → 308 apex; **`dev.prendo.com.co` sigue sirviendo dev**

**Puesta en marcha (§6–§7)**
- [ ] Super-admin creado; token con `platform_role = super_admin`; `/platform/plans` devuelve 3 planes
- [ ] Primera empresa (o la de humo) con 4 roles, cuenta de caja y admin `active`
- [ ] Las 19 pruebas de §7 en verde

**Operación (§8)**
- [ ] Monitor externo de uptime con alerta
- [ ] Prueba de restauración hecha y fechada
- [ ] Decidido qué hacer con `SENTRY_DSN` (integrar o quitar)
- [ ] Hora real del job anotada la primera semana
- [ ] (Si D6) migración de LA GRAN LEGAL ensayada con `diff` vacío antes del corte (§9)

---

## Apéndice · Supuestos no verificados

Lo que este documento afirma sin haberlo podido comprobar el 27/09/2026. Cada uno dice dónde se confirma.

| # | Supuesto | Dónde se confirma |
|---|---|---|
| S1 | Latencias Colombia ↔ us-east-1 vs. sa-east-1 (la recomendación de región) | medir antes de D1 (§0.1) |
| S2 | El plan Hobby de Vercel no permite uso comercial | términos de Vercel (§0.2) |
| S3 | PITR exige un compute add-on mínimo; costos de la tabla §0.4 | dashboard de Supabase al contratar |
| S4 | Los proyectos Supabase nuevos nacen con clave JWT asimétrica | §1.4, con el `curl` al JWKS |
| S5 | Nombres de campo de la Management API de Auth | §1.8.2 los comprueba contra el `GET` antes del `PATCH` |
| S6 | Tope diario del plan gratis de Resend (~100/día) | panel de Resend / soporte (§2.3) |
| S7 | Semántica del Ignored Build Step (0 cancela, 1 construye) | primer push tras configurarlo (§4.1.3) |
| S8 | Mover un dominio entre proyectos del mismo team no pide re-verificación ni cambio de DNS | §4.1.6, en el momento |
| S9 | En el camino alternativo, Vercel acepta `gitBranch: dev` mientras `dev` es Production Branch | §4.2, solo si se elige esa vía |
| S10 | `fly machine update` sin `--skip-start` arranca el job, y si eso mueve la hora del `schedule daily` | logs de la primera semana (§3.6, §8.1) |
| S11 | *Restore to a new project* disponible en el plan contratado | §8.4 |
| S12 | GoTrue acepta `id` en `POST /admin/users` y lo respeta | **primer paso del ensayo de §9.4; si falla, se para la migración** |
| S13 | GoTrue acepta `password_hash` en el mismo endpoint | §9.4, solo si se quisiera conservar contraseñas |
| S14 | El rol `postgres` de Supabase puede fijar `session_replication_role` | §9.6, en el ensayo, solo si hace falta |

Hechos medidos que contradicen documentos existentes (para corregirlos en su lugar):

- `frontend-starter/docs/DEPLOY.md`: «`dev.prendo.com.co` — dev, intacto — no se mueve» es falso mientras sus
  dominios tengan `gitBranch: null` (§4.0); y su paso 3 dice `fly apps create compraventa-backend-prod`.
- `fly.prod.toml`: nombre, región y memoria (§0.7).
- Docstring de `scripts/qa/verificar_job_nocturno.py`: el ejemplo usa `FLY_APP=compraventa-backend-prod`.
- DMARC: los pendientes dicen que falta; medido el 27/09/2026, `_dmarc.prendo.com.co` ya existe con `p=none`.
