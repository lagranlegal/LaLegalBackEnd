"""Integración de platform (paso 3): require_super_admin, create_company_defaults
end-to-end (roles semilla + caja + invitación del primer admin), suspender/
activar, extender suscripción. Requiere Postgres real (se salta si no hay).
"""

import uuid
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
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


@pytest.fixture
def super_admin_token(monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]) -> str:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    return make_token(private_pem, sub=str(uuid4()), app_metadata={"platform_role": "super_admin"})


@pytest.fixture
def tenant_token(monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]) -> str:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    return make_token(private_pem, sub=str(uuid4()), company_id=str(uuid4()), role_id=str(uuid4()))


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


async def _cleanup_company(company_id: uuid.UUID) -> None:
    # audit_log es inmutable (trigger forbid_change) y no tiene FK hacia
    # company/role — se deja huérfano a propósito, no bloquea el resto del
    # cleanup.
    async with AsyncSessionLocal() as session, session.begin():
        # subscription_event referencia subscription y company: se borra antes
        # que ambas.
        await session.execute(
            text("delete from public.subscription_event where company_id = :id"),
            {"id": str(company_id)},
        )
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
            text("delete from public.account where company_id = :id"), {"id": str(company_id)}
        )
        await session.execute(
            text("delete from public.cash_register where company_id = :id"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.subscription where company_id = :id"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.company where id = :id"), {"id": str(company_id)}
        )


@pytest_asyncio.fixture
async def created_company(
    client: TestClient, mocked_invite: list[str], super_admin_token: str
) -> AsyncGenerator[dict, None]:
    response = client.post(
        "/api/v1/platform/companies",
        headers={"Authorization": f"Bearer {super_admin_token}"},
        json={
            "name": "Empresa integration-test",
            "plan_code": "full",
            "subscription_expires_at": "2099-01-01",
            "first_admin_email": "admin-integration-test@example.com",
            "first_admin_full_name": "Admin Integration Test",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    yield body
    await _cleanup_company(uuid.UUID(body["id"]))


def test_require_super_admin_rejects_no_token(client: TestClient) -> None:
    response = client.get("/api/v1/platform/companies")
    assert response.status_code == 401


def test_require_super_admin_rejects_tenant_token(client: TestClient, tenant_token: str) -> None:
    response = client.get(
        "/api/v1/platform/companies", headers={"Authorization": f"Bearer {tenant_token}"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_require_super_admin_accepts_platform_claim(
    client: TestClient, super_admin_token: str
) -> None:
    response = client.get(
        "/api/v1/platform/companies", headers={"Authorization": f"Bearer {super_admin_token}"}
    )
    assert response.status_code == 200
    assert "items" in response.json()


async def test_create_company_defaults_creates_seed_roles_and_cash_register(
    created_company: dict, mocked_invite: list[str]
) -> None:
    company_id = uuid.UUID(created_company["id"])
    assert created_company["status"] == "active"
    assert mocked_invite == ["admin-integration-test@example.com"]

    async with AsyncSessionLocal() as session, session.begin():
        roles = (
            await session.execute(
                text("select name, is_seed from public.role where company_id = :id order by name"),
                {"id": str(company_id)},
            )
        ).all()
        assert {(r[0], r[1]) for r in roles} == {
            ("Admin", True),
            ("Asesor", True),
            ("Bodega", True),
            ("Moderador", True),
        }

        admin_role_id = (
            await session.execute(
                text("select id from public.role where company_id = :id and name = 'Admin'"),
                {"id": str(company_id)},
            )
        ).scalar_one()
        admin_permission_count = (
            await session.execute(
                text("select count(*) from public.role_permission where role_id = :role_id"),
                {"role_id": str(admin_role_id)},
            )
        ).scalar_one()
        permission_catalog_count = (
            await session.execute(text("select count(*) from public.permission"))
        ).scalar_one()
        assert admin_permission_count == permission_catalog_count

        register_count = (
            await session.execute(
                text("select count(*) from public.cash_register where company_id = :id"),
                {"id": str(company_id)},
            )
        ).scalar_one()
        assert register_count == 1

        # Una empresa sin cuenta de efectivo no puede registrar un solo cobro:
        # desde 00027 `cash_movement.account_id` es NOT NULL. Se verifica acá
        # junto al resto del alta porque el hueco original fue exactamente
        # este — el alta creaba la caja pero no las cuentas.
        #
        # SOLO la de efectivo, a propósito. Antes se sembraban también
        # "Transferencias" y "Otros medios", que eran un artefacto de la
        # migración 00024: existían para mapear el enum viejo de medios de pago
        # al catálogo de cuentas y no perder el histórico de las empresas que
        # ya estaban. Una empresa nueva no tiene historia que mapear, y el
        # módulo de cuentas existe para responder DÓNDE está la plata — cosa
        # que un nombre como "Transferencias" no hace. Las bancarias las crea
        # el dueño con el nombre de su banco.
        accounts = (
            await session.execute(
                text(
                    "select name, type, is_default from public.account "
                    "where company_id = :id order by name"
                ),
                {"id": str(company_id)},
            )
        ).all()
        assert [(a[0], a[1], a[2]) for a in accounts] == [("Caja principal", "cash", True)]

        invited_user = (
            await session.execute(
                text("select status, role_id from public.app_user where company_id = :id"),
                {"id": str(company_id)},
            )
        ).first()
        assert invited_user is not None
        assert invited_user[0] == "invited"
        assert invited_user[1] == admin_role_id

        audit_action = (
            await session.execute(
                text(
                    "select action from public.audit_log "
                    "where company_id = :id and entity_type = 'company'"
                ),
                {"id": str(company_id)},
            )
        ).scalar_one()
        assert audit_action == "create_company"


def test_suspend_and_activate_company(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    suspend_resp = client.post(f"/api/v1/platform/companies/{company_id}/suspend", headers=headers)
    assert suspend_resp.status_code == 200
    assert suspend_resp.json()["status"] == "suspended"

    activate_resp = client.post(
        f"/api/v1/platform/companies/{company_id}/activate", headers=headers
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["status"] == "active"


def test_created_company_includes_plan_and_subscription_expiry(created_company: dict) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md #4/#14: el panel de plataforma
    necesita ver el plan y la fecha de expiración sin un segundo request."""
    assert created_company["plan_code"] == "full"
    assert created_company["plan_name"] == "Completo"
    assert created_company["subscription_expires_at"] == "2099-01-01"


def test_get_and_list_companies_include_plan_and_subscription(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    detail = client.get(f"/api/v1/platform/companies/{company_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["plan_code"] == "full"

    # Se pagina hasta encontrarla en vez de asumir que cae en la primera
    # página: `GET /platform/companies` ordena por `id` (UUID aleatorio) y
    # devuelve 50 por defecto, así que en una BD con varias empresas la recién
    # creada aparece en cualquier página. Asumirlo hacía fallar este test con
    # `StopIteration` en cuanto la BD de pruebas acumulaba empresas.
    row = None
    cursor = None
    for _ in range(50):  # tope defensivo, no debería hacer falta
        params = {"limit": 200, **({"cursor": cursor} if cursor else {})}
        listing = client.get("/api/v1/platform/companies", headers=headers, params=params)
        assert listing.status_code == 200
        page = listing.json()
        row = next((c for c in page["items"] if c["id"] == company_id), None)
        if row is not None or not page.get("next_cursor"):
            break
        cursor = page["next_cursor"]

    assert row is not None, "la empresa creada no apareció en ninguna página del listado"
    assert row["plan_code"] == "full"
    assert row["subscription_expires_at"] == "2099-01-01"


def test_list_plans_includes_modules(client: TestClient, super_admin_token: str) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md #14: PlanOut no exponía `modules`
    aunque la columna ya existe con datos reales en `plan`."""
    response = client.get(
        "/api/v1/platform/plans", headers={"Authorization": f"Bearer {super_admin_token}"}
    )
    assert response.status_code == 200
    full_plan = next(p for p in response.json() if p["code"] == "full")
    assert full_plan["modules"] == {"pawn": True, "store": True}


def test_extend_subscription(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    response = client.post(
        f"/api/v1/platform/companies/{company_id}/subscription/extend",
        headers=headers,
        json={"new_expires_at": "2099-12-31", "notes": "prueba de integración"},
    )
    assert response.status_code == 204


# ---- Historial comercial de la suscripción (docs/PENDIENTES_BACKEND_INFRA.md
# #14: la fila de `subscription` se sobrescribe en cada extensión y el
# `audit_log` es tenant-scoped, así que el rastro existía pero era inalcanzable
# y perdía las notas de cada renovación).


def _events(client: TestClient, token: str, company_id: str) -> list[dict]:
    response = client.get(
        f"/api/v1/platform/companies/{company_id}/subscription/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


def test_company_creation_records_first_event(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    """Sin el evento de alta, una empresa que nunca renovó tendría historial
    vacío y no se distinguiría de una a la que se le perdieron los eventos."""
    events = _events(client, super_admin_token, created_company["id"])
    assert [e["event_type"] for e in events] == ["created"]
    assert events[0]["new_expires_at"] == "2099-01-01"


def test_extension_records_amount_and_notes(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    """Las `notes` de cada extensión se perdían: la fila de `subscription` las
    sobrescribe y el `audit_log` solo copia `expires_at`."""
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    client.post(
        f"/api/v1/platform/companies/{company_id}/subscription/extend",
        headers=headers,
        json={
            "new_expires_at": "2099-06-30",
            "notes": "pagó por transferencia",
            "amount": "150000.00",
        },
    )

    events = _events(client, super_admin_token, company_id)
    assert [e["event_type"] for e in events] == ["extended", "created"]  # más reciente primero
    extended = events[0]
    assert extended["previous_expires_at"] == "2099-01-01"
    assert extended["new_expires_at"] == "2099-06-30"
    assert extended["amount"] == "150000.00"
    assert extended["notes"] == "pagó por transferencia"


def test_extension_without_amount_is_valid(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    """El cobro es manual y fuera del sistema: registrar el monto es una
    conveniencia, no un requisito."""
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    response = client.post(
        f"/api/v1/platform/companies/{company_id}/subscription/extend",
        headers=headers,
        json={"new_expires_at": "2099-07-31"},
    )
    assert response.status_code == 204

    assert _events(client, super_admin_token, company_id)[0]["amount"] is None


def test_suspend_and_activate_are_recorded_without_dates(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    """Suspender no mueve el vencimiento — así el historial distingue "renovó
    hasta X" de "le cortaron el acceso"."""
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    client.post(f"/api/v1/platform/companies/{company_id}/suspend", headers=headers)
    client.post(f"/api/v1/platform/companies/{company_id}/activate", headers=headers)

    events = _events(client, super_admin_token, company_id)
    assert [e["event_type"] for e in events] == ["activated", "suspended", "created"]
    for event in events[:2]:
        assert event["previous_expires_at"] is None
        assert event["new_expires_at"] is None


def test_subscription_events_require_super_admin(client: TestClient, created_company: dict) -> None:
    response = client.get(f"/api/v1/platform/companies/{created_company['id']}/subscription/events")
    assert response.status_code == 401


def test_subscription_events_for_unknown_company_is_404(
    client: TestClient, super_admin_token: str
) -> None:
    response = client.get(
        f"/api/v1/platform/companies/{uuid4()}/subscription/events",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 404


async def _insert_audit_row(*, company_id: uuid.UUID, action: str) -> uuid.UUID:
    row_id = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.audit_log (id, company_id, module, action, entity_type) "
                "values (:id, :cid, 'identity', :action, 'role')"
            ),
            {"id": str(row_id), "cid": str(company_id), "action": action},
        )
    return row_id


def test_company_audit_log_requires_super_admin(
    client: TestClient, created_company: dict, tenant_token: str
) -> None:
    # `tenant_token` no trae claim de plataforma — mismo caso que ya cubre
    # `test_require_super_admin_rejects_tenant_token` para otras rutas.
    response = client.get(
        f"/api/v1/platform/companies/{created_company['id']}/audit-log",
        headers={"Authorization": f"Bearer {tenant_token}"},
    )
    assert response.status_code == 403


def test_company_audit_log_for_unknown_company_is_404(
    client: TestClient, super_admin_token: str
) -> None:
    response = client.get(
        f"/api/v1/platform/companies/{uuid4()}/audit-log",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_company_audit_log_lets_super_admin_read_any_company_and_stays_scoped(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md: `audit_log` tiene RLS forzado, así
    que un super-admin con la sesión normal (tenant) nunca podía ver el de
    una empresa que no es la suya — el histórico COMERCIAL de suscripciones
    ya se resolvió aparte; este es el de SEGURIDAD (roles, remates,
    anulaciones)."""
    company_id = uuid.UUID(created_company["id"])
    other_company_id = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Otra empresa — audit test')"),
            {"id": str(other_company_id)},
        )
    try:
        mine_id = await _insert_audit_row(company_id=company_id, action="update_role_permissions")
        other_id = await _insert_audit_row(
            company_id=other_company_id, action="update_role_permissions"
        )

        response = client.get(
            f"/api/v1/platform/companies/{company_id}/audit-log",
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        assert response.status_code == 200, response.text
        ids = [item["id"] for item in response.json()["items"]]
        assert str(mine_id) in ids
        assert str(other_id) not in ids, "no debe filtrar auditoría de otra empresa"
    finally:
        # audit_log es inmutable (trigger forbid_change bloquea también
        # DELETE, no solo UPDATE) y no tiene FK hacia company — se deja
        # huérfano a propósito, mismo criterio que ya usa `_cleanup_company`.
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(
                text("delete from public.company where id = :cid"), {"cid": str(other_company_id)}
            )


@pytest.mark.asyncio
def test_crear_empresa_devuelve_el_enlace_del_primer_admin(
    client: TestClient, super_admin_token: str, mocked_invite: list[str]
) -> None:
    """El alta era el ÚNICO camino que dependía sí o sí del correo de Supabase.

    Invitaba al primer admin con `send_email=True` y tiraba el enlace a la
    basura. Si ese correo no llegaba —cuota agotada, spam, o un escáner que lo
    quemó antes de que lo abrieran— el cliente nuevo se quedaba con una empresa
    creada y sin forma de entrar, y nadie podía rescatarlo: para generarle otro
    enlace hay que estar dentro de esa empresa, y él era el único que iba a
    poder estarlo.

    Cerrado el 04/09/2026, cuando se vio que las plantillas de correo de
    Supabase no se podían modificar en el plan actual del proyecto.
    """
    response = client.post(
        "/api/v1/platform/companies",
        headers={"Authorization": f"Bearer {super_admin_token}"},
        json={
            "name": "Compraventa Sin Correo",
            "plan_code": "full",
            "subscription_expires_at": "2027-01-01",
            "first_admin_email": "primer-admin@example.com",
            "first_admin_full_name": "Primer Admin",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # El fake devuelve enlace SOLO cuando `send_email=False`, igual que el
    # real: que venga uno prueba las dos cosas a la vez — que no se mandó
    # correo, y que el enlace llega a quien está dando de alta al cliente.
    assert body["admin_invite_link"], (
        "sin el enlace, el primer admin depende de un correo que puede no llegar"
    )
    assert mocked_invite == ["primer-admin@example.com"]


async def test_onboarding_completo_de_una_empresa_nueva(
    client: TestClient,
    created_company: dict,
    mocked_invite: list[str],
    monkeypatch: pytest.MonkeyPatch,
    rsa_keypair: tuple[str, object],
) -> None:
    """El camino que recorre TODO cliente nuevo, de punta a punta.

    Existe por lo que costó descubrir el bug del `redirect_to`: la invitación
    del alta de empresa estuvo rota al 100% —el admin entraba sin poner
    contraseña y después no podía volver— mientras el resto de la app se veía
    perfecto. Nadie lo detectó porque cada pieza estaba probada por separado y
    **nada probaba la cadena completa**, que es justamente el primer contacto
    de cada cliente con el producto.

    Lo que Supabase Auth hace (el correo, el token, la contraseña) no se puede
    probar acá. Lo que SÍ es nuestro y se prueba: que el admin quede creado con
    el rol correcto, que su primer request lo active, que tenga todos los
    permisos, y que desde ahí pueda operar la empresa — invitar y rescatar a
    alguien sin depender del correo.
    """
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    company_id = uuid.UUID(created_company["id"])

    async with AsyncSessionLocal() as session:
        fila = (
            await session.execute(
                text(
                    "select u.id, u.status, r.name as role_name "
                    "from public.app_user u join public.role r on r.id = u.role_id "
                    "where u.company_id = :cid"
                ),
                {"cid": str(company_id)},
            )
        ).first()

    assert fila is not None, "el alta tiene que dejar al primer admin creado"
    admin_id, estado_inicial, rol = fila
    # Nace `invited`: existe en la BD pero todavía no ha entrado nunca.
    assert estado_inicial == "invited"
    assert rol == "Admin"

    role_id = await _role_id_de(company_id, "Admin")
    # `amr: password` porque el front, apenas la persona guarda su contraseña
    # en `/auth/callback`, entra con ella (`useSetPassword`). La distinción
    # importa: con la sesión del ENLACE (`amr: otp`) el usuario NO se activa,
    # justamente porque abrir un enlace no prueba que exista una contraseña.
    token = make_token(
        private_pem,
        sub=str(admin_id),
        company_id=str(company_id),
        role_id=str(role_id),
        amr=[{"method": "password", "timestamp": 1788496531}],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # PRIMER REQUEST — es lo que hace el front justo después del callback.
    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200, me.text
    cuerpo = me.json()
    assert cuerpo["company"]["id"] == str(company_id)
    assert cuerpo["role"]["name"] == "Admin"
    # Un Admin tiene TODO: si el alta le diera menos, el cliente nuevo se
    # encontraría con módulos que no puede abrir en su primer minuto de uso.
    assert "identity.manage_users" in cuerpo["permissions"]
    assert "cashbox.open_close" in cuerpo["permissions"]

    async with AsyncSessionLocal() as session:
        estado_final = (
            await session.execute(
                text("select status from public.app_user where id = :id"), {"id": str(admin_id)}
            )
        ).scalar_one()
    assert estado_final == "active", "entrar con su propia contraseña lo activa (invited -> active)"

    # Y desde ahí YA PUEDE OPERAR: invitar a alguien sin depender del correo.
    invitacion = client.post(
        "/api/v1/identity/invitations",
        headers=headers,
        json={
            "email": "empleado@example.com",
            "full_name": "Empleado Nuevo",
            "role_id": str(await _role_id_de(company_id, "Asesor")),
            "send_email": False,
        },
    )
    assert invitacion.status_code == 201, invitacion.text
    assert invitacion.json()["invite_link"], "sin correo, el enlace es la única entrega posible"

    # Y puede RESCATAR a alguien que olvidó su contraseña, también sin correo.
    # Sin esto, un olvido dejaba a esa persona afuera y nadie podía ayudarla:
    # era el único hueco funcional que quedaba por no tener correo propio.
    empleado_id = invitacion.json()["id"]
    monkeypatch.setattr(
        identity_auth_admin,
        "generate_recovery_link",
        _fake_recovery_link,
    )
    rescate = client.post(f"/api/v1/identity/users/{empleado_id}/recovery-link", headers=headers)
    assert rescate.status_code == 200, rescate.text
    assert rescate.json()["recovery_link"].startswith("https://")
    assert rescate.json()["email"] == "empleado@example.com"

    # Queda auditado quién lo generó y para quién — el enlace es una
    # credencial, y el audit_log es lo único que queda si después hay que
    # explicar un acceso. El enlace en sí NO se guarda.
    async with AsyncSessionLocal() as session:
        auditoria = (
            await session.execute(
                text(
                    "select action, after from public.audit_log "
                    "where company_id = :cid and action = 'generate_recovery_link'"
                ),
                {"cid": str(company_id)},
            )
        ).first()
    assert auditoria is not None
    assert "link" not in str(auditoria[1]), "la credencial no puede quedar en el log"


async def _fake_recovery_link(email: str) -> str:
    return "https://supabase.test/verify?token=recovery-fake"


async def _role_id_de(company_id: uuid.UUID, nombre: str) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        return uuid.UUID(
            str(
                (
                    await session.execute(
                        text(
                            "select id from public.role where company_id = :cid and name = :nombre"
                        ),
                        {"cid": str(company_id), "nombre": nombre},
                    )
                ).scalar_one()
            )
        )
