"""Integración de `GET/PATCH /api/v1/company/settings`: la empresa configura
sus propios datos, su logo, su FIRMA (que se estampa en los documentos de
contrato) y los textos de encabezado/pie de los impresos. Requiere el permiso
`company.configure`. Requiere Postgres real (se salta si no hay)."""

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.core import security
from app.core.db import AsyncSessionLocal, engine


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


async def _make_tenant(private_pem: str, *, codes: tuple[str, ...]) -> tuple[dict, str]:
    company_id = uuid4()
    role_id = uuid4()
    user_id = uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.company (id, name, settings) values "
                "(:id, 'Compraventa Config Test', "
                ' \'{"timezone": "America/Bogota", "currency": "COP", "grace_days": 30}\'::jsonb)'
            ),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Admin')"),
            {"id": str(role_id), "cid": str(company_id)},
        )
        if codes:
            await session.execute(
                text(
                    "insert into public.role_permission (role_id, permission_id) "
                    "select :role_id, id from public.permission where code in :codes"
                ).bindparams(bindparam("codes", expanding=True)),
                {"role_id": str(role_id), "codes": list(codes)},
            )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :role_id, 'Admin Test', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "role_id": str(role_id),
                "email": f"admin-{user_id}@example.com",
            },
        )
        plan_id = (
            await session.execute(text("select id from public.plan where code = 'full'"))
        ).scalar_one()
        await session.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :plan_id, 'active', current_date + 30)"
            ),
            {"cid": str(company_id), "plan_id": str(plan_id)},
        )

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )
    return {"company_id": company_id, "user_id": user_id, "token": token}, str(company_id)


async def _cleanup(company_id: str) -> None:
    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": company_id})
        except Exception:
            pass

    await _try_delete("delete from public.audit_log where company_id = :cid")
    await _try_delete("delete from public.app_user where company_id = :cid")
    await _try_delete(
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)"
    )
    await _try_delete("delete from public.role where company_id = :cid")
    await _try_delete("delete from public.subscription where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


@pytest_asyncio.fixture
async def company_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    tenant, company_id = await _make_tenant(private_pem, codes=("company.configure",))
    yield tenant
    await _cleanup(company_id)


@pytest_asyncio.fixture
async def tenant_without_permission(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    tenant, company_id = await _make_tenant(private_pem, codes=("contracts.view",))
    yield tenant
    await _cleanup(company_id)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_get_settings_returns_defaults(client: TestClient, company_tenant: dict) -> None:
    response = client.get("/api/v1/company/settings", headers=_headers(company_tenant["token"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Compraventa Config Test"
    assert body["signature_url"] is None
    assert body["timezone"] == "America/Bogota"
    assert body["currency"] == "COP"
    assert body["documents"] == {"header_note": None, "footer_note": None, "legal_notice": None}


def test_settings_requires_permission(client: TestClient, tenant_without_permission: dict) -> None:
    """Deny-by-default (CLAUDE.md regla 3): sin `company.configure` no se ve ni
    se edita la configuración — incluye la firma, que es la que da validez a
    los documentos impresos."""
    token = tenant_without_permission["token"]
    assert client.get("/api/v1/company/settings", headers=_headers(token)).status_code == 403
    assert (
        client.patch(
            "/api/v1/company/settings", headers=_headers(token), json={"legal_name": "X"}
        ).status_code
        == 403
    )


def test_patch_updates_signature_and_documents(client: TestClient, company_tenant: dict) -> None:
    response = client.patch(
        "/api/v1/company/settings",
        headers=_headers(company_tenant["token"]),
        json={
            "legal_name": "Compraventa El Progreso S.A.S.",
            "tax_id": "900123456-7",
            "signature_url": "company-files/signature.png",
            "documents": {"footer_note": "Gracias por su visita", "legal_notice": "Ley 1581"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["legal_name"] == "Compraventa El Progreso S.A.S."
    assert body["tax_id"] == "900123456-7"
    assert body["signature_url"] == "company-files/signature.png"
    assert body["documents"]["footer_note"] == "Gracias por su visita"
    assert body["documents"]["legal_notice"] == "Ley 1581"
    assert body["documents"]["header_note"] is None


@pytest.mark.asyncio
async def test_patch_does_not_clobber_unsent_settings_keys(
    client: TestClient, company_tenant: dict
) -> None:
    """El bug que este test existe para impedir: `settings` es UN jsonb que
    guarda timezone, currency y grace_days junto a los textos de documentos.
    Guardar un pie de página con un `settings = :nuevo` a ciegas borraría la
    zona horaria — y la zona horaria decide el "hoy" con el que se calculan
    mora, prórrogas y cierres de caja."""
    headers = _headers(company_tenant["token"])
    client.patch(
        "/api/v1/company/settings", headers=headers, json={"documents": {"footer_note": "Pie 1"}}
    )
    client.patch(
        "/api/v1/company/settings", headers=headers, json={"documents": {"header_note": "Cabecera"}}
    )

    body = client.get("/api/v1/company/settings", headers=headers).json()
    assert body["timezone"] == "America/Bogota"
    assert body["currency"] == "COP"
    # El segundo PATCH no borró lo que puso el primero.
    assert body["documents"]["footer_note"] == "Pie 1"
    assert body["documents"]["header_note"] == "Cabecera"

    async with AsyncSessionLocal() as session:
        grace_days = (
            await session.execute(
                text("select settings->>'grace_days' from public.company where id = :cid"),
                {"cid": str(company_tenant["company_id"])},
            )
        ).scalar_one()
    assert int(grace_days) == 30


@pytest.mark.asyncio
async def test_patch_is_audited(client: TestClient, company_tenant: dict) -> None:
    """Cambiar la firma de la empresa altera documentos legales — es una acción
    sensible y CLAUDE.md regla 6 exige auditarla. Se consulta `audit_log`
    directo: el rol de este fixture no tiene `audit.view`."""
    response = client.patch(
        "/api/v1/company/settings",
        headers=_headers(company_tenant["token"]),
        json={"signature_url": "company-files/firma.png"},
    )
    assert response.status_code == 200, response.text

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "select action, entity_type, after from public.audit_log "
                    "where company_id = :cid and module = 'company'"
                ),
                {"cid": str(company_tenant["company_id"])},
            )
        ).one()
    assert row.action == "update_settings"
    assert row.entity_type == "company"
    # Se registran los campos que cambiaron, no su contenido.
    assert row.after == {"changed_fields": ["signature_url"]}


@pytest.mark.asyncio
async def test_tenant_cannot_change_its_own_status(
    client: TestClient, company_tenant: dict
) -> None:
    """Suspender/activar una empresa es del super-admin (módulo `platform`).
    Un campo que no está en el schema se ignora, nunca se escribe."""
    response = client.patch(
        "/api/v1/company/settings",
        headers=_headers(company_tenant["token"]),
        json={"status": "suspended", "legal_name": "Legítimo"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["legal_name"] == "Legítimo"

    async with AsyncSessionLocal() as session:
        status = (
            await session.execute(
                text("select status from public.company where id = :cid"),
                {"cid": str(company_tenant["company_id"])},
            )
        ).scalar_one()
    assert status == "active"
