"""Laboratorio «ZZ AI»: ocho empresas desechables, una por frente de QA.

    python scripts/qa/lab_zzai.py --dry-run          # el plan, sin tocar la red
    python scripts/qa/lab_zzai.py --verificar        # solo lectura: cuenta lo que hay
    python scripts/qa/lab_zzai.py                    # crea lo que falte (idempotente)
    python scripts/qa/lab_zzai.py rotar-viejos       # rota la clave de los usuarios QA viejos
    python scripts/qa/lab_zzai.py rotar-viejos --dry-run

## Por qué ocho empresas y no una

Cada frente de la auditoría (identidad, contratos, caja, inventario...) ensucia
datos que otro frente lee: una sesión de caja abierta cambia lo que ve el que
prueba reportes, un rol editado rompe la matriz del que prueba permisos. Con
una empresa por frente, los barridos se pueden correr en paralelo sin pisarse,
y borrar el rastro de uno no toca a los demás. "Identidad B" existe para las
pruebas de aislamiento entre inquilinos (A no debe ver nada de B).

## Qué siembra en cada empresa

- Usuarios `zzai.<frente>.<rol>@qalab.com` para los cuatro roles semilla
  (Admin, Moderador, Asesor, Bodega) y un rol a medida **"Gestor usuarios"**
  con SOLO `identity.manage_users` — el que sirve para probar la salvaguarda
  del último admin sin ser admin.
- En "Identidad A", además, un rol **"P · <código>"** por cada permiso con un
  usuario `zzai.ida.p-NN@qalab.com`: la matriz permiso por permiso. Con un rol
  de un solo permiso, un 200 donde se esperaba 403 señala exactamente qué
  permiso abre de más, cosa que con los roles semilla (5 a 43 permisos) no se
  puede distinguir.
- El árbol de categorías con herencia REPARTIDA a propósito (el mismo del
  laboratorio viejo, docs/QA_AUDITORIA.md §"Datos sembrados"): Joyería define
  plazo/ventana/LTV y Oro → Cadena/Anillo no definen nada (la herencia sube dos
  niveles); Tecnología define solo la ventana y Celulares solo el plazo (la
  herencia es POR CAMPO). Gama alta cuelga de Celulares porque un artículo solo
  se clasifica en nivel 3.
- Dos proveedores con letra (ninguna de las reservadas R P T D).
- Cuentas: la `cash` que siembra el alta + 2 `bank` + 1 `settlement` + 1 `vault`.
  No se crea una segunda `cash`: el backend la rechaza (`CASH_ACCOUNT_ALREADY_EXISTS`)
  porque el arqueo cuenta un solo cajón.
- Tres clientes con datos evidentemente falsos (cédulas 100000000N, "Cliente
  Prueba Uno", correo @qalab.com) y SIN consentimiento de correo, para que
  ningún aviso salga hacia ellos.

**Las unidades por gramo no se siembran.** La unidad es del PRODUCTO, no de la
categoría (`inventory/units.py`), y un producto solo nace de un ingreso de
inventario (`POST /inventory/entries`), que mueve costo y a veces caja. Eso ya
es un dato del frente de Inventario, no del esqueleto del laboratorio.

## Cómo se crean los usuarios sin gastar correo

El flujo del README: el admin invita con `send_email: false` (el enlace vuelve
en la respuesta y se DESCARTA sin imprimirlo), y la contraseña se fija con el
service role (`PUT /auth/v1/admin/users/{id}`). Queda un paso que ninguno de
los dos avisa: el `app_user` sigue en `invited` hasta su primer request con una
sesión de CONTRASEÑA (`amr=password`, core/security.py). Por eso el script
hace login + `GET /me` con cada usuario recién creado — sin eso quedarían
"invitados" para siempre y la matriz probaría usuarios que la UI muestra
pendientes.

**Supabase Auth limita los logins a ~30 cada 5 min por IP.** La primera corrida
hace ~83; cuando llega el 429 el script espera y reintenta, así que tarda
unos quince minutos. Las siguientes corridas no hacen login de quien ya está
`active`, y son rápidas.

## Contraseñas

UNA por corrida para todo el laboratorio: `QA_LAB_PASSWORD` si está, si no la
que ya esté en `QA_LAB_SECRETS_FILE` (para que re-correr no rote todo), y si no
una nueva de `secrets`. **Nunca se imprime ni se escribe en el repo**: solo en
`QA_LAB_SECRETS_FILE`, que tiene que quedar FUERA del workspace (el repo es
público), con permisos 0600. En el mismo JSON quedan los ids de todo lo
sembrado. El archivo se escribe ANTES de fijar la primera contraseña: si la
corrida se cae a la mitad, la clave con la que quedaron los usuarios no se
pierde.

## Credencial de plataforma

Crear una empresa es de super-admin (`app_metadata.platform_role`). Se toma de
`QA_PLATFORM_TOKEN` (un JWT) o de `QA_PLATFORM_EMAIL` + `QA_PLATFORM_PASSWORD`.
Sin ninguna de las dos el script se detiene ANTES de tocar nada.

## Guardas

- Solo se escribe en empresas cuyo nombre empieza por "ZZ AI —". Después de
  entrar como el admin de cada una se compara `GET /me` (id y nombre) con la
  empresa esperada: si un correo `zzai.*` apareciera colgado de otra empresa
  —LA GRAN LEGAL, por ejemplo— el script aborta en vez de sembrarle datos.
- El service role solo fija contraseñas de correos `zzai.<frente>.<algo>@qalab.com`
  o de la lista fija de usuarios viejos, y el id sale SIEMPRE del listado de
  Auth buscado por correo, nunca de otra fuente.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import string
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))

import qa  # noqa: E402

# ------------------------------------------------------------ el plan ------
PREFIJO = "ZZ AI — "
PLAN_CODE = "full"  # los dos módulos: cada frente puede probar empeño y tienda

#: (slug del correo, sufijo del nombre de la empresa)
FRENTES: list[tuple[str, str]] = [
    ("ida", "Identidad A"),
    ("idb", "Identidad B"),
    ("contratos", "Contratos"),
    ("caja", "Caja"),
    ("inventario", "Inventario"),
    ("reportes", "Reportes"),
    ("documentos", "Documentos"),
    ("ui", "UI"),
]
#: El frente que además recibe un rol por permiso.
FRENTE_BARRIDO = "ida"

#: (slug del correo, nombre del rol semilla que crea el alta de la empresa)
ROLES_SEMILLA: list[tuple[str, str]] = [
    ("admin", "Admin"),
    ("moderador", "Moderador"),
    ("asesor", "Asesor"),
    ("bodega", "Bodega"),
]
ROL_GESTOR = "Gestor usuarios"
PERMISO_GESTOR = "identity.manage_users"
PREFIJO_ROL_PERMISO = "P · "


@dataclass(frozen=True)
class Categoria:
    nombre: str
    letra: str
    padre: str | None
    plazo: int | None = None
    ventana: int | None = None
    ltv: str | None = None


#: En orden: un padre siempre antes que sus hijas. Los números son los del
#: laboratorio viejo (QA_AUDITORIA.md, "La herencia de parámetros"): con
#: Tecnología en ventana 1, un contrato de Tecnología nunca llega a `in_arrears`,
#: y eso también es algo que un frente quiere poder probar.
CATEGORIAS: list[Categoria] = [
    Categoria("Joyería", "J", None, plazo=4, ventana=4, ltv="70"),
    Categoria("Oro", "O", "Joyería"),
    Categoria("Cadena", "C", "Oro"),
    Categoria("Anillo", "A", "Oro"),
    Categoria("Tecnología", "T", None, ventana=1),
    Categoria("Celulares", "C", "Tecnología", plazo=1),
    Categoria("Gama alta", "G", "Celulares"),
]

#: (nombre, letra, NIT ficticio). Letras fuera de R P T D (reservadas).
PROVEEDORES: list[tuple[str, str, str]] = [
    ("Joyas Ficticias ZZ", "J", "900000001"),
    ("Tecno Ficticio ZZ", "K", "900000002"),
]

#: La `cash` no está: la siembra el alta y es única por empresa.
CUENTAS: list[tuple[str, str]] = [
    ("Bancolombia ZZ", "bank"),
    ("Davivienda ZZ", "bank"),
    ("Sistecrédito ZZ", "settlement"),
    ("Caja fuerte ZZ", "vault"),
]

#: (nombre, cédula, teléfono, palabra para el correo)
CLIENTES: list[tuple[str, str, str, str]] = [
    ("Cliente Prueba Uno", "1000000001", "3000000001", "uno"),
    ("Cliente Prueba Dos", "1000000002", "3000000002", "dos"),
    ("Cliente Prueba Tres", "1000000003", "3000000003", "tres"),
]

#: Los usuarios del laboratorio viejo que rota `rotar-viejos`. Lista cerrada a
#: propósito: el service role puede cambiarle la clave a CUALQUIER usuario de
#: Supabase, incluida la cuenta del dueño; un patrón aquí sería una puerta.
VIEJOS: tuple[str, ...] = (
    "qa.admin@qalab.com",
    "qa.moderador@qalab.com",
    "qa.asesor@qalab.com",
    "qa.bodega@qalab.com",
    "qa.gestor@qalab.com",
    "qa.b.admin@qalab.com",
    "qa.datos.prueba@qalab.com",
)

_CORREO_LAB = re.compile(r"^zzai\.[a-z0-9-]+\.[a-z0-9-]+@qalab\.com$")

#: Supabase Auth: ~30 logins / 5 min por IP. Al 429 se espera esto y se reintenta.
ESPERA_429_S = 60
REINTENTOS_429 = 10


class LabError(Exception):
    """Un fallo que detiene la corrida con un mensaje legible (sin secretos)."""


def nombre_empresa(sufijo: str) -> str:
    return f"{PREFIJO}{sufijo}"


def correo(frente: str, rol: str) -> str:
    return f"zzai.{frente}.{rol}@qalab.com"


def correo_permiso(n: int) -> str:
    # Relleno a dos dígitos: así el orden alfabético de los correos coincide con
    # el de los permisos en cualquier listado.
    return correo(FRENTE_BARRIDO, f"p-{n:02d}")


def exigir_prefijo(nombre: str) -> None:
    if not nombre.startswith(PREFIJO):
        raise LabError(f"Negado: «{nombre}» no es una empresa del laboratorio ZZ AI.")


# ------------------------------------------------------------ secretos ------
def ruta_secretos(requerida: bool) -> Path | None:
    raw = os.environ.get("QA_LAB_SECRETS_FILE", "").strip()
    if not raw:
        if requerida:
            raise LabError(
                "Falta QA_LAB_SECRETS_FILE: la ruta (FUERA del repo) donde se escriben la "
                "contraseña del laboratorio y los ids sembrados. No se toca nada sin ella."
            )
        return None
    p = Path(raw).expanduser().resolve()
    # Fuera de TODO el workspace, no solo de este repo: el front también es
    # público, y un .json suelto en cualquiera de los dos se commitea sin querer.
    if p == qa.ROOT or qa.ROOT in p.parents:
        raise LabError(
            f"QA_LAB_SECRETS_FILE apunta dentro del workspace ({qa.ROOT}). "
            "Tiene que quedar fuera: el repo es público."
        )
    return p


def leer_secretos(p: Path | None) -> dict[str, Any]:
    if p is None or not p.exists():
        return {}
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise LabError(f"{p} no contiene un objeto JSON.")
    return data


def escribir_secretos(p: Path, data: dict[str, Any]) -> None:
    """Escritura atómica y con 0600 desde el primer byte.

    `os.open` con el modo, y no `write_text` + `chmod`: entre esas dos llamadas
    el archivo existe legible para cualquiera.
    """
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, p)
    os.chmod(p, 0o600)


def generar_contrasena() -> str:
    """28 caracteres con las cuatro clases: pase la política que pase Supabase."""
    alfabeto = string.ascii_letters + string.digits + "!#%*+-=?@_"
    while True:
        pw = "".join(secrets.choice(alfabeto) for _ in range(28))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(not c.isalnum() for c in pw)
        ):
            return pw


def contrasena_del_lab(guardado: dict[str, Any]) -> str:
    env = os.environ.get("QA_LAB_PASSWORD", "")
    if env:
        return env
    previa = guardado.get("password")
    if isinstance(previa, str) and previa:
        return previa
    return generar_contrasena()


# ----------------------------------------------------------------- auth ------
def login_con_espera(email: str, password: str) -> str:
    """`qa.login` con paciencia ante el 429 de Supabase Auth. Devuelve el JWT.

    El mensaje de error lleva el `error_code` de Supabase y nunca el cuerpo
    enviado: ahí va la contraseña.
    """
    for intento in range(REINTENTOS_429 + 1):
        try:
            token = qa.login(email, password)["access_token"]
            assert isinstance(token, str)
            return token
        except httpx.HTTPStatusError as exc:
            r = exc.response
            if r.status_code == 429 and intento < REINTENTOS_429:
                print(f"      … Auth limita los logins (429); espero {ESPERA_429_S} s")
                time.sleep(ESPERA_429_S)
                continue
            try:
                codigo = r.json().get("error_code") or r.json().get("error")
            except ValueError:
                codigo = None
            raise LabError(f"Login de {email} falló: {r.status_code} {codigo}") from None
    raise LabError(f"Login de {email}: se agotaron los reintentos por 429.")


class AuthUsuarios:
    """Índice correo → id de Supabase Auth, leído con el service role (solo GET).

    Es la ÚNICA fuente de ids para `PUT /admin/users/{id}`: buscar por correo
    acá garantiza que la contraseña que se cambia es la de ese correo y no la
    de un id que llegó de otro lado.
    """

    def __init__(self) -> None:
        self._mapa: dict[str, str] | None = None

    def invalidar(self) -> None:
        self._mapa = None

    def mapa(self) -> dict[str, str]:
        if self._mapa is None:
            out: dict[str, str] = {}
            page, per_page = 1, 500
            while True:
                r = httpx.get(
                    f"{qa.SUPABASE_URL}/auth/v1/admin/users",
                    headers=qa.admin_headers(),
                    params={"page": page, "per_page": per_page},
                    timeout=qa.TIMEOUT,
                )
                if r.status_code != 200:
                    raise LabError(f"Listar usuarios de Auth falló: {r.status_code}")
                users = r.json().get("users", [])
                for u in users:
                    if u.get("email"):
                        out[u["email"].lower()] = u["id"]
                if len(users) < per_page:
                    break
                page += 1
            self._mapa = out
        return self._mapa

    def id_de(self, email: str) -> str | None:
        return self.mapa().get(email.lower())


def fijar_contrasena(auth: AuthUsuarios, email: str, password: str) -> str:
    if not (_CORREO_LAB.match(email) or email in VIEJOS):
        raise LabError(f"Negado: {email} no es un usuario del laboratorio.")
    uid = auth.id_de(email)
    if uid is None:
        raise LabError(f"{email} no existe en Supabase Auth.")
    r = httpx.put(
        f"{qa.SUPABASE_URL}/auth/v1/admin/users/{uid}",
        headers=qa.admin_headers(),
        # `email_confirm`: un invitado que nunca abrió el enlace tiene el correo
        # sin confirmar, y Supabase rechaza su login por contraseña.
        json={"password": password, "email_confirm": True},
        timeout=qa.TIMEOUT,
    )
    if r.status_code != 200:
        raise LabError(f"Fijar contraseña de {email} falló: {r.status_code}")
    return uid


def token_plataforma() -> str:
    tok = os.environ.get("QA_PLATFORM_TOKEN", "").strip()
    if not tok:
        email = os.environ.get("QA_PLATFORM_EMAIL", "").strip()
        pw = os.environ.get("QA_PLATFORM_PASSWORD", "")
        if not (email and pw):
            raise LabError(
                "Sin credencial de plataforma. Exporta QA_PLATFORM_TOKEN (JWT de super-admin) "
                "o QA_PLATFORM_EMAIL + QA_PLATFORM_PASSWORD. No se tocó nada."
            )
        tok = login_con_espera(email, pw)
    try:
        claims = qa.decode_jwt(tok)
    except Exception:
        raise LabError("QA_PLATFORM_TOKEN no es un JWT legible.") from None
    if claims.get("app_metadata", {}).get("platform_role") != "super_admin":
        raise LabError("La credencial de plataforma no es de super-admin. No se tocó nada.")
    if int(claims.get("exp", 0)) < time.time() + 60:
        raise LabError("El JWT de plataforma está vencido (o vence en menos de un minuto).")
    return tok


# ------------------------------------------------------------- HTTP app ------
def exigir(res: qa.Result, contexto: str) -> Any:
    """El cuerpo si fue 2xx; si no, un LabError con status + `code` + mensaje.

    El mensaje del envelope de error nunca trae credenciales; el cuerpo de un
    2xx sí puede (`invite_link`, `admin_invite_link`), y por eso ESE jamás se
    imprime.
    """
    if res.ok:
        return res.body
    msg = res.body.get("message") if isinstance(res.body, dict) else None
    raise LabError(f"{contexto}: {res.status} {res.code or ''} {msg or ''}".rstrip())


def listar(c: qa.Client, path: str, **params: Any) -> list[dict[str, Any]]:
    """Recorre un `CursorPage` entero."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        q = dict(params, limit=200)
        if cursor:
            q["cursor"] = cursor
        body = exigir(c.get(path, params=q), f"GET {path}")
        items.extend(body["items"])
        cursor = body.get("next_cursor")
        if not cursor:
            return items


# -------------------------------------------------------- el plan en sí ------
@dataclass(frozen=True)
class UsuarioPlan:
    email: str
    nombre: str
    rol: str


def usuarios_del_frente(frente: str, sufijo: str, permisos: list[str]) -> list[UsuarioPlan]:
    out = [
        UsuarioPlan(correo(frente, slug), f"ZZ AI {rol} {sufijo}", rol)
        for slug, rol in ROLES_SEMILLA
    ]
    out.append(UsuarioPlan(correo(frente, "gestor"), f"ZZ AI Gestor {sufijo}", ROL_GESTOR))
    if frente == FRENTE_BARRIDO:
        for n, code in enumerate(permisos, start=1):
            out.append(
                UsuarioPlan(
                    correo_permiso(n), f"ZZ AI P-{n:02d} {code}", PREFIJO_ROL_PERMISO + code
                )
            )
    return out


def roles_a_medida(frente: str, permisos: list[str]) -> dict[str, list[str]]:
    out = {ROL_GESTOR: [PERMISO_GESTOR]}
    if frente == FRENTE_BARRIDO:
        out.update({PREFIJO_ROL_PERMISO + code: [code] for code in permisos})
    return out


def permisos_de_migraciones() -> list[str]:
    """Vista previa OFFLINE para `--dry-run`. La corrida real los lee de la API.

    Solo sirve para mostrar el plan sin red; si discrepa de
    `GET /identity/permissions`, gana la API.
    """
    migr = Path(__file__).resolve().parents[2] / "supabase"
    codes: set[str] = set()
    for f in migr.rglob("*.sql"):
        codes.update(re.findall(r"\('([a-z_]+\.[a-z_]+)'", f.read_text()))
    return sorted(codes)


def imprimir_plan() -> int:
    permisos = permisos_de_migraciones()
    total_usuarios = 0
    print("\n  PLAN del laboratorio ZZ AI (dry-run: no se hace ninguna llamada de red)\n")
    print(f"  Backend: {qa.API}   plan de suscripción: {PLAN_CODE}\n")
    for frente, sufijo in FRENTES:
        nombre = nombre_empresa(sufijo)
        exigir_prefijo(nombre)
        usuarios = usuarios_del_frente(frente, sufijo, permisos)
        total_usuarios += len(usuarios)
        print(f"  ▸ {nombre}")
        print(f"      alta: POST /platform/companies  primer admin {correo(frente, 'admin')}")
        for u in usuarios[: len(ROLES_SEMILLA) + 1]:
            print(f"      usuario {u.email:<38} rol {u.rol}")
        if frente == FRENTE_BARRIDO:
            print(f"      + {len(permisos)} roles «{PREFIJO_ROL_PERMISO}<código>» con su usuario:")
            for n, code in enumerate(permisos, start=1):
                print(f"          {correo_permiso(n):<30} {PREFIJO_ROL_PERMISO}{code}")
        print(f"      rol a medida «{ROL_GESTOR}» = [{PERMISO_GESTOR}]")
        cats = ", ".join(
            f"{c.nombre}({c.letra}{'←' + c.padre if c.padre else ''})" for c in CATEGORIAS
        )
        print(f"      categorías: {cats}")
        print(f"      proveedores: {', '.join(f'{n} [{letra}]' for n, letra, _ in PROVEEDORES)}")
        cuentas = ", ".join(f"{n} ({t})" for n, t in CUENTAS)
        print(f"      cuentas: Caja principal (cash, del alta) + {cuentas}")
        print(f"      clientes: {', '.join(f'{n} cc {d}' for n, d, _, _ in CLIENTES)}\n")
    print(f"  Total: {len(FRENTES)} empresas, {total_usuarios} usuarios.")
    print(f"  Permisos (vista previa desde las migraciones locales): {len(permisos)}")
    print("  Contraseña: una por corrida; va SOLO a QA_LAB_SECRETS_FILE, nunca a pantalla.\n")
    return 0


# ------------------------------------------------------------- siembra ------
class Siembra:
    def __init__(self, password: str, ruta: Path, guardado: dict[str, Any]) -> None:
        self.password = password
        self.ruta = ruta
        self.data = guardado
        self.auth = AuthUsuarios()
        self.plataforma = qa.Client(label="plataforma", token=token_plataforma())

    def guardar(self) -> None:
        escribir_secretos(self.ruta, self.data)

    # -- empresas --
    def empresas_por_nombre(self) -> dict[str, dict[str, Any]]:
        return {c["name"]: c for c in listar(self.plataforma, "/platform/companies")}

    def asegurar_empresa(self, frente: str, sufijo: str, existentes: dict[str, Any]) -> str:
        nombre = nombre_empresa(sufijo)
        exigir_prefijo(nombre)
        if nombre in existentes:
            emp = existentes[nombre]
            if emp["status"] != "active":
                raise LabError(f"{nombre} existe pero está «{emp['status']}»; no se toca.")
            print(f"    = empresa existe ({emp['id']})")
            return str(emp["id"])
        vence = dt.date.today() + dt.timedelta(days=365)
        body = exigir(
            self.plataforma.post(
                "/platform/companies",
                json={
                    "name": nombre,
                    "plan_code": PLAN_CODE,
                    "subscription_expires_at": vence.isoformat(),
                    "first_admin_email": correo(frente, "admin"),
                    "first_admin_full_name": f"ZZ AI Admin {sufijo}",
                    "send_email": False,
                },
            ),
            f"crear {nombre}",
        )
        # `admin_invite_link` viene en `body` y se descarta aquí sin imprimirse:
        # la contraseña se fija por service role, el enlace no hace falta.
        self.auth.invalidar()
        print(f"    + empresa creada ({body['id']})")
        return str(body["id"])

    # -- admin --
    def entrar_como_admin(self, frente: str, nombre: str, company_id: str) -> qa.Client:
        email = correo(frente, "admin")
        fijar_contrasena(self.auth, email, self.password)
        c = qa.Client(label=email, token=login_con_espera(email, self.password))
        me = exigir(c.get("/me"), f"GET /me de {email}")
        # LA guarda: de acá en adelante todo se escribe con el token de este
        # usuario, así que el destino lo decide a qué empresa pertenece él.
        if str(me["company"]["id"]) != company_id or me["company"]["name"] != nombre:
            raise LabError(
                f"{email} pertenece a «{me['company']['name']}», no a «{nombre}». Abortado."
            )
        exigir_prefijo(me["company"]["name"])
        return c

    # -- roles --
    def asegurar_roles(self, c: qa.Client, a_medida: dict[str, list[str]]) -> dict[str, str]:
        roles = {r["name"]: str(r["id"]) for r in exigir(c.get("/identity/roles"), "roles")}
        for _, semilla in ROLES_SEMILLA:
            if semilla not in roles:
                raise LabError(f"Falta el rol semilla «{semilla}».")
        creados = 0
        for nombre, codes in a_medida.items():
            if nombre not in roles:
                body = exigir(
                    c.post(
                        "/identity/roles",
                        json={"name": nombre, "description": "Laboratorio QA (lab_zzai.py)"},
                    ),
                    f"crear rol {nombre}",
                )
                roles[nombre] = str(body["id"])
                creados += 1
            rid = roles[nombre]
            actuales = exigir(c.get(f"/identity/roles/{rid}/permissions"), f"permisos {nombre}")
            # Solo se reescribe si difiere: cada PUT deja una fila de auditoría,
            # y una corrida idempotente no debería ensuciar el registro.
            if sorted(actuales) != sorted(codes):
                exigir(
                    c.put(f"/identity/roles/{rid}/permissions", json={"permission_codes": codes}),
                    f"fijar permisos {nombre}",
                )
        print(f"    roles: {len(a_medida)} a medida ({creados} nuevos)")
        return roles

    # -- usuarios --
    def asegurar_usuarios(
        self, c: qa.Client, plan: list[UsuarioPlan], roles: dict[str, str]
    ) -> dict[str, dict[str, Any]]:
        en_empresa = {u["email"].lower(): u for u in listar(c, "/identity/users")}
        invitados = 0
        for u in plan:
            rid = roles[u.rol]
            actual = en_empresa.get(u.email)
            if actual is None:
                # Un usuario de Auth con este correo pero sin fila en ESTA
                # empresa es de otra: invitarlo reventaría en Supabase, y
                # "arreglarlo" sería moverlo de empresa. Se reporta.
                if self.auth.id_de(u.email) is not None:
                    raise LabError(f"{u.email} existe en Auth pero no en esta empresa. Revisar.")
                body = exigir(
                    c.post(
                        "/identity/invitations",
                        json={
                            "email": u.email,
                            "full_name": u.nombre,
                            "role_id": rid,
                            "send_email": False,
                        },
                    ),
                    f"invitar {u.email}",
                )
                # `invite_link` se descarta: ver `asegurar_empresa`.
                en_empresa[u.email] = {k: body[k] for k in ("id", "email", "role_id", "status")}
                invitados += 1
            elif str(actual["role_id"]) != rid:
                # Pasa si se agregó un permiso: la numeración p-NN se corre y el
                # usuario queda con el rol del código vecino. Se realinea.
                exigir(
                    c.patch(f"/identity/users/{actual['id']}/role", json={"role_id": rid}),
                    f"realinear rol de {u.email}",
                )
                actual["role_id"] = rid
                print(f"      ~ {u.email} realineado a «{u.rol}»")
        if invitados:
            self.auth.invalidar()
        print(f"    usuarios: {len(plan)} ({invitados} invitados ahora)")

        # Contraseña para todos: garantiza que el archivo de secretos dice la
        # verdad aunque la clave haya cambiado entre corridas.
        activados = 0
        for u in plan:
            fijar_contrasena(self.auth, u.email, self.password)
            fila = en_empresa[u.email]
            if fila["status"] == "inactive":
                print(f"      ! {u.email} está inactivo; no se reactiva solo")
            elif fila["status"] != "active":
                tok = login_con_espera(u.email, self.password)
                exigir(qa.Client(u.email, tok).get("/me"), f"activar {u.email}")
                fila["status"] = "active"
                activados += 1
        print(f"    contraseñas fijadas: {len(plan)} · activados con login: {activados}")
        return {
            u.email: {"id": str(en_empresa[u.email]["id"]), "rol": u.rol, "role_id": roles[u.rol]}
            for u in plan
        }

    # -- catálogo --
    def asegurar_catalogo(self, c: qa.Client) -> tuple[dict[str, str], dict[str, str]]:
        existentes = exigir(c.get("/catalogs/categories"), "categorías")
        ids_por_nombre: dict[str, str] = {}
        por_padre_nombre = {(x["parent_id"], x["name"]): str(x["id"]) for x in existentes}
        nuevas = 0
        for cat in CATEGORIAS:
            padre = ids_por_nombre[cat.padre] if cat.padre else None
            clave = (padre, cat.nombre)
            if clave in por_padre_nombre:
                ids_por_nombre[cat.nombre] = por_padre_nombre[clave]
                continue
            body = exigir(
                c.post(
                    "/catalogs/categories",
                    json={
                        "parent_id": padre,
                        "name": cat.nombre,
                        "code_letter": cat.letra,
                        "default_term_months": cat.plazo,
                        "arrears_window_months": cat.ventana,
                        "max_ltv_pct": cat.ltv,
                    },
                ),
                f"categoría {cat.nombre}",
            )
            ids_por_nombre[cat.nombre] = str(body["id"])
            nuevas += 1
        # Clave "Padre/Hija" en la salida: hay dos «C» y un nombre solo no
        # alcanza para leer el árbol desde el JSON.
        categorias = {
            (f"{cat.padre}/{cat.nombre}" if cat.padre else cat.nombre): ids_por_nombre[cat.nombre]
            for cat in CATEGORIAS
        }

        provs = {p["name"]: str(p["id"]) for p in listar(c, "/catalogs/suppliers")}
        nuevos = 0
        for nombre, letra, nit in PROVEEDORES:
            if nombre in provs:
                continue
            body = exigir(
                c.post(
                    "/catalogs/suppliers",
                    json={
                        "name": nombre,
                        "code_letter": letra,
                        "doc_type": "nit",
                        "doc_number": nit,
                        "notes": "Proveedor ficticio del laboratorio QA (lab_zzai.py).",
                    },
                ),
                f"proveedor {nombre}",
            )
            provs[nombre] = str(body["id"])
            nuevos += 1
        print(
            f"    catálogo: {len(CATEGORIAS)} categorías ({nuevas} nuevas), "
            f"{len(PROVEEDORES)} proveedores ({nuevos} nuevos)"
        )
        return categorias, {n: provs[n] for n, _, _ in PROVEEDORES}

    # -- cuentas --
    def asegurar_cuentas(self, c: qa.Client) -> dict[str, str]:
        cuentas = exigir(c.get("/accounts", params={"include_inactive": "true"}), "cuentas")
        por_nombre = {a["name"]: a for a in cuentas}
        cash = [a for a in cuentas if a["type"] == "cash" and a["active"]]
        if len(cash) != 1:
            raise LabError(f"Se esperaba exactamente una cuenta cash activa; hay {len(cash)}.")
        out = {cash[0]["name"]: str(cash[0]["id"])}
        nuevas = 0
        for nombre, tipo in CUENTAS:
            if nombre in por_nombre:
                if por_nombre[nombre]["type"] != tipo:
                    raise LabError(f"La cuenta «{nombre}» existe con otro tipo.")
                out[nombre] = str(por_nombre[nombre]["id"])
                continue
            body = exigir(
                c.post("/accounts", json={"name": nombre, "type": tipo}), f"cuenta {nombre}"
            )
            out[nombre] = str(body["id"])
            nuevas += 1
        print(f"    cuentas: {len(out)} ({nuevas} nuevas)")
        return out

    # -- clientes --
    def asegurar_clientes(self, c: qa.Client, frente: str) -> dict[str, str]:
        out: dict[str, str] = {}
        nuevos = 0
        for nombre, cedula, tel, palabra in CLIENTES:
            hallados = listar(c, "/customers", q=cedula)
            match = [x for x in hallados if x["doc_type"] == "cc" and x["doc_number"] == cedula]
            if match:
                out[nombre] = str(match[0]["id"])
                continue
            body = exigir(
                c.post(
                    "/customers",
                    json={
                        "full_name": nombre,
                        "doc_type": "cc",
                        "doc_number": cedula,
                        "phone": tel,
                        "email": f"cliente.{palabra}.{frente}@qalab.com",
                        "address": "Calle Ficticia 123",
                        "notes": "Dato ficticio del laboratorio QA (lab_zzai.py).",
                    },
                ),
                f"cliente {nombre}",
            )
            out[nombre] = str(body["id"])
            nuevos += 1
        print(f"    clientes: {len(out)} ({nuevos} nuevos)")
        return out

    # -- todo --
    def correr(self) -> int:
        self.data["password"] = self.password
        self.data["api"] = qa.API
        self.data["actualizado"] = dt.datetime.now().isoformat(timespec="seconds")
        self.data.setdefault("empresas", {})
        # Antes de la primera contraseña: ver el docstring del módulo.
        self.guardar()

        existentes = self.empresas_por_nombre()
        permisos: list[str] = []
        for frente, sufijo in FRENTES:
            nombre = nombre_empresa(sufijo)
            print(f"\n  ▸ {nombre}")
            company_id = self.asegurar_empresa(frente, sufijo, existentes)
            c = self.entrar_como_admin(frente, nombre, company_id)
            if not permisos:
                permisos = sorted(
                    p["code"] for p in exigir(c.get("/identity/permissions"), "permisos")
                )
            roles = self.asegurar_roles(c, roles_a_medida(frente, permisos))
            usuarios = self.asegurar_usuarios(
                c, usuarios_del_frente(frente, sufijo, permisos), roles
            )
            categorias, proveedores = self.asegurar_catalogo(c)
            cuentas = self.asegurar_cuentas(c)
            clientes = self.asegurar_clientes(c, frente)
            self.data["empresas"][nombre] = {
                "id": company_id,
                "frente": frente,
                "usuarios": usuarios,
                "roles": roles,
                "categorias": categorias,
                "proveedores": proveedores,
                "cuentas": cuentas,
                "clientes": clientes,
            }
            # Por empresa y no al final: si la séptima falla, las seis primeras
            # ya quedaron registradas con sus ids.
            self.guardar()
        print(f"\n  Listo. Contraseña e ids en {self.ruta} (0600). No se imprimieron.\n")
        return 0


# ----------------------------------------------------------- verificar ------
def verificar() -> int:
    """Solo lectura. Sale 0 completo, 1 si falta algo, 2 si no se pudo verificar.

    El 2 no es un lujo (mismo criterio que `verificar_cadenas.py`): "no pude
    mirar" no es lo mismo que "falta", y confundirlos hace que el guardián
    se empiece a ignorar.
    """
    ruta = ruta_secretos(requerida=False)
    guardado = leer_secretos(ruta)
    password = os.environ.get("QA_LAB_PASSWORD") or guardado.get("password")
    faltas = 0

    # 1) Usuarios en Auth: no necesita más que el service role.
    auth = AuthUsuarios()
    lab = sorted(e for e in auth.mapa() if _CORREO_LAB.match(e))
    print(f"\n  Usuarios zzai.* en Supabase Auth: {len(lab)}")

    # 2) Empresas: con la credencial de plataforma, si la hay.
    empresas: dict[str, dict[str, Any]] | None = None
    try:
        plataforma = qa.Client(label="plataforma", token=token_plataforma())
        empresas = {c["name"]: c for c in listar(plataforma, "/platform/companies")}
    except LabError as exc:
        print(f"  (sin listado de plataforma: {exc})")

    if empresas is None and not password:
        print("  No se pudo verificar: sin credencial de plataforma ni contraseña del laboratorio.")
        return 2

    permisos_n: int | None = None
    for frente, sufijo in FRENTES:
        nombre = nombre_empresa(sufijo)
        linea = f"  {nombre:<24}"
        if empresas is not None:
            emp = empresas.get(nombre)
            if emp is None:
                print(f"{linea} NO EXISTE")
                faltas += 1
                continue
            linea += f" {emp['status']:<9}"
        if not password:
            print(f"{linea} (sin contraseña: no se cuentan los datos)")
            continue
        email = correo(frente, "admin")
        try:
            c = qa.Client(label=email, token=login_con_espera(email, password))
            me = exigir(c.get("/me"), "GET /me")
        except LabError as exc:
            print(f"{linea} no se pudo entrar: {exc}")
            faltas += 1
            continue
        if me["company"]["name"] != nombre:
            print(f"{linea} ¡{email} es de «{me['company']['name']}»!")
            faltas += 1
            continue
        if permisos_n is None:
            permisos_n = len(exigir(c.get("/identity/permissions"), "permisos"))
        users = [u for u in listar(c, "/identity/users") if _CORREO_LAB.match(u["email"])]
        activos = sum(1 for u in users if u["status"] == "active")
        roles = exigir(c.get("/identity/roles"), "roles")
        a_medida = [r for r in roles if not r["is_seed"]]
        cats = exigir(c.get("/catalogs/categories"), "categorías")
        provs = listar(c, "/catalogs/suppliers")
        cuentas = exigir(c.get("/accounts"), "cuentas")
        clientes = sum(
            1
            for _, ced, _, _ in CLIENTES
            if any(x["doc_number"] == ced for x in listar(c, "/customers", q=ced))
        )
        esperados_u = len(ROLES_SEMILLA) + 1 + (permisos_n if frente == FRENTE_BARRIDO else 0)
        esperados_r = 1 + (permisos_n if frente == FRENTE_BARRIDO else 0)
        cuentas_nombres = {a["name"] for a in cuentas}
        ok = (
            activos >= esperados_u
            and len(a_medida) >= esperados_r
            and {c_.nombre for c_ in CATEGORIAS} <= {x["name"] for x in cats}
            and {n for n, _, _ in PROVEEDORES} <= {p["name"] for p in provs}
            and {n for n, _ in CUENTAS} <= cuentas_nombres
            and clientes == len(CLIENTES)
        )
        faltas += 0 if ok else 1
        print(
            f"{linea} usuarios {activos}/{len(users)} activos (≥{esperados_u}) · "
            f"roles a medida {len(a_medida)} · categorías {len(cats)} · "
            f"proveedores {len(provs)} · cuentas {len(cuentas)} · clientes {clientes}"
            f"  {'OK' if ok else 'INCOMPLETO'}"
        )
    print()
    return 1 if faltas else 0


# --------------------------------------------------------- rotar-viejos ------
def rotar_viejos(dry: bool) -> int:
    ruta = ruta_secretos(requerida=not dry)
    auth = AuthUsuarios()
    hallados = {e: auth.id_de(e) for e in VIEJOS}
    print("\n  Usuarios QA viejos:")
    for e, uid in hallados.items():
        print(f"    {e:<30} {'encontrado' if uid else 'NO EXISTE en Auth'}")
    if dry:
        print("\n  dry-run: no se cambió ninguna contraseña.\n")
        return 0
    assert ruta is not None
    data = leer_secretos(ruta)
    data["viejos"] = {
        "password": generar_contrasena(),
        "rotado": dt.datetime.now().isoformat(timespec="seconds"),
        "usuarios": {e: uid for e, uid in hallados.items() if uid},
    }
    # Primero el archivo, después las claves: ver el docstring del módulo.
    escribir_secretos(ruta, data)
    for e, uid in hallados.items():
        if uid:
            fijar_contrasena(auth, e, data["viejos"]["password"])
    print(f"\n  Rotadas {sum(1 for u in hallados.values() if u)}. Nueva clave en {ruta} (0600).")
    print("  OJO: los scripts que usan QA_PASSWORD con estos usuarios necesitan la nueva.\n")
    return 0


# ----------------------------------------------------------------- main ------
def main() -> int:
    ap = argparse.ArgumentParser(description="Laboratorio ZZ AI de QA (ver docstring).")
    ap.add_argument("accion", nargs="?", choices=["sembrar", "rotar-viejos"], default="sembrar")
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--dry-run", action="store_true", help="solo imprime el plan")
    modo.add_argument("--verificar", action="store_true", help="solo lectura: cuenta lo que hay")
    args = ap.parse_args()

    try:
        if args.accion == "rotar-viejos":
            if args.verificar:
                ap.error("rotar-viejos no tiene --verificar")
            return rotar_viejos(dry=args.dry_run)
        if args.dry_run:
            return imprimir_plan()
        if args.verificar:
            return verificar()
        # Todo lo que puede faltar se comprueba ANTES de la primera escritura.
        ruta = ruta_secretos(requerida=True)
        assert ruta is not None
        guardado = leer_secretos(ruta)
        return Siembra(contrasena_del_lab(guardado), ruta, guardado).correr()
    except LabError as exc:
        print(f"\n  ERROR: {exc}\n", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
