"""`GET /api/v1/contracts` — el listado, contra Postgres (issue #10 del front).

Cada ítem trae el cliente (`customer_name`, `customer_document`) desde la
misma consulta.

Los contratos se siembran con `POST /contracts/import` (no exige caja abierta
y acepta cualquier fecha, DOMINIO §2.5); las fechas salen del hoy de la
EMPRESA (`_dates.hoy_empresa`).
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _dates import hoy_empresa
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.modules.platform.service import build_seed_role_permissions


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


Empresa = dict[str, Any]


@pytest_asyncio.fixture
async def empresas(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[Callable[[str], Awaitable[Empresa]], None]:
    """Fábrica de empresas con los roles semilla Admin, Asesor y Bodega (los
    permisos de verdad de `build_seed_role_permissions`) y una categoría de
    nivel 3. Los clientes los pone cada test con `_cliente`."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    creadas: list[UUID] = []

    async def crear(nombre: str) -> Empresa:
        company_id = uuid4()
        creadas.append(company_id)
        category_id = uuid4()
        cats = [uuid4(), uuid4()]
        tokens: dict[str, str] = {}
        async with AsyncSessionLocal() as s, s.begin():
            await s.execute(
                text("insert into public.company (id, name) values (:id, :name)"),
                {"id": str(company_id), "name": nombre},
            )
            codes = set((await s.execute(text("select code from public.permission"))).scalars())
            for rol, permisos in build_seed_role_permissions(codes).items():
                if rol not in ("Admin", "Asesor", "Bodega"):
                    continue
                role_id, user_id = uuid4(), uuid4()
                await s.execute(
                    text("insert into public.role (id, company_id, name) values (:id, :cid, :n)"),
                    {"id": str(role_id), "cid": str(company_id), "n": rol},
                )
                await s.execute(
                    text(
                        "insert into public.role_permission (role_id, permission_id) "
                        "select :rid, id from public.permission where code in :codes"
                    ).bindparams(bindparam("codes", expanding=True)),
                    {"rid": str(role_id), "codes": sorted(permisos)},
                )
                await s.execute(
                    text(
                        "insert into public.app_user (id, company_id, role_id, full_name, "
                        "email, status) values (:id, :cid, :rid, :n, :e, 'active')"
                    ),
                    {
                        "id": str(user_id),
                        "cid": str(company_id),
                        "rid": str(role_id),
                        "n": rol,
                        "e": f"{rol.lower()}-{user_id}@example.com",
                    },
                )
                tokens[rol] = make_token(
                    private_pem,
                    sub=str(user_id),
                    company_id=str(company_id),
                    role_id=str(role_id),
                )
            plan_id = (await s.execute(text("select id from public.plan limit 1"))).scalar_one()
            await s.execute(
                text(
                    "insert into public.subscription (company_id, plan_id, status, expires_at) "
                    "values (:cid, :pid, 'active', current_date + 30)"
                ),
                {"cid": str(company_id), "pid": str(plan_id)},
            )
            for nivel, (cat_id, parent) in enumerate(
                [(cats[0], None), (cats[1], cats[0]), (category_id, cats[1])], start=1
            ):
                await s.execute(
                    text(
                        "insert into public.category (id, company_id, parent_id, level, name, "
                        "code_letter, default_term_months, arrears_window_months) "
                        "values (:id, :cid, :p, :lvl, :n, :letra, 4, 4)"
                    ),
                    {
                        "id": str(cat_id),
                        "cid": str(company_id),
                        "p": str(parent) if parent else None,
                        "lvl": nivel,
                        "n": f"Cat {nivel}",
                        "letra": "JOC"[nivel - 1],
                    },
                )
        return {"company_id": company_id, "category_id": category_id, "tokens": tokens}

    yield crear

    for company_id in creadas:
        for sql in (
            "delete from public.contract_item where company_id = :cid",
            "delete from public.contract where company_id = :cid",
            "delete from public.code_counter where company_id = :cid",
            "delete from public.customer where company_id = :cid",
            "delete from public.category where company_id = :cid and level = 3",
            "delete from public.category where company_id = :cid and level = 2",
            "delete from public.category where company_id = :cid and level = 1",
            "delete from public.app_user where company_id = :cid",
            "delete from public.role_permission where role_id in "
            "(select id from public.role where company_id = :cid)",
            "delete from public.role where company_id = :cid",
            "delete from public.subscription where company_id = :cid",
            "delete from public.company where id = :cid",
        ):
            try:
                async with AsyncSessionLocal() as s, s.begin():
                    await s.execute(text(sql), {"cid": str(company_id)})
            except Exception:
                pass  # audit_log es inmutable: huérfano local a propósito


def _h(token: str, key: str | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if key:
        h["Idempotency-Key"] = key
    return h


async def _cliente(e: Empresa, nombre: str) -> dict[str, str]:
    customer_id, doc = uuid4(), str(uuid4().int)[:10]
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.customer (id, company_id, full_name, doc_type, "
                "doc_number, phone) values (:id, :cid, :n, 'cc', :doc, '3000000000')"
            ),
            {"id": str(customer_id), "cid": str(e["company_id"]), "n": nombre, "doc": doc},
        )
    return {"id": str(customer_id), "name": nombre, "doc": doc}


def _sembrar(client: TestClient, e: Empresa, cliente: dict[str, str], *, ipu: date) -> dict:
    """Un contrato importado con el ancla en `ipu` (inicio = ancla)."""
    code = f"LST-{uuid4().hex[:8]}"
    r = client.post(
        "/api/v1/contracts/import",
        headers=_h(e["tokens"]["Admin"], code),
        json={
            "legacy_code": code,
            "customer_id": cliente["id"],
            "principal": "100000.00",
            "capital_balance": "100000.00",
            "interest_rate_pct": "5",
            "term_months": 4,
            "arrears_window_months": 4,
            "extension_months": 1,
            "start_date": ipu.isoformat(),
            "interest_paid_until": ipu.isoformat(),
            "items": [{"category_id": str(e["category_id"]), "description": "Cadena"}],
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def _todas(client: TestClient, token: str, **params: Any) -> tuple[list[dict], int]:
    """Recorre el listado completo siguiendo `next_cursor`; devuelve los ítems
    en orden y cuántas páginas hicieron falta."""
    items: list[dict] = []
    paginas = 0
    cursor: str | None = None
    while True:
        query = dict(params)
        if cursor:
            query["cursor"] = cursor
        r = client.get("/api/v1/contracts", headers=_h(token), params=query)
        assert r.status_code == 200, r.text
        body = r.json()
        items.extend(body["items"])
        paginas += 1
        cursor = body["next_cursor"]
        if cursor is None:
            return items, paginas
        assert paginas < 50, "el cursor no avanza"


async def test_cada_item_trae_el_nombre_y_documento_del_cliente(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    a = await empresas("Empresa nombres listado")
    maria = await _cliente(a, "María Pérez")
    jose = await _cliente(a, "José Gómez")
    hoy = hoy_empresa()
    de_maria = _sembrar(client, a, maria, ipu=hoy - timedelta(days=5))
    de_jose = _sembrar(client, a, jose, ipu=hoy - timedelta(days=10))

    items, _ = _todas(client, a["tokens"]["Asesor"])
    por_id = {i["id"]: i for i in items}
    assert set(por_id) == {de_maria["id"], de_jose["id"]}
    assert por_id[de_maria["id"]]["customer_name"] == "María Pérez"
    assert por_id[de_maria["id"]]["customer_document"] == maria["doc"]
    assert por_id[de_jose["id"]]["customer_name"] == "José Gómez"
    assert por_id[de_jose["id"]]["customer_document"] == jose["doc"]
    # Sigue siendo un `ContractOut` completo: el resto del shape no cambió.
    assert por_id[de_maria["id"]]["customer_id"] == maria["id"]
    assert por_id[de_maria["id"]]["items"][0]["description"] == "Cadena"

    # `?q=` es la misma ruta: también lo trae.
    r = client.get("/api/v1/contracts", headers=_h(a["tokens"]["Asesor"]), params={"q": "mar"})
    assert r.status_code == 200, r.text
    assert [(i["id"], i["customer_name"]) for i in r.json()["items"]] == [
        (de_maria["id"], "María Pérez")
    ]


async def test_el_detalle_no_trae_el_cliente(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    """`customer_name` es del listado (`ContractListItemOut`), no de
    `ContractOut`: el detalle conserva su shape."""
    a = await empresas("Empresa detalle listado")
    c = _sembrar(client, a, await _cliente(a, "Ana Ruiz"), ipu=hoy_empresa())
    r = client.get(f"/api/v1/contracts/{c['id']}", headers=_h(a["tokens"]["Asesor"]))
    assert r.status_code == 200, r.text
    assert "customer_name" not in r.json()


async def test_cada_empresa_ve_solo_sus_contratos_y_sus_clientes(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    a = await empresas("Empresa A listado")
    b = await empresas("Empresa B listado")
    hoy = hoy_empresa()
    de_a = [_sembrar(client, a, await _cliente(a, f"Cliente A{i}"), ipu=hoy) for i in range(3)]
    de_b = [_sembrar(client, b, await _cliente(b, f"Cliente B{i}"), ipu=hoy) for i in range(2)]

    items_a, _ = _todas(client, a["tokens"]["Asesor"], limit=2)
    items_b, _ = _todas(client, b["tokens"]["Asesor"], limit=2)
    assert sorted(i["id"] for i in items_a) == sorted(c["id"] for c in de_a)
    assert sorted(i["id"] for i in items_b) == sorted(c["id"] for c in de_b)
    assert {i["customer_name"] for i in items_a} == {"Cliente A0", "Cliente A1", "Cliente A2"}
    assert {i["customer_name"] for i in items_b} == {"Cliente B0", "Cliente B1"}

    # Buscar el nombre de un cliente ajeno no lo trae.
    r = client.get(
        "/api/v1/contracts", headers=_h(a["tokens"]["Asesor"]), params={"q": "Cliente B"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
