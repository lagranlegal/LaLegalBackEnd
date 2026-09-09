"""Ningún listado revienta: el barrido que habría cazado el 500 de `/accounts/transfers`.

`GET /api/v1/accounts/transfers` devolvió **500 siempre** desde que se creó
(migración 00032) hasta el 08/09/2026. El endpoint aparecía nueve veces en
`test_accounts.py` y **las nueve eran POST**: ningún test de toda la suite lo
llamaba con GET, así que 325 tests pasaban en verde con un endpoint roto al
100%. Un endpoint puede estar roto y parecer cubierto si lo que se ejercita es
su vecino.

Este test recorre **todos** los GET sin parámetros de ruta que expone la app y
comprueba que ninguno responde 5xx. No valida contenido —para eso están los
tests de cada módulo— sino que la consulta corre: un `AmbiguousParameterError`,
una columna que no existe o un `response_model` imposible caen acá el mismo día
que se escriben, aunque nadie se acuerde de escribirle su test.

Corre con una empresa vacía a propósito: la lista vacía es el caso que más se
olvida, y era justamente el que reventaba.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import security
from app.core.db import AsyncSessionLocal, engine

# Query params obligatorios de algunos listados: sin ellos la respuesta es un
# 422 legítimo y no probaríamos la consulta de verdad.
PARAMS_REQUERIDOS = {
    "/api/v1/reports/income-statement": {"from_date": "2026-01-01", "to_date": "2026-12-31"},
    "/api/v1/reports/profit": {"from_date": "2026-01-01", "to_date": "2026-12-31"},
    "/api/v1/reports/pawn-performance": {"from_date": "2026-01-01", "to_date": "2026-12-31"},
    "/api/v1/company/document-templates": {"document_type": "contract"},
    "/api/v1/company/document-templates/active": {"document_type": "contract"},
}

# Listados que este smoke no cubre y por qué.
FUERA_DE_ALCANCE = {
    "/api/v1/platform/companies",  # super-admin: tiene su propio tenant en test_platform
    "/api/v1/platform/plans",
}


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
async def tenant_con_todo(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[str, None]:
    """Una empresa vacía cuyo rol tiene TODOS los permisos del catálogo.

    Todos, para que ningún listado se salte por un 403 y el barrido de verdad
    llegue a ejecutar cada consulta.
    """
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id, role_id, user_id = uuid4(), uuid4(), uuid4()
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa smoke-test')"),
            {"id": str(company_id)},
        )
        await s.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Todo')"),
            {"id": str(role_id), "cid": str(company_id)},
        )
        await s.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :rid, id from public.permission"
            ),
            {"rid": str(role_id)},
        )
        await s.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :rid, 'Smoke User', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "rid": str(role_id),
                "email": f"smoke-{user_id}@example.com",
            },
        )
        plan_id = (await s.execute(text("select id from public.plan limit 1"))).scalar_one()
        await s.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :pid, 'active', current_date + 30)"
            ),
            {"cid": str(company_id), "pid": str(plan_id)},
        )
        await s.execute(
            text(
                "insert into public.cash_register (company_id, name, active) "
                "values (:cid, 'Principal', true)"
            ),
            {"cid": str(company_id)},
        )

    yield make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )

    async with AsyncSessionLocal() as s, s.begin():
        for tabla in ("app_user", "role_permission", "role", "subscription", "cash_register"):
            col = "role_id" if tabla == "role_permission" else "company_id"
            val = str(role_id) if tabla == "role_permission" else str(company_id)
            await s.execute(text(f"delete from public.{tabla} where {col} = :v"), {"v": val})
        await s.execute(text("delete from public.company where id = :v"), {"v": str(company_id)})


def _listados(client: TestClient) -> list[str]:
    """Todo GET del OpenAPI que no lleve parámetros de ruta."""
    spec = client.get("/openapi.json").json()
    return sorted(
        p
        for p, ops in spec["paths"].items()
        if "get" in ops and "{" not in p and p not in FUERA_DE_ALCANCE and p != "/api/v1/health"
    )


def test_ningun_listado_responde_5xx(client: TestClient, tenant_con_todo: str) -> None:
    rutas = _listados(client)
    assert len(rutas) > 15, f"solo {len(rutas)} listados encontrados — ¿cambió el OpenAPI?"

    rotos = []
    for ruta in rutas:
        r = client.get(
            ruta,
            headers={"Authorization": f"Bearer {tenant_con_todo}"},
            params=PARAMS_REQUERIDOS.get(ruta, {}),
        )
        if r.status_code >= 500:
            rotos.append(f"  GET {ruta} → {r.status_code}  {r.text[:120]}")

    assert not rotos, (
        "Listados que revientan con una empresa vacía. Un 5xx acá casi siempre es\n"
        "la consulta, no el permiso — así estuvo roto `/accounts/transfers` desde\n"
        "00032 sin que nadie lo notara:\n" + "\n".join(rotos)
    )


def test_ningun_listado_devuelve_texto_plano(client: TestClient, tenant_con_todo: str) -> None:
    """Todo error viaja en el envelope `{code, message, details}` (CLAUDE.md regla 7).

    El 500 de `/accounts/transfers` respondía `"Internal Server Error"` en texto
    plano: ni siquiera llegaba al handler que arma el envelope, así que el front
    no tenía ningún `code` que mirar.
    """
    malos = []
    for ruta in _listados(client):
        r = client.get(
            ruta,
            headers={"Authorization": f"Bearer {tenant_con_todo}"},
            params=PARAMS_REQUERIDOS.get(ruta, {}),
        )
        if r.status_code >= 400 and "application/json" not in r.headers.get("content-type", ""):
            malos.append(f"  GET {ruta} → {r.status_code} ({r.headers.get('content-type')})")
    assert not malos, "Respuestas de error que no son JSON:\n" + "\n".join(malos)
