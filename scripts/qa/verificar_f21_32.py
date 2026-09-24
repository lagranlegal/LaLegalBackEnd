"""F21-32 en lo DESPLEGADO: reabrir una caja deshace el cierre entero.

    python scripts/qa/verificar_f21_32.py            # empresa ZZ QA (qa.admin)
    python scripts/qa/verificar_f21_32.py --b        # empresa ZZ QA-B (qa.b.admin)

Contra el backend desplegado, con login real del laboratorio de QA.

EL BUG
======
`reopen_session` limpiaba el acta (`expected_cash`/`counted_cash`/`difference`)
pero dejaba vivo el `adjustment` que el cierre había emitido sobre la cuenta
(con `session_id = NULL`, a propósito). Al recerrar, `_expected_cash` no lo ve,
así que el segundo cierre emitía OTRO ajuste encima: cerrar → reabrir →
recerrar acumulaba los dos sobre el saldo mientras el acta solo reportaba el
último (el test de integración: 87.000 donde el acta dice 95.000).

EL INVARIANTE (regla 5 de CLAUDE.md, 00048)
===========================================
Después de cerrar, el saldo de la cuenta `cash` == lo contado. Y después de
reabrir, el saldo vuelve a lo que valía antes del cierre deshecho.

QUÉ HACE
========
1. GET /me y ABORTA si la empresa no empieza con "ZZ". Nunca se escribe sobre
   una empresa real: la base dev tiene datos personales reales (Ley 1581).
2. Anota el estado inicial: ¿sesión abierta?, ¿sesión de hoy?, saldo del cajón.
3. Consigue una sesión abierta: la actual; si no hay, abre una (sin conteo:
   hereda el saldo); si ya se cerró hoy, reabre la de hoy.
4. Tres cierres con conteos distintos (−8.000, +3.000, −5.000 sobre lo
   esperado) con reaperturas en medio. En cada uno: `expected_cash` no se
   corre, la diferencia del acta es la pedida, y el saldo == contado. En cada
   reapertura: el saldo vuelve a la base.
5. Deja el laboratorio con el saldo igual al inicial: si la sesión estaba
   abierta, la deja abierta; si no, la cierra con conteo == esperado
   (diferencia 0, sin ajuste).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import time  # noqa: E402

import httpx  # noqa: E402
import qa  # noqa: E402

# La red hacia Fly suelta `Connection reset by peer` en el handshake TLS de vez
# en cuando. Solo se reintenta ConnectError/ConnectTimeout: fallan ANTES de enviar la
# petición, así que reintentar un POST no puede duplicar un cierre.
_request_original = httpx.request


def _request_con_reintento(*a: object, **kw: object) -> httpx.Response:
    for intento in range(8):
        try:
            return _request_original(*a, **kw)  # type: ignore[arg-type]
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if intento == 7:
                raise
            time.sleep(1.5 * (intento + 1))
    raise AssertionError("inalcanzable")


qa.httpx.request = _request_con_reintento  # type: ignore[assignment]

USUARIOS = {"A": "qa.admin@qalab.com", "B": "qa.b.admin@qalab.com"}
MOTIVO = "QA F21-32 — verificación en vivo (borrable)"

# Desvíos sobre lo esperado, uno por cierre. Distintos entre sí y de signo
# mixto: si la reversa se acumulara o se invirtiera, los números lo delatan.
DESVIOS = [Decimal("-8000.00"), Decimal("3000.00"), Decimal("-5000.00")]


def D(x: object) -> Decimal:
    return Decimal(str(x))


def saldo_cajon(c: qa.Client) -> tuple[str, Decimal]:
    r = c.get("/accounts")
    if not r.ok:
        raise SystemExit(f"GET /accounts falló: {r}")
    cash = [a for a in r.body if a["type"] == "cash" and a["active"]]
    if len(cash) != 1:
        raise SystemExit(f"se esperaba UNA cuenta cash activa y hay {len(cash)}")
    return cash[0]["name"], D(cash[0]["balance"])


def main() -> int:
    empresa_key = "B" if "--b" in sys.argv else "A"
    print(f"\n  Backend: {qa.API}")
    c = qa.client_for(USUARIOS[empresa_key], qa.TEST_PASSWORD, f"admin-{empresa_key}")

    # ------------------------------------------------------ 1. salvaguarda
    me = c.get("/me")
    if not me.ok:
        raise SystemExit(f"GET /me falló: {me}")
    empresa = (me.body.get("company") or {}).get("name") or ""
    print(f"  Empresa: {empresa!r}  (usuario {USUARIOS[empresa_key]})\n")
    if not empresa.startswith("ZZ"):
        print("  ABORTADO: la empresa no es del laboratorio (no empieza con 'ZZ').")
        return 2

    # ----------------------------------------------------- 2. estado inicial
    cajon, saldo_inicial = saldo_cajon(c)
    actual = c.get("/cashbox/sessions/current")
    qa.check(
        "GET /sessions/current: 200 o CASH_SESSION_NOT_OPEN",
        actual.ok or actual.code == "CASH_SESSION_NOT_OPEN",
        f"{actual}",
    )
    estaba_abierta = actual.ok
    hoy = c.get("/cashbox/sessions/today")
    print(f"  Estado inicial: cajón {cajon!r} saldo {saldo_inicial}")
    print(f"    sesión abierta: {'sí ' + actual.body['id'] if estaba_abierta else 'no'}")
    print(
        f"    sesión de hoy: "
        f"{hoy.body['id'] + ' (' + hoy.body['status'] + ')' if hoy.ok else hoy.code}\n"
    )

    # ------------------------------------------- 3. conseguir sesión abierta
    if estaba_abierta:
        sid = actual.body["id"]
        como = "ya estaba abierta"
    else:
        ab = c.post("/cashbox/sessions/open", json={})
        if ab.ok:
            sid, como = ab.body["id"], "abierta por el script (sin conteo: hereda saldo)"
        elif ab.code == "CASH_SESSION_ALREADY_CLOSED_TODAY" and hoy.ok:
            re = c.post(f"/cashbox/sessions/{hoy.body['id']}/reopen", json={"reason": MOTIVO})
            if not qa.check("reabrir la sesión de hoy (ya cerrada)", re.ok, f"{re}"):
                return 1
            sid, como = hoy.body["id"], "sesión de hoy reabierta por el script"
        else:
            print(f"  No se pudo conseguir una sesión abierta: {ab} {ab.body}")
            return 1
    print(f"  Sesión {sid}: {como}")

    # Error por `code`: abrir con una ya abierta.
    dup = c.post("/cashbox/sessions/open", json={})
    qa.check(
        "abrir con una sesión abierta → CASH_SESSION_ALREADY_OPEN",
        dup.code == "CASH_SESSION_ALREADY_OPEN",
        f"{dup}",
    )

    _, base = saldo_cajon(c)
    rep = c.get(f"/cashbox/sessions/{sid}/report")
    if not rep.ok:
        print(f"  GET report falló: {rep}")
        return 1
    esperado = D(rep.body["expected_cash"])
    print(f"  Base: saldo del cajón {base}, esperado del turno {esperado}\n")
    qa.check(
        "punto de partida sano: saldo del cajón == esperado del turno",
        base == esperado,
        f"saldo {base} vs esperado {esperado} (si difiere, hay deriva previa al script)",
    )

    # Error por `code`: descuadre sin justificación.
    sin_motivo = c.post(f"/cashbox/sessions/{sid}/close", json={"counted_cash": str(esperado - 1)})
    qa.check(
        "cerrar con descuadre sin motivo → BAD_REQUEST (y no cierra)",
        sin_motivo.code == "BAD_REQUEST" and sin_motivo.status == 400,
        f"{sin_motivo}",
    )

    # ------------------------------------------------- 4. los ciclos
    tabla: list[tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
    for i, desvio in enumerate(DESVIOS, start=1):
        contado = esperado + desvio
        cierre = c.post(
            f"/cashbox/sessions/{sid}/close",
            json={"counted_cash": str(contado), "difference_reason": f"{MOTIVO} — cierre {i}"},
        )
        if not qa.check(
            f"cierre {i}: 200", cierre.ok, f"{cierre} {cierre.body if not cierre.ok else ''}"
        ):
            return 1
        exp_acta = D(cierre.body["expected_cash"])
        dif_acta = D(cierre.body["difference"])
        _, saldo = saldo_cajon(c)
        tabla.append((i, exp_acta, contado, dif_acta, saldo, saldo - base))
        print(
            f"    cierre {i}: esperado {exp_acta} · contado {contado} · "
            f"diferencia acta {dif_acta} · saldo cajón {saldo} (movió {saldo - base})"
        )
        qa.check(
            f"cierre {i}: expected_cash no se corre entre cierres",
            exp_acta == esperado,
            f"{exp_acta} vs {esperado}",
            severity="alta",
        )
        qa.check(
            f"cierre {i}: diferencia del acta == desvío pedido",
            dif_acta == desvio,
            f"{dif_acta} vs {desvio}",
            severity="alta",
        )
        qa.check(
            f"cierre {i}: INVARIANTE saldo del cajón == contado",
            saldo == contado,
            f"saldo {saldo} vs contado {contado}",
            severity="alta",
        )
        qa.check(
            f"cierre {i}: el saldo movió exactamente la diferencia del acta (no acumulado)",
            saldo - base == dif_acta,
            f"movió {saldo - base}, acta {dif_acta}",
            severity="alta",
        )

        # Error por `code`: cerrar una sesión ya cerrada.
        otra = c.post(
            f"/cashbox/sessions/{sid}/close",
            json={"counted_cash": str(contado), "difference_reason": MOTIVO},
        )
        qa.check(
            f"cierre {i}: recerrar sin reabrir → CASH_SESSION_NOT_OPEN",
            otra.code == "CASH_SESSION_NOT_OPEN",
            f"{otra}",
        )

        # Reabrir siempre: la reversa es justo lo que se verifica. Si la sesión
        # no estaba abierta al empezar, se cierra al final sin descuadre.
        re = c.post(
            f"/cashbox/sessions/{sid}/reopen", json={"reason": f"{MOTIVO} — reapertura {i}"}
        )
        if not qa.check(f"reapertura {i}: 200", re.ok, f"{re}"):
            return 1
        qa.check(
            f"reapertura {i}: el acta queda limpia",
            re.body["difference"] is None and re.body["counted_cash"] is None,
            f"difference={re.body['difference']} counted={re.body['counted_cash']}",
        )
        _, saldo_re = saldo_cajon(c)
        print(f"    reapertura {i}: saldo cajón {saldo_re}")
        qa.check(
            f"reapertura {i}: el saldo vuelve a la base (reversa del ajuste)",
            saldo_re == base,
            f"saldo {saldo_re} vs base {base}",
            severity="alta",
        )
        # Error por `code`: reabrir una sesión abierta.
        re2 = c.post(f"/cashbox/sessions/{sid}/reopen", json={"reason": MOTIVO})
        qa.check(
            f"reapertura {i}: reabrir una abierta → CONFLICT",
            re2.code == "CONFLICT",
            f"{re2}",
        )

    # ------------------------------------------------- 5. dejar el laboratorio
    print()
    if estaba_abierta:
        estado_final = "sesión ABIERTA, como estaba"
    else:
        fin = c.post(f"/cashbox/sessions/{sid}/close", json={"counted_cash": str(esperado)})
        qa.check("cierre final con conteo == esperado (diferencia 0)", fin.ok, f"{fin}")
        if fin.ok:
            qa.check(
                "cierre final: diferencia 0",
                D(fin.body["difference"]) == 0,
                f"{fin.body['difference']}",
            )
        estado_final = "sesión CERRADA con conteo == esperado (sin ajuste)"
    _, saldo_final = saldo_cajon(c)
    qa.check(
        "saldo final del cajón == saldo inicial",
        saldo_final == saldo_inicial,
        f"final {saldo_final} vs inicial {saldo_inicial}",
    )
    print(f"  Estado final: {estado_final}; saldo {saldo_final} (inicial {saldo_inicial})")

    qa.save(
        "f21_32",
        {
            "empresa": empresa,
            "session_id": sid,
            "saldo_inicial": saldo_inicial,
            "base": base,
            "cierres": [
                dict(
                    zip(
                        ("n", "esperado", "contado", "diferencia", "saldo", "movio"), t, strict=True
                    )
                )
                for t in tabla
            ],
            "saldo_final": saldo_final,
            "estado_final": estado_final,
            "hallazgos": qa.FINDINGS,
        },
    )

    print()
    if not qa.FINDINGS:
        print("  OK — F21-32 se comporta en lo desplegado: saldo == contado en cada cierre.\n")
        return 0
    print(f"  {len(qa.FINDINGS)} hallazgo(s):")
    for f in qa.FINDINGS:
        print(f"    · [{f['severity']}] {f['name']} — {f['detail']}")
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
