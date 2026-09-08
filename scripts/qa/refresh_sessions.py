"""Renueva el token de cada actor del laboratorio.

Los access_token de Supabase Auth duran una hora, así que en una sesión de
trabajo larga hay que rehacer el login. Guarda en `_run/sessions.json` el
token, los permisos efectivos y el id de cada uno, que es lo que consumen
todos los demás scripts.

    python scripts/qa/refresh_sessions.py
"""

import json

import qa

# Los actores del laboratorio (ver docs/QA_AUDITORIA.md §"El laboratorio").
# El número de permisos es el de la matriz de roles semilla: si no cuadra,
# alguien tocó los roles de la empresa espejo y la matriz va a dar falsos.
ACTORS = {
    "Admin": ("qa.admin@qalab.com", 36),
    "Moderador": ("qa.moderador@qalab.com", 19),
    "Asesor": ("qa.asesor@qalab.com", 11),
    "Bodega": ("qa.bodega@qalab.com", 5),
    "Gestor": ("qa.gestor@qalab.com", 1),
    "AdminB": ("qa.b.admin@qalab.com", 36),
}


def main() -> None:
    sessions: dict[str, dict] = {}
    for role, (email, esperados) in ACTORS.items():
        try:
            token = qa.login(email, qa.TEST_PASSWORD)["access_token"]
        except Exception as e:  # noqa: BLE001 — un actor caído no debe tumbar al resto
            print(f"  {role:10} ✗ no pudo entrar: {e}")
            continue
        me = qa.Client(role, token).get("/me")
        if not me.ok:
            print(f"  {role:10} ✗ /me devolvió {me.status} {me.code}")
            continue
        perms = me.body["permissions"]
        marca = "✓" if len(perms) == esperados else f"✗ esperaba {esperados}"
        print(f"  {role:10} {len(perms):2} permisos {marca}  ({me.body['company']['name']})")
        sessions[role] = {
            "token": token,
            "permissions": perms,
            "user_id": me.body["user"]["id"],
            "company_id": me.body["company"]["id"],
        }

    qa.save("sessions", sessions)

    # El super-admin de plataforma es una cuenta aparte: no pertenece al
    # laboratorio, así que solo se refresca si ya había una guardada.
    try:
        anterior = qa.load("session_admin")
    except FileNotFoundError:
        return
    if email := anterior.get("email"):
        s = qa.login(email, anterior["password"])
        qa.save("session_admin", {**anterior, "access_token": s["access_token"]})
        print(f"  {'super-admin':10} renovado ({email})")
    else:
        print("\n  Ojo: `session_admin.json` no guarda credenciales — renuévalo a mano.")
        print(f"  {json.dumps({'email': '...', 'password': '...'})} y vuelve a correr esto.")


if __name__ == "__main__":
    main()
