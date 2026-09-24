#!/usr/bin/env bash
# Despliega el backend de DEV completo, en un solo comando que no se puede hacer a medias.
#
#     ./scripts/deploy_dev.sh
#
# POR QUÉ EXISTE
# `fly deploy` actualiza SOLO la máquina de la API. La Machine `nightly-job` no tiene
# process group, así que `fly deploy` y `fly secrets set` la saltean y queda corriendo la
# imagen vieja — la causa de F21-10 (11 noches recalculando contratos con código viejo).
# No se le pone process group a propósito (ver el docstring de
# scripts/qa/verificar_job_nocturno.py): el arreglo es actualizarla en cada deploy, y
# este script hace que eso no dependa de que alguien se acuerde.
#
# QUÉ HACE, EN ORDEN (cualquier falla lo detiene)
#   1. Frena si hay cambios sin commitear o sin pushear: se desplegaría código que no está
#      en git, y el deploy de hoy no se podría reproducir mañana.
#   2. Frena si hay migraciones sin aplicar en la base remota: el código nuevo no puede
#      llegar antes que su esquema. Se aplican con `supabase db push` y se vuelve a correr.
#   3. `fly deploy` de la API.
#   4. Actualiza la Machine del job a la MISMA imagen (y con eso, a los secrets actuales),
#      conservando su `schedule`.
#   5. Corre los dos guardianes; si alguno falla, sale con error.
#
# NUNCA destruye ni recrea la Machine del job: borrarla causó el incidente del 27/08.

set -euo pipefail

APP="compraventa-backend-dev"
CONFIG="fly.dev.toml"
JOB_NAME="nightly-job"
API_URL="https://api-dev.prendo.com.co"

cd "$(dirname "$0")/.."
PY=".venv/bin/python"

paso() { printf '\n\033[1m▶ %s\033[0m\n' "$1"; }
falla() { printf '\n\033[31m✖ %s\033[0m\n' "$1" >&2; exit 1; }
ok() { printf '\033[32m✔ %s\033[0m\n' "$1"; }

paso "1/5 · El código está commiteado y pusheado"
flyctl auth whoami >/dev/null 2>&1 || falla "flyctl no está autenticado: corre 'fly auth login'."
[ -z "$(git status --porcelain)" ] || falla "Hay cambios sin commitear. Commitea o descártalos antes de desplegar."
git fetch -q origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}')" ] \
  || falla "La rama no coincide con origin (falta push o pull). Se desplegaría algo que no está en git."
ok "limpio y al día con $(git rev-parse --abbrev-ref '@{u}') ($(git rev-parse --short HEAD))"

paso "2/5 · Migraciones aplicadas en la base remota"
pendientes=$(supabase migration list --linked 2>/dev/null \
  | awk -F'|' '$1 ~ /[0-9]/ && $2 ~ /^ *$/ {gsub(/ /, "", $1); print $1}')
[ -z "$pendientes" ] || falla "Migraciones sin aplicar en la remota: $pendientes. Corre 'supabase db push --linked' y repite."
ok "ninguna pendiente"

paso "3/5 · Deploy de la API"
flyctl deploy --config "$CONFIG" --app "$APP"

paso "4/5 · Machine del job nocturno a la misma imagen"
imagen=$(flyctl releases --app "$APP" --json | "$PY" -c '
import json, sys
r = json.load(sys.stdin)[0]
print(r.get("ImageRef") or r.get("imageRef") or "")')
[ -n "$imagen" ] || falla "No se pudo leer la imagen del release que se acaba de desplegar."
job_id=$(flyctl machine list --app "$APP" --json | "$PY" -c "
import json, sys
ids = [m['id'] for m in json.load(sys.stdin) if m.get('name') == '$JOB_NAME']
print(ids[0] if len(ids) == 1 else '')")
[ -n "$job_id" ] || falla "No encontré UNA Machine '$JOB_NAME'. No se crea sola: revisa con 'flyctl machine list --app $APP'."
echo "  $job_id → $imagen"
flyctl machine update "$job_id" --image "$imagen" --app "$APP" --yes

paso "5/5 · Guardianes"
"$PY" scripts/qa/verificar_job_nocturno.py || falla "El guardián del job nocturno falló (arriba dice qué y cómo arreglarlo)."
"$PY" scripts/qa/verificar_cadenas.py || falla "El guardián de cadenas de contratos falló."
titulo=$(curl -fsS "$API_URL/openapi.json" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(d["info"]["title"], "·", len(d["paths"]), "rutas")') \
  || falla "La API servida no responde en $API_URL."
ok "API servida: $titulo"

printf '\n\033[32;1m✔ Deploy de dev completo: API, job nocturno y guardianes en verde.\033[0m\n'
