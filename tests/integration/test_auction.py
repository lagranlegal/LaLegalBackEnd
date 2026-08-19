"""Integración de remate asistido (paso 7): contracts -> inventory ->
cashbox. Crea un inventory_item en draft por cada prenda, costo repartido
proporcional a tasación, vínculo bidireccional, contrato y prendas quedan
`auctioned`. Requiere Postgres real (se salta si no hay)."""

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


def _headers(token: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


@pytest_asyncio.fixture
async def auction_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    role_id = uuid4()
    user_id = uuid4()
    customer_id = uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    register_id = uuid4()
    codes = ("contracts.view", "contracts.create", "contracts.auction", "payments.create")

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa auction-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Full')"),
            {"id": str(role_id), "cid": str(company_id)},
        )
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
                "values (:id, :cid, :role_id, 'Full User', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "role_id": str(role_id),
                "email": f"full-{user_id}@example.com",
            },
        )
        plan_id = (await session.execute(text("select id from public.plan limit 1"))).scalar_one()
        await session.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :plan_id, 'active', current_date + 30)"
            ),
            {"cid": str(company_id), "plan_id": str(plan_id)},
        )
        await session.execute(
            text(
                "insert into public.customer "
                "(id, company_id, full_name, doc_type, doc_number, phone) "
                "values (:id, :cid, 'Cliente Test', 'cc', :doc, '3000000000')"
            ),
            {"id": str(customer_id), "cid": str(company_id), "doc": str(uuid4().int)[:10]},
        )
        await session.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, null, 1, 'Joyería', 'J')"
            ),
            {"id": str(cat1), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, :parent, 2, 'Oro', 'O')"
            ),
            {"id": str(cat2), "cid": str(company_id), "parent": str(cat1)},
        )
        await session.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter, "
                " default_term_months, arrears_window_months) "
                "values (:id, :cid, :parent, 3, 'Cadena', 'C', 4, 4)"
            ),
            {"id": str(cat3), "cid": str(company_id), "parent": str(cat2)},
        )
        await session.execute(
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {"id": str(register_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.cash_session "
                "(company_id, register_id, opened_by, opening_balance) "
                "values (:cid, :rid, :cid, 0)"
            ),
            {"cid": str(company_id), "rid": str(register_id)},
        )

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )

    yield {
        "company_id": company_id,
        "customer_id": customer_id,
        "category_id": cat3,
        "token": token,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    await _try_delete("delete from public.inventory_entry_line where company_id = :cid")
    await _try_delete("delete from public.inventory_entry where company_id = :cid")
    await _try_delete("delete from public.inventory_item where company_id = :cid")
    await _try_delete("delete from public.contract_item where company_id = :cid")
    await _try_delete("delete from public.contract where company_id = :cid")
    await _try_delete("delete from public.code_counter where company_id = :cid")
    await _try_delete("delete from public.customer where company_id = :cid")
    await _try_delete("delete from public.category where company_id = :cid and level = 3")
    await _try_delete("delete from public.category where company_id = :cid and level = 2")
    await _try_delete("delete from public.category where company_id = :cid and level = 1")
    await _try_delete("delete from public.app_user where company_id = :cid")
    await _try_delete(
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)"
    )
    await _try_delete("delete from public.role where company_id = :cid")
    await _try_delete("delete from public.subscription where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


async def _backdate_and_expire_extension(*, company_id, contract_id, months: int) -> None:
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "update public.contract "
                "set interest_paid_until = interest_paid_until - make_interval(months => :months) "
                "where company_id = :cid and id = :id"
            ),
            {"months": months, "cid": str(company_id), "id": str(contract_id)},
        )


def test_auction_rejected_when_contract_not_ready(client: TestClient, auction_tenant: dict) -> None:
    headers = _headers(auction_tenant["token"], idempotency_key=str(uuid4()))
    contract = client.post(
        "/api/v1/contracts",
        headers=headers,
        json={
            "customer_id": str(auction_tenant["customer_id"]),
            "principal": "1000000.00",
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [{"category_id": str(auction_tenant["category_id"]), "description": "Cadena"}],
        },
    ).json()

    response = client.post(f"/api/v1/contracts/{contract['id']}/auction", headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "CONTRACT_NOT_READY_FOR_AUCTION"


async def test_auction_splits_cost_proportional_to_appraisal(
    client: TestClient, auction_tenant: dict
) -> None:
    headers = _headers(auction_tenant["token"], idempotency_key=str(uuid4()))
    contract = client.post(
        "/api/v1/contracts",
        headers=headers,
        json={
            "customer_id": str(auction_tenant["customer_id"]),
            "principal": "1000000.00",
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [
                {
                    "category_id": str(auction_tenant["category_id"]),
                    "description": "Cadena grande",
                    "item_appraisal": "600000.00",
                },
                {
                    "category_id": str(auction_tenant["category_id"]),
                    "description": "Anillo pequeño",
                    "item_appraisal": "400000.00",
                },
            ],
        },
    ).json()
    assert len(contract["items"]) == 2

    # 8 meses atrás: ventana de mora 4 + prórroga 1 -> sobra de sobra para
    # que la prórroga ya esté vencida.
    await _backdate_and_expire_extension(
        company_id=auction_tenant["company_id"], contract_id=contract["id"], months=8
    )
    refreshed = client.get(f"/api/v1/contracts/{contract['id']}", headers=headers).json()
    assert refreshed["status"] == "in_extension"

    response = client.post(f"/api/v1/contracts/{contract['id']}/auction", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "auctioned"
    for item in body["items"]:
        assert item["status"] == "auctioned"
        # docs/PENDIENTES_BACKEND_INFRA.md #19: contract_item.inventory_item_id
        # existía en la BD pero no salía en ContractItemOut — sin esto el
        # front no puede ir de "prenda rematada" al artículo específico en
        # el que se convirtió.
        assert item["inventory_item_id"] is not None

    async with AsyncSessionLocal() as session, session.begin():
        inventory_rows = (
            await session.execute(
                text(
                    "select cost from public.inventory_item "
                    "where company_id = :cid and source_contract_id = :contract_id "
                    "order by cost desc"
                ),
                {"cid": str(auction_tenant["company_id"]), "contract_id": contract["id"]},
            )
        ).all()
        linked = (
            await session.execute(
                text(
                    "select inventory_item_id from public.contract_item "
                    "where company_id = :cid and contract_id = :contract_id"
                ),
                {"cid": str(auction_tenant["company_id"]), "contract_id": contract["id"]},
            )
        ).all()
        entry = (
            await session.execute(
                text(
                    "select origin_type, contract_id from public.inventory_entry "
                    "where company_id = :cid and contract_id = :contract_id"
                ),
                {"cid": str(auction_tenant["company_id"]), "contract_id": contract["id"]},
            )
        ).first()

    assert len(inventory_rows) == 2
    higher_cost, lower_cost = float(inventory_rows[0][0]), float(inventory_rows[1][0])
    total_cost = higher_cost + lower_cost
    # 600000:400000 = 60%/40% del total repartido
    assert higher_cost == pytest.approx(total_cost * 0.6, abs=1)
    assert lower_cost == pytest.approx(total_cost * 0.4, abs=1)
    assert all(row[0] is not None for row in linked)
    assert entry is not None
    assert entry[0] == "auction"
    assert {str(row[0]) for row in linked} == {item["inventory_item_id"] for item in body["items"]}
