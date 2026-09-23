#!/usr/bin/env bash
# Verifica que un enlace de activación o recuperación SOBREVIVA a los crawlers
# de vista previa antes de que lo abra la persona.
#
# POR QUÉ EXISTE
# --------------
# El 03/09/2026 costó días: el `action_link` de GoTrue es un **GET de un solo
# uso** —basta con PEDIR la URL para quemarla— y las vistas previas de WhatsApp,
# Telegram, Slack y los escáneres de correo la piden antes que el destinatario.
# El admin pegaba el enlace en un chat, el crawler lo quemaba al instante para
# armar la tarjetita, y la persona llegaba SIN SESIÓN: veía el formulario igual
# y al guardar recibía un error genérico que la mandaba a reintentar algo
# imposible.
#
# La salida fue dejar de apuntar a GoTrue y apuntar a la app
# (`/auth/callback?token_hash=…&type=…`), que se canjea con `verifyOtp` — un
# **POST**. Un crawler que haga GET solo se baja el cascarón de la SPA.
#
# Este script comprueba esa propiedad. Es el paso 7.1 del runbook de la Fase 5a
# (`frontend-starter/docs/PLAN_MARCA.md`).
#
# USO
#   scripts/qa/verificar_enlace_correo.sh '<el enlace COMPLETO, entre comillas>'
#
#   Sin argumento, prueba la RUTA con un token falso: eso verifica que el
#   dominio y el enrutamiento estén bien, pero NO prueba el canje real.
#
# QUÉ TIENE QUE PASAR
#   Los cuatro crawlers → 200, sin redirect, y el cuerpo con el cascarón de la
#   SPA. Y RECIÉN DESPUÉS abrir el mismo enlace en un navegador real: si deja
#   guardar la contraseña, sobrevivió. **El 200 no es la prueba; el guardado sí.**
#
# CÓMO SE LEE UNA FALLA
#   302 con `#access_token=…`   el token se quemó ahí mismo → la plantilla está
#                               usando `{{ .ConfirmationURL }}`, o quedó la
#                               plantilla por defecto de Supabase.
#   302 con `#error_code=otp_expired`  ya estaba quemado antes de la prueba.
#   Un dominio que no es el nuestro   es el click tracking de Resend
#                               reescribiendo el enlace: hay que apagarlo.
set -uo pipefail

DOMINIO="${PRENDO_APP_URL:-https://dev.prendo.com.co}"
LINK="${1:-$DOMINIO/auth/callback?token_hash=TOKEN_FALSO_DE_PRUEBA&type=recovery}"

if [ $# -eq 0 ]; then
  echo
  echo "  ⚠ Sin enlace real: probando solo la RUTA con un token falso."
  echo "    Esto verifica dominio y enrutamiento, NO el canje. Para la prueba"
  echo "    de verdad, pasá el enlace del correo entre comillas."
fi

echo
echo "  Enlace: ${LINK%%\?*}?…"
# Antes de gastar el token: ¿la plantilla está usando la forma correcta?
# `/auth/v1/verify` es el enlace de GoTrue, o sea `{{ .ConfirmationURL }}` —
# el que los crawlers queman. El nuestro apunta a la app con `token_hash`.
case "$LINK" in
  */auth/v1/verify\?*)
    echo
    echo "  🔴 EL ENLACE ES EL DE GoTrue, NO EL DE LA APP."
    echo "     Empieza con /auth/v1/verify, o sea que la plantilla está usando"
    echo "     {{ .ConfirmationURL }} — el enlace que los crawlers queman."
    echo "     El nuestro se ve así:"
    echo "       <dominio>/auth/callback?token_hash=…&type=recovery"
    echo
    echo "     Causa casi segura: la plantilla no se guardó, se editó la"
    echo "     equivocada (Reset Password ≠ Magic Link), o el plan del proyecto"
    echo "     no permite editarlas (medido el 04/09/2026 — paso 1 del runbook)."
    echo
    echo "     Se sigue igual para dejar la evidencia, pero el diagnóstico ya está."
    ;;
esac

echo "  ── Los cuatro crawlers que queman enlaces ──"

FALLAS=0
while IFS='|' read -r NOMBRE UA; do
  RES=$(curl -s -o /tmp/_vec_body -w '%{http_code}|%{redirect_url}' --max-time 30 -A "$UA" "$LINK")
  CODIGO="${RES%%|*}"; REDIR="${RES#*|}"
  if [ "$CODIGO" = "200" ] && [ -z "$REDIR" ]; then
    printf '  [OK  ] %-24s 200, sin redirect\n' "$NOMBRE"
  else
    # El destino NO se imprime entero a propósito: cuando el enlace se quema,
    # el redirect trae un `access_token` REAL en el fragmento, y pegar esa
    # salida en un chat o un ticket lo filtra. Se dice QUÉ pasó, no el token.
    case "$REDIR" in
      *access_token=*)  QUE="SE QUEMÓ: el destino trae un access_token (sesión real)" ;;
      *otp_expired*)    QUE="ya estaba quemado (otp_expired) — lo consumió un crawler anterior" ;;
      *error_code=*)    QUE="el destino trae un error_code" ;;
      "")               QUE="sin redirect, pero el código no es 200" ;;
      *)                QUE="redirige a ${REDIR%%\?*}" ;;
    esac
    printf '  [ROTA] %-24s %s  %s\n' "$NOMBRE" "$CODIGO" "$QUE"
    FALLAS=$((FALLAS+1))
  fi
done <<'CRAWLERS'
WhatsApp|WhatsApp/2.23
Telegram|TelegramBot (like TwitterBot)
Facebook|facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)
Slack|Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)
CRAWLERS

echo "  ── El cuerpo ──"
CUERPO=$(curl -s --max-time 30 -A "WhatsApp/2.23" "$LINK")
if printf '%s' "$CUERPO" | grep -q 'id="root"'; then
  echo "  [OK  ] es el cascarón de la SPA"
else
  echo "  [ROTA] NO es el cascarón de la SPA — el crawler se bajó otra cosa"
  FALLAS=$((FALLAS+1))
fi
if printf '%s' "$CUERPO" | grep -qi 'access_token\|refresh_token'; then
  echo "  [ROTA] hay un token en la respuesta: el enlace se está canjeando por GET"
  FALLAS=$((FALLAS+1))
else
  echo "  [OK  ] no hay ningún token en la respuesta"
fi

echo
if [ "$FALLAS" -gt 0 ]; then
  echo "  ROTO — $FALLAS comprobación(es). Ver el encabezado de este archivo."
  exit 1
fi
echo "  OK — el enlace sobrevivió a los cuatro crawlers."
if [ $# -gt 0 ]; then
  echo
  echo "  ⚠ FALTA LA MITAD DE LA PRUEBA: abrí AHORA ese mismo enlace en un"
  echo "    navegador real y guardá la contraseña. Si guarda, sobrevivió de"
  echo "    verdad. El 200 no es la prueba; el guardado sí."
fi
