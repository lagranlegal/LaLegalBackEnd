"""Integración de identity (paso 3): invitaciones, roles, matriz de permisos,
salvaguardas de último admin, activación automática invited->active en el
primer login. Requiere Postgres real (se salta si no hay).
"""

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _concurrency import Peticion, en_paralelo
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.modules.identity import auth_admin as identity_auth_admin


async def _postgres_available() -> bool:
    try:
        async with engine.connect():
            return True
    except Exception:
        return False


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _require_postgres() -> None:
    if not await _postgres_available():
        pytest.skip("Postgres local no disponible: correr `supabase start` primero.")


@pytest_asyncio.fixture
async def mocked_invite(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    invited_emails: list[str] = []

    async def _fake_invite(
        email: str, full_name: str, *, send_email: bool = True
    ) -> identity_auth_admin.Invitation:
        invited_emails.append(email)
        # `link` solo cuando NO se manda correo, igual que el real.
        return identity_auth_admin.Invitation(
            user_id=uuid4(), link=None if send_email else "https://supabase.test/verify?token=fake"
        )

    monkeypatch.setattr(identity_auth_admin, "invite_user", _fake_invite)
    return invited_emails


@pytest_asyncio.fixture
async def tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    """Empresa con un rol Admin (todos los permisos) + 1 usuario activo, y un
    rol Bodega (sin permisos de identity) para probar reasignaciones.
    """
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    admin_role_id = uuid4()
    basic_role_id = uuid4()
    admin_user_id = uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, :name)"),
            {"id": str(company_id), "name": "Empresa identity-test"},
        )
        await session.execute(
            text(
                "insert into public.role (id, company_id, name, is_seed) "
                "values (:id, :company_id, :name, true)"
            ),
            [
                {"id": str(admin_role_id), "company_id": str(company_id), "name": "Admin"},
                {"id": str(basic_role_id), "company_id": str(company_id), "name": "Bodega"},
            ],
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission"
            ),
            {"role_id": str(admin_role_id)},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code = 'inventory.view'"
            ),
            {"role_id": str(basic_role_id)},
        )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :company_id, :role_id, 'Admin Test', :email, 'active')"
            ),
            {
                "id": str(admin_user_id),
                "company_id": str(company_id),
                "role_id": str(admin_role_id),
                "email": f"admin-{admin_user_id}@example.com",
            },
        )
        plan_id = (await session.execute(text("select id from public.plan limit 1"))).scalar_one()
        await session.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:company_id, :plan_id, 'active', current_date + 30)"
            ),
            {"company_id": str(company_id), "plan_id": str(plan_id)},
        )

    admin_token = make_token(
        private_pem,
        sub=str(admin_user_id),
        company_id=str(company_id),
        role_id=str(admin_role_id),
    )

    yield {
        "company_id": company_id,
        "admin_role_id": admin_role_id,
        "basic_role_id": basic_role_id,
        "admin_user_id": admin_user_id,
        "admin_token": admin_token,
        "admin_email": f"admin-{admin_user_id}@example.com",
        "private_pem": private_pem,
    }

    # audit_log es inmutable (trigger forbid_change) y no tiene FK hacia
    # company/role — se deja huérfano a propósito, no bloquea el cleanup.
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("delete from public.app_user where company_id = :id"), {"id": str(company_id)}
        )
        await session.execute(
            text(
                "delete from public.role_permission where role_id in "
                "(select id from public.role where company_id = :id)"
            ),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.role where company_id = :id"), {"id": str(company_id)}
        )
        await session.execute(
            text("delete from public.subscription where company_id = :id"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.company where id = :id"), {"id": str(company_id)}
        )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_invite_user(client: TestClient, tenant: dict, mocked_invite: list[str]) -> None:
    response = client.post(
        "/api/v1/identity/invitations",
        headers=_headers(tenant["admin_token"]),
        json={
            "email": "nuevo@example.com",
            "full_name": "Nuevo Usuario",
            "role_id": str(tenant["basic_role_id"]),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "invited"
    assert body["role_id"] == str(tenant["basic_role_id"])
    assert mocked_invite == ["nuevo@example.com"]


def test_invite_por_enlace_no_manda_correo_y_devuelve_el_link(
    client: TestClient, tenant: dict, mocked_invite: list[str]
) -> None:
    """`send_email=false` crea al usuario igual, pero devuelve el enlace.

    Es la salida cuando el correo no llega, cae en spam, o la persona está
    parada al lado del admin — que en una compraventa es lo normal. No
    consume la cuota de envíos de Supabase, que es baja a propósito en el
    servicio incluido.
    """
    response = client.post(
        "/api/v1/identity/invitations",
        headers=_headers(tenant["admin_token"]),
        json={
            "email": "por-enlace@example.com",
            "full_name": "Por Enlace",
            "role_id": str(tenant["basic_role_id"]),
            "send_email": False,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # El usuario queda igual que con una invitación por correo…
    assert body["status"] == "invited"
    assert body["role_id"] == str(tenant["basic_role_id"])
    # …y además vuelve el enlace para entregarlo a mano.
    assert body["invite_link"] == "https://supabase.test/verify?token=fake"


def test_reinvitar_a_alguien_ya_invitado_explica_que_hacer(
    client: TestClient, tenant: dict, mocked_invite: list[str]
) -> None:
    """Invitar dos veces al mismo correo es NORMAL: "no le llegó, mándaselo otra vez".

    Antes el segundo intento reventaba el índice único de `app_user` y salía
    un **500 en texto plano** — ni siquiera el envelope de error, así que el
    front lo mostraba como "Ocurrió un error inesperado". Y encima Supabase ya
    había regenerado el enlace, dejando muerto el primero, que el admin quizá
    ya había mandado por WhatsApp.

    Encontrado auditando los flujos de identidad el 04/09/2026, después de que
    un cliente reportara "no se pueden crear usuarios".
    """
    cuerpo = {
        "email": "repetido@example.com",
        "full_name": "Repetido",
        "role_id": str(tenant["basic_role_id"]),
        "send_email": False,
    }
    primera = client.post(
        "/api/v1/identity/invitations", headers=_headers(tenant["admin_token"]), json=cuerpo
    )
    assert primera.status_code == 201, primera.text

    segunda = client.post(
        "/api/v1/identity/invitations", headers=_headers(tenant["admin_token"]), json=cuerpo
    )
    assert segunda.status_code == 409, segunda.text
    body = segunda.json()
    assert body["code"] == "USER_ALREADY_INVITED"
    # El mensaje tiene que nombrar la acción correcta, no solo negar la que se
    # intentó: la salida es generar el enlace desde su ficha.
    assert "activación" in body["message"]


def test_invitar_a_alguien_ya_activo_no_lo_pisa(
    client: TestClient, tenant: dict, mocked_invite: list[str]
) -> None:
    """El admin de la empresa ya existe y está activo: invitarlo de nuevo es un
    error del admin, no una falla del sistema."""
    response = client.post(
        "/api/v1/identity/invitations",
        headers=_headers(tenant["admin_token"]),
        json={
            "email": tenant["admin_email"],
            "full_name": "Duplicado",
            "role_id": str(tenant["basic_role_id"]),
            "send_email": False,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "USER_ALREADY_EXISTS"


def test_invite_por_correo_no_devuelve_enlace(
    client: TestClient, tenant: dict, mocked_invite: list[str]
) -> None:
    """El enlace es una credencial de un solo uso: quien lo tenga se
    convierte en ese usuario. Si el correo ya salió, no hay razón para que
    ande dando vueltas también en una respuesta HTTP."""
    response = client.post(
        "/api/v1/identity/invitations",
        headers=_headers(tenant["admin_token"]),
        json={
            "email": "por-correo@example.com",
            "full_name": "Por Correo",
            "role_id": str(tenant["basic_role_id"]),
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["invite_link"] is None


def test_list_roles_expone_cuantos_permisos_tiene_cada_rol(
    client: TestClient, tenant: dict
) -> None:
    """Un rol en 0 permisos no sirve para nada — quien lo tenga no puede ni
    ver la caja ni el inventario, y la app le muestra mensajes que parecen
    errores ("Caja cerrada", "no se pudo cargar") en vez de decirle que le
    faltan permisos. Sin este dato, el listado de roles no lo distinguía de
    uno bien configurado.
    """
    # Un rol recién creado nace SIN permisos — es exactamente lo que pasa
    # cuando un admin crea un rol y no abre la matriz a marcarlos.
    creado = client.post(
        "/api/v1/identity/roles",
        headers=_headers(tenant["admin_token"]),
        json={"name": "Cajero Temporal", "description": None},
    )
    assert creado.status_code == 201, creado.text

    response = client.get("/api/v1/identity/roles", headers=_headers(tenant["admin_token"]))
    assert response.status_code == 200
    por_nombre = {r["name"]: r["permission_count"] for r in response.json()}
    assert por_nombre["Admin"] > 0
    assert por_nombre["Cajero Temporal"] == 0


def test_list_users_includes_admin(client: TestClient, tenant: dict) -> None:
    response = client.get("/api/v1/identity/users", headers=_headers(tenant["admin_token"]))
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert str(tenant["admin_user_id"]) in ids


async def test_deactivate_last_admin_is_blocked(client: TestClient, tenant: dict) -> None:
    """Dejar a la empresa sin ningún administrador activo la deja sin dueño.

    Lo intenta OTRA persona, no el propio admin: quien tiene
    `identity.manage_users` pero no `identity.manage_roles` puede gestionar
    usuarios sin ser administrador, y es el único camino por el que se llega
    a este safeguard desde que desactivarse a uno mismo se rechaza antes
    (`CANNOT_DEACTIVATE_SELF`).
    """
    gestor_id = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code = 'identity.manage_users'"
            ),
            {"role_id": str(tenant["basic_role_id"])},
        )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :company_id, :role_id, 'Gestor Test', :email, 'active')"
            ),
            {
                "id": str(gestor_id),
                "company_id": str(tenant["company_id"]),
                "role_id": str(tenant["basic_role_id"]),
                "email": f"gestor-{gestor_id}@example.com",
            },
        )

    token = make_token(
        tenant["private_pem"],
        sub=str(gestor_id),
        company_id=str(tenant["company_id"]),
        role_id=str(tenant["basic_role_id"]),
    )
    response = client.post(
        f"/api/v1/identity/users/{tenant['admin_user_id']}/deactivate",
        headers=_headers(token),
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "LAST_ADMIN_SAFEGUARD"


def test_nadie_cambia_su_propio_rol(client: TestClient, tenant: dict) -> None:
    """Antes, el último admin cambiándose el rol llegaba a
    `LAST_ADMIN_SAFEGUARD`. Desde F3-02 (27/09/2026) nadie cambia su propio
    rol —ni el último admin ni nadie—, así que la respuesta es otra y llega
    antes: el cambio de rol lo decide siempre otra persona."""
    response = client.patch(
        f"/api/v1/identity/users/{tenant['admin_user_id']}/role",
        headers=_headers(tenant["admin_token"]),
        json={"role_id": str(tenant["basic_role_id"])},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "CANNOT_CHANGE_OWN_ROLE"


def test_remove_admin_permission_from_only_admin_role_is_blocked(
    client: TestClient, tenant: dict
) -> None:
    get_resp = client.get(
        f"/api/v1/identity/roles/{tenant['admin_role_id']}/permissions",
        headers=_headers(tenant["admin_token"]),
    )
    assert get_resp.status_code == 200
    codes = [c for c in get_resp.json() if c != "identity.manage_roles"]

    put_resp = client.put(
        f"/api/v1/identity/roles/{tenant['admin_role_id']}/permissions",
        headers=_headers(tenant["admin_token"]),
        json={"permission_codes": codes},
    )
    assert put_resp.status_code == 409
    assert put_resp.json()["code"] == "LAST_ADMIN_SAFEGUARD"


def test_create_and_clone_role(client: TestClient, tenant: dict) -> None:
    response = client.post(
        "/api/v1/identity/roles",
        headers=_headers(tenant["admin_token"]),
        json={
            "name": "Bodega clonado",
            "clone_from_role_id": str(tenant["basic_role_id"]),
        },
    )
    assert response.status_code == 201, response.text
    new_role_id = response.json()["id"]

    perms_resp = client.get(
        f"/api/v1/identity/roles/{new_role_id}/permissions",
        headers=_headers(tenant["admin_token"]),
    )
    assert perms_resp.status_code == 200
    assert perms_resp.json() == ["inventory.view"]


def test_no_puedes_desactivarte_a_ti_mismo(client: TestClient, tenant: dict) -> None:
    """La UI ya oculta el botón, pero ocultar no es proteger.

    Sin este guard un admin que no fuera el último podía dejarse fuera de su
    propia empresa con un request a mano, y la única salida sería que otro lo
    reactivara. Encontrado auditando los flujos de identidad (04/09/2026).
    """
    response = client.post(
        f"/api/v1/identity/users/{tenant['admin_user_id']}/deactivate",
        headers=_headers(tenant["admin_token"]),
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "CANNOT_DEACTIVATE_SELF"


async def _crear_invitado(tenant: dict) -> UUID:
    invited_user_id = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :company_id, :role_id, 'Invitado Test', :email, 'invited')"
            ),
            {
                "id": str(invited_user_id),
                "company_id": str(tenant["company_id"]),
                "role_id": str(tenant["admin_role_id"]),
                "email": f"invitado-{invited_user_id}@example.com",
            },
        )
    return invited_user_id


async def _estado(user_id: UUID) -> str:
    async with AsyncSessionLocal() as session, session.begin():
        return str(
            (
                await session.execute(
                    text("select status from public.app_user where id = :id"),
                    {"id": str(user_id)},
                )
            ).scalar_one()
        )


async def test_abrir_el_enlace_NO_activa_al_invitado(
    client: TestClient,
    tenant: dict,
    rsa_keypair: tuple[str, object],
) -> None:
    """Abrir la invitación no prueba que exista ninguna contraseña.

    BUG REAL (04/09/2026): el usuario pasaba a `active` con cualquier JWT
    válido, y la sesión que produce el enlace YA es válida antes de que la
    persona elija su clave. Comprobado contra el proyecto dev: canjear el
    enlace y hacer un solo request dejaba al usuario en `active` sin
    contraseña — y después no podía entrar. El admin veía "Activo" en la
    lista, todo en orden, mientras esa persona estaba bloqueada para siempre.

    `amr` distingue los dos casos: `otp` para una sesión de enlace,
    `password` para un login de verdad.
    """
    invited_user_id = await _crear_invitado(tenant)
    token = make_token(
        tenant["private_pem"],
        sub=str(invited_user_id),
        company_id=str(tenant["company_id"]),
        role_id=str(tenant["admin_role_id"]),
        amr=[{"method": "otp", "timestamp": 1788496665}],
    )

    # Se le deja pasar: esa sesión es la que necesita para poner su clave.
    assert client.get("/api/v1/identity/users", headers=_headers(token)).status_code == 200
    assert await _estado(invited_user_id) == "invited"


async def test_invited_user_activates_on_first_login(
    client: TestClient,
    tenant: dict,
    monkeypatch: pytest.MonkeyPatch,
    rsa_keypair: tuple[str, object],
) -> None:
    """Entrar con su propia contraseña sí lo activa — que es lo que `active`
    debe significar para el admin: esta persona ya puede entrar sola."""
    private_pem = tenant["private_pem"]
    invited_user_id = uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :company_id, :role_id, 'Invitado Test', :email, 'invited')"
            ),
            {
                "id": str(invited_user_id),
                "company_id": str(tenant["company_id"]),
                "role_id": str(tenant["admin_role_id"]),
                "email": f"invitado-{invited_user_id}@example.com",
            },
        )

    token = make_token(
        private_pem,
        sub=str(invited_user_id),
        company_id=str(tenant["company_id"]),
        role_id=str(tenant["admin_role_id"]),
        amr=[{"method": "password", "timestamp": 1788496531}],
    )
    response = client.get("/api/v1/identity/users", headers=_headers(token))
    assert response.status_code == 200

    async with AsyncSessionLocal() as session, session.begin():
        status_after = (
            await session.execute(
                text("select status from public.app_user where id = :id"),
                {"id": str(invited_user_id)},
            )
        ).scalar_one()
    assert status_after == "active"


# --------------------------------------------------------------------------
# Concurrencia (auditoría 27/09/2026, F3-07 / B08)
# --------------------------------------------------------------------------
async def _segundo_admin(tenant: dict) -> tuple[UUID, str]:
    admin2 = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :company_id, :role_id, 'Admin Dos', :email, 'active')"
            ),
            {
                "id": str(admin2),
                "company_id": str(tenant["company_id"]),
                "role_id": str(tenant["admin_role_id"]),
                "email": f"admin2-{admin2}@example.com",
            },
        )
    token = make_token(
        tenant["private_pem"],
        sub=str(admin2),
        company_id=str(tenant["company_id"]),
        role_id=str(tenant["admin_role_id"]),
    )
    return admin2, token


async def _admins_activos(company_id: UUID) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(
                    text(
                        "select count(*) from public.app_user "
                        "where company_id = :cid and status = 'active'"
                    ),
                    {"cid": str(company_id)},
                )
            ).scalar_one()
        )


async def test_F3_07_dos_admins_desactivandose_entre_si_no_dejan_cero(tenant: dict) -> None:
    """Antes: 204 y 204 — cada uno contaba al otro como "el admin que queda"
    y la empresa quedaba sin administradores. Con el candado por empresa el
    segundo cuenta después del primero y recibe `LAST_ADMIN_SAFEGUARD`."""
    admin2, token2 = await _segundo_admin(tenant)
    respuestas = await en_paralelo(
        [
            Peticion(
                "POST",
                f"/api/v1/identity/users/{admin2}/deactivate",
                token=tenant["admin_token"],
            ),
            Peticion(
                "POST",
                f"/api/v1/identity/users/{tenant['admin_user_id']}/deactivate",
                token=token2,
            ),
        ]
    )
    assert sorted(r.status_code for r in respuestas) == [204, 409], [r.text for r in respuestas]
    rechazo = next(r for r in respuestas if r.status_code == 409)
    assert rechazo.json()["code"] == "LAST_ADMIN_SAFEGUARD"
    assert await _admins_activos(tenant["company_id"]) == 1


async def test_F3_07_desactivar_y_degradar_a_la_vez_no_dejan_cero(tenant: dict) -> None:
    """La misma carrera por el otro camino: uno desactiva al otro mientras
    éste le cambia el rol al primero a uno sin `identity.manage_roles`."""
    admin2, token2 = await _segundo_admin(tenant)
    respuestas = await en_paralelo(
        [
            Peticion(
                "POST",
                f"/api/v1/identity/users/{admin2}/deactivate",
                token=tenant["admin_token"],
            ),
            Peticion(
                "PATCH",
                f"/api/v1/identity/users/{tenant['admin_user_id']}/role",
                token=token2,
                json={"role_id": str(tenant["basic_role_id"])},
            ),
        ]
    )
    codigos = sorted(r.status_code for r in respuestas)
    assert codigos in ([200, 409], [204, 409]), [r.text for r in respuestas]
    assert next(r for r in respuestas if r.status_code == 409).json()["code"] == (
        "LAST_ADMIN_SAFEGUARD"
    )
    async with AsyncSessionLocal() as session:
        admins = (
            await session.execute(
                text(
                    "select count(*) from public.app_user "
                    "where company_id = :cid and status = 'active' and role_id = :rid"
                ),
                {"cid": str(tenant["company_id"]), "rid": str(tenant["admin_role_id"])},
            )
        ).scalar_one()
    assert admins == 1


# --------------------------------------------------------------------------
# Quien gestiona usuarios o roles solo reparte lo que tiene (F3-02, 27/09/2026)
# --------------------------------------------------------------------------
async def _usuario_con_permisos(tenant: dict, nombre: str, codes: list[str]) -> tuple[UUID, str]:
    """Crea un rol con exactamente `codes` y un usuario activo con ese rol."""
    role_id, user_id = uuid4(), uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, :name)"),
            {"id": str(role_id), "cid": str(tenant["company_id"]), "name": nombre},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :rid, id from public.permission where code = any(:codes)"
            ),
            {"rid": str(role_id), "codes": codes},
        )
        await session.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :rid, :name, :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(tenant["company_id"]),
                "rid": str(role_id),
                "name": nombre,
                "email": f"{nombre.lower().replace(' ', '-')}-{user_id}@example.com",
            },
        )
    token = make_token(
        tenant["private_pem"],
        sub=str(user_id),
        company_id=str(tenant["company_id"]),
        role_id=str(role_id),
    )
    return user_id, token


async def _gestor(tenant: dict) -> tuple[UUID, str]:
    return await _usuario_con_permisos(
        tenant, "Gestor", ["identity.manage_users", "inventory.view"]
    )


async def test_gestor_no_puede_cambiarse_su_propio_rol(client: TestClient, tenant: dict) -> None:
    gestor_id, token = await _gestor(tenant)
    response = client.patch(
        f"/api/v1/identity/users/{gestor_id}/role",
        headers=_headers(token),
        json={"role_id": str(tenant["admin_role_id"])},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "CANNOT_CHANGE_OWN_ROLE"


async def test_solo_se_asigna_un_rol_contenido_en_los_permisos_del_actor(
    client: TestClient, tenant: dict
) -> None:
    _, token = await _gestor(tenant)
    otro_id, _ = await _usuario_con_permisos(tenant, "Otro", [])

    hacia_admin = client.patch(
        f"/api/v1/identity/users/{otro_id}/role",
        headers=_headers(token),
        json={"role_id": str(tenant["admin_role_id"])},
    )
    assert hacia_admin.status_code == 403, hacia_admin.text
    body = hacia_admin.json()
    assert body["code"] == "ROLE_EXCEEDS_ACTOR_PERMISSIONS"
    assert "identity.manage_roles" in body["details"]["missing_permissions"]

    # Bodega (solo inventory.view) sí está dentro de lo que el gestor tiene.
    hacia_bodega = client.patch(
        f"/api/v1/identity/users/{otro_id}/role",
        headers=_headers(token),
        json={"role_id": str(tenant["basic_role_id"])},
    )
    assert hacia_bodega.status_code == 200, hacia_bodega.text
    assert hacia_bodega.json()["role_id"] == str(tenant["basic_role_id"])


async def test_no_se_cambia_el_rol_de_alguien_con_mas_permisos_que_el_actor(
    client: TestClient, tenant: dict
) -> None:
    _, token = await _gestor(tenant)
    admin2, _ = await _segundo_admin(tenant)
    response = client.patch(
        f"/api/v1/identity/users/{admin2}/role",
        headers=_headers(token),
        json={"role_id": str(tenant["basic_role_id"])},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "ROLE_EXCEEDS_ACTOR_PERMISSIONS"


async def test_solo_se_invita_con_un_rol_contenido_en_los_permisos_del_actor(
    client: TestClient, tenant: dict, mocked_invite: list[str]
) -> None:
    _, token = await _gestor(tenant)
    response = client.post(
        "/api/v1/identity/invitations",
        headers=_headers(token),
        json={
            "email": "invitado-admin@example.com",
            "full_name": "Invitado",
            "role_id": str(tenant["admin_role_id"]),
            "send_email": False,
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "ROLE_EXCEEDS_ACTOR_PERMISSIONS"
    assert mocked_invite == []  # no se llegó a crear nada en Supabase Auth


async def test_enlace_de_acceso_solo_para_usuarios_dentro_de_los_permisos_del_actor(
    client: TestClient, tenant: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(email: str) -> str:
        return "https://supabase.test/verify?token=recovery-fake"

    monkeypatch.setattr(identity_auth_admin, "generate_recovery_link", _fake)
    _, token = await _gestor(tenant)
    response = client.post(
        f"/api/v1/identity/users/{tenant['admin_user_id']}/recovery-link",
        headers=_headers(token),
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "ROLE_EXCEEDS_ACTOR_PERMISSIONS"

    bodega_id, _ = await _usuario_con_permisos(tenant, "Bodeguero", ["inventory.view"])
    ok = client.post(f"/api/v1/identity/users/{bodega_id}/recovery-link", headers=_headers(token))
    assert ok.status_code == 200, ok.text


async def test_editar_un_rol_no_agrega_permisos_que_el_actor_no_tiene(
    client: TestClient, tenant: dict
) -> None:
    _, token = await _usuario_con_permisos(
        tenant, "Editor de roles", ["identity.manage_roles", "inventory.view"]
    )
    url = f"/api/v1/identity/roles/{tenant['basic_role_id']}/permissions"

    agrega_ajeno = client.put(
        url,
        headers=_headers(token),
        json={"permission_codes": ["inventory.view", "cashbox.reopen"]},
    )
    assert agrega_ajeno.status_code == 403, agrega_ajeno.text
    assert agrega_ajeno.json()["code"] == "ROLE_EXCEEDS_ACTOR_PERMISSIONS"
    assert agrega_ajeno.json()["details"]["missing_permissions"] == ["cashbox.reopen"]

    # Quitar sí se puede, y agregar lo que el actor tiene también.
    quita = client.put(url, headers=_headers(token), json={"permission_codes": []})
    assert quita.status_code == 200, quita.text
    agrega_propio = client.put(
        url, headers=_headers(token), json={"permission_codes": ["identity.manage_roles"]}
    )
    assert agrega_propio.status_code == 200, agrega_propio.text


async def test_clonar_un_rol_exige_tener_sus_permisos(client: TestClient, tenant: dict) -> None:
    _, token = await _usuario_con_permisos(tenant, "Editor", ["identity.manage_roles"])
    response = client.post(
        "/api/v1/identity/roles",
        headers=_headers(token),
        json={"name": "Copia de Admin", "clone_from_role_id": str(tenant["admin_role_id"])},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "ROLE_EXCEEDS_ACTOR_PERMISSIONS"


async def test_reactivar_a_quien_nunca_completo_su_invitacion_lo_deja_invitado(
    client: TestClient, tenant: dict
) -> None:
    """`active` significa que la persona ya puede entrar con su contraseña.
    Quien fue desactivado antes de completar su invitación vuelve a
    `invited` al reactivarlo, para que el enlace de activación siga
    siendo el camino y la lista no lo muestre como listo para entrar."""
    invitado = await _crear_invitado(tenant)
    headers = _headers(tenant["admin_token"])

    r = client.post(f"/api/v1/identity/users/{invitado}/deactivate", headers=headers)
    assert r.status_code == 204, r.text
    assert await _estado(invitado) == "inactive"

    r = client.post(f"/api/v1/identity/users/{invitado}/reactivate", headers=headers)
    assert r.status_code == 204, r.text
    assert await _estado(invitado) == "invited"


async def test_reactivar_a_un_invitado_no_lo_activa(client: TestClient, tenant: dict) -> None:
    invitado = await _crear_invitado(tenant)

    r = client.post(
        f"/api/v1/identity/users/{invitado}/reactivate",
        headers=_headers(tenant["admin_token"]),
    )
    assert r.status_code == 204, r.text
    assert await _estado(invitado) == "invited"


async def test_reactivar_a_un_usuario_que_ya_entraba_lo_deja_activo(
    client: TestClient, tenant: dict
) -> None:
    invitado = await _crear_invitado(tenant)
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.app_user set status = 'active' where id = :id"),
            {"id": str(invitado)},
        )
    headers = _headers(tenant["admin_token"])

    assert (
        client.post(f"/api/v1/identity/users/{invitado}/deactivate", headers=headers).status_code
        == 204
    )
    assert (
        client.post(f"/api/v1/identity/users/{invitado}/reactivate", headers=headers).status_code
        == 204
    )
    assert await _estado(invitado) == "active"


def _invitar(client: TestClient, tenant: dict, email: str) -> object:
    return client.post(
        "/api/v1/identity/invitations",
        headers=_headers(tenant["admin_token"]),
        json={"email": email, "full_name": "Cupo", "role_id": str(tenant["basic_role_id"])},
    )


async def test_invitaciones_y_enlaces_tienen_tope_por_hora_por_empresa(
    client: TestClient,
    tenant: dict,
    mocked_invite: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "invitations_per_hour", 2)

    async def _fake(email: str) -> str:
        return "https://supabase.test/verify?token=recovery-fake"

    monkeypatch.setattr(identity_auth_admin, "generate_recovery_link", _fake)

    assert _invitar(client, tenant, "cupo1@example.com").status_code == 201
    assert _invitar(client, tenant, "cupo2@example.com").status_code == 201

    tercero = _invitar(client, tenant, "cupo3@example.com")
    assert tercero.status_code == 429, tercero.text
    assert tercero.json()["code"] == "INVITATIONS_RATE_LIMITED"
    retry = tercero.json()["details"]["retry_after_seconds"]
    assert 0 < retry <= 3600
    assert tercero.headers["Retry-After"] == str(retry)
    # Rechazado antes de pedirle nada a Supabase Auth.
    assert mocked_invite == ["cupo1@example.com", "cupo2@example.com"]

    # Los enlaces de acceso cuentan en el mismo cupo.
    invitado = await _crear_invitado(tenant)
    enlace = client.post(
        f"/api/v1/identity/users/{invitado}/recovery-link",
        headers=_headers(tenant["admin_token"]),
    )
    assert enlace.status_code == 429, enlace.text
    assert enlace.json()["code"] == "INVITATIONS_RATE_LIMITED"


async def test_invitaciones_tienen_tope_por_dia_por_empresa(
    client: TestClient,
    tenant: dict,
    mocked_invite: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "invitations_per_day", 3)
    # Tres invitaciones de hace unas horas: fuera de la ventana de una hora,
    # dentro de la del día.
    async with AsyncSessionLocal() as session, session.begin():
        for horas in (2, 3, 4):
            await session.execute(
                text(
                    "insert into public.audit_log "
                    "(company_id, user_id, module, action, entity_type, created_at) "
                    "values (:c, :u, 'identity', 'invite_user', 'app_user', "
                    "now() - make_interval(hours => :h))"
                ),
                {"c": str(tenant["company_id"]), "u": str(tenant["admin_user_id"]), "h": horas},
            )

    response = _invitar(client, tenant, "cupo-dia@example.com")
    assert response.status_code == 429, response.text
    assert response.json()["code"] == "INVITATIONS_RATE_LIMITED"
    assert response.json()["details"]["retry_after_seconds"] > 3600
    assert mocked_invite == []


async def test_el_tope_de_invitaciones_no_cuenta_otras_empresas(
    client: TestClient,
    tenant: dict,
    mocked_invite: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "invitations_per_hour", 1)
    otra = await _rows_company_other()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.audit_log "
                "(company_id, module, action, entity_type) "
                "values (:c, 'identity', 'invite_user', 'app_user')"
            ),
            {"c": str(otra)},
        )

    assert _invitar(client, tenant, "cupo-aislado@example.com").status_code == 201


async def _rows_company_other() -> UUID:
    other = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Otra empresa cupo')"),
            {"id": str(other)},
        )
    return other
