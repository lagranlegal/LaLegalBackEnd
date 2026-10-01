"""`GET /api/v1/contracts/attention` — «Para hoy» del Inicio, contra Postgres.

Los contratos se siembran con `POST /contracts/import` (el único camino para
sembrar un contrato en cualquier estado, DOMINIO §2.5) y las fechas salen del
hoy de la EMPRESA (`_dates.hoy_empresa`). Cada monto se compara con
`payment-options` del mismo contrato: la tarjeta y el botón de cobro no pueden
decir números distintos.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
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
from app.modules.contracts.rules import add_months
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
    permisos de verdad de `build_seed_role_permissions`), un cliente y una
    categoría de nivel 3."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    creadas: list[UUID] = []

    async def crear(nombre: str) -> Empresa:
        company_id = uuid4()
        creadas.append(company_id)
        customer_id, category_id = uuid4(), uuid4()
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
            await s.execute(
                text(
                    "insert into public.customer (id, company_id, full_name, doc_type, "
                    "doc_number, phone) values (:id, :cid, :n, 'cc', :doc, '3000000000')"
                ),
                {
                    "id": str(customer_id),
                    "cid": str(company_id),
                    "n": f"Cliente {nombre}",
                    "doc": str(uuid4().int)[:10],
                },
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
        return {
            "company_id": company_id,
            "customer_id": customer_id,
            "category_id": category_id,
            "tokens": tokens,
        }

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


def _sembrar(client: TestClient, e: Empresa, *, ipu: date, capital: str, rate: str) -> dict:
    """Un contrato importado con el ancla en `ipu` (inicio = ancla: siempre
    alineado), ventana de mora 4 y prórroga 1."""
    code = f"ATT-{uuid4().hex[:8]}"
    r = client.post(
        "/api/v1/contracts/import",
        headers=_h(e["tokens"]["Admin"], code),
        json={
            "legacy_code": code,
            "customer_id": str(e["customer_id"]),
            "principal": capital,
            "capital_balance": capital,
            "interest_rate_pct": rate,
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


def _ancla_que_vence_hoy(hoy: date) -> date | None:
    """El ancla cuya cuota vence HOY (`ancla + 1 mes == hoy`). No existe en
    todos los días: el 31 de octubre ninguna cuota vence (el 31/09 no
    existe y el 30/09 + 1 mes es el 30/10)."""
    for dias in range(27, 32):
        d = hoy - timedelta(days=dias)
        if add_months(d, 1) == hoy:
            return d
    return None


async def test_para_hoy_cuenta_ordena_y_cobra_lo_mismo_que_payment_options(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    a = await empresas("Empresa A attention")
    hoy = hoy_empresa()
    remate = _sembrar(client, a, ipu=add_months(hoy, -8), capital="1000000.00", rate="5")
    mora_larga = _sembrar(client, a, ipu=hoy - timedelta(days=70), capital="400000.00", rate="4")
    mora_corta = _sembrar(client, a, ipu=hoy - timedelta(days=40), capital="300000.00", rate="5")
    prorroga = _sembrar(client, a, ipu=hoy - timedelta(days=130), capital="500000.00", rate="3")
    al_dia = _sembrar(client, a, ipu=hoy - timedelta(days=5), capital="200000.00", rate="5")
    ancla_hoy = _ancla_que_vence_hoy(hoy)
    vence_hoy = (
        _sembrar(client, a, ipu=ancla_hoy, capital="250000.00", rate="10") if ancla_hoy else None
    )
    # El estado persistido puede ir atrasado (job nocturno): la respuesta usa
    # el EFECTIVO.
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text("update public.contract set status = 'active' where id = :id"),
            {"id": mora_larga["id"]},
        )

    r = client.get("/api/v1/contracts/attention", headers=_h(a["tokens"]["Asesor"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["as_of"] == hoy.isoformat()

    esperado = [remate, mora_larga, mora_corta, prorroga] + ([vence_hoy] if vence_hoy else [])
    assert [i["contract_id"] for i in body["items"]] == [c["id"] for c in esperado]
    assert al_dia["id"] not in {i["contract_id"] for i in body["items"]}
    assert body["items_total"] == len(esperado)
    assert [i["reason_code"] for i in body["items"]] == [
        "ready_for_auction",
        "in_arrears",
        "in_arrears",
        "in_extension",
    ] + (["due_today"] if vence_hoy else [])
    por_id = {i["contract_id"]: i for i in body["items"]}
    assert por_id[mora_larga["id"]]["status"] == "in_arrears"
    assert por_id[mora_larga["id"]]["customer_name"] == "Cliente Empresa A attention"

    admin = _h(a["tokens"]["Admin"])
    opciones = {
        c["id"]: client.get(f"/api/v1/contracts/{c['id']}/payment-options", headers=admin).json()
        for c in esperado
    }

    # Listo para remate: saldar; fecha = fin de la prórroga del contrato.
    detalle_remate = client.get(f"/api/v1/contracts/{remate['id']}", headers=admin).json()
    item = por_id[remate["id"]]
    assert item["reference_date"] == detalle_remate["extension_ends_at"]
    assert Decimal(item["amount_due_today"]) == Decimal(opciones[remate["id"]]["payoff_total"])
    assert body["ready_for_auction"] == {
        "count": 1,
        "earliest_expired_on": detalle_remate["extension_ends_at"],
    }

    # Mora y prórroga: ponerse al día = la última opción de payment-options.
    for c in (mora_larga, mora_corta, prorroga):
        ultima = opciones[c["id"]]["options"][-1]
        assert Decimal(por_id[c["id"]]["amount_due_today"]) == Decimal(ultima["total"])
    assert (
        por_id[mora_larga["id"]]["days_overdue"]
        == (hoy - add_months(hoy - timedelta(days=70), 1)).days
    )
    assert por_id[mora_larga["id"]]["days_overdue"] > por_id[mora_corta["id"]]["days_overdue"]
    detalle_prorroga = client.get(f"/api/v1/contracts/{prorroga['id']}", headers=admin).json()
    assert por_id[prorroga["id"]]["reference_date"] == detalle_prorroga["extension_ends_at"]

    assert body["in_arrears"]["count"] == 2
    assert Decimal(body["in_arrears"]["overdue_interest_total"]) == sum(
        Decimal(opciones[c["id"]]["options"][-1]["total"]) for c in (mora_larga, mora_corta)
    )

    if vence_hoy:
        item = por_id[vence_hoy["id"]]
        un_mes = Decimal(opciones[vence_hoy["id"]]["options"][0]["total"])
        assert item["days_overdue"] == 0
        assert item["reference_date"] == hoy.isoformat()
        assert Decimal(item["amount_due_today"]) == un_mes == Decimal("25000.00")
        assert body["due_today"]["count"] == 1
        assert Decimal(body["due_today"]["amount_total"]) == un_mes
    else:
        assert body["due_today"] == {"count": 0, "amount_total": "0.00"}

    # `limit` topa la lista, no las tarjetas.
    corto = client.get(
        "/api/v1/contracts/attention?limit=2", headers=_h(a["tokens"]["Asesor"])
    ).json()
    assert [i["contract_id"] for i in corto["items"]] == [remate["id"], mora_larga["id"]]
    assert corto["items_total"] == len(esperado)
    assert corto["in_arrears"]["count"] == 2


async def test_el_limite_tiene_tope_de_50(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    a = await empresas("Empresa limite attention")
    r = client.get("/api/v1/contracts/attention?limit=51", headers=_h(a["tokens"]["Asesor"]))
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


async def test_sin_contracts_view_es_403(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    a = await empresas("Empresa permiso attention")
    r = client.get("/api/v1/contracts/attention", headers=_h(a["tokens"]["Bodega"]))
    assert r.status_code == 403
    assert r.json()["code"] == "PERMISSION_DENIED"


async def test_cada_empresa_ve_solo_sus_contratos(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    a = await empresas("Empresa A aislamiento")
    b = await empresas("Empresa B aislamiento")
    hoy = hoy_empresa()
    de_a = _sembrar(client, a, ipu=hoy - timedelta(days=40), capital="100000.00", rate="5")
    de_b = _sembrar(client, b, ipu=hoy - timedelta(days=70), capital="900000.00", rate="5")

    vista_a = client.get("/api/v1/contracts/attention", headers=_h(a["tokens"]["Asesor"])).json()
    vista_b = client.get("/api/v1/contracts/attention", headers=_h(b["tokens"]["Asesor"])).json()
    assert [i["contract_id"] for i in vista_a["items"]] == [de_a["id"]]
    assert [i["contract_id"] for i in vista_b["items"]] == [de_b["id"]]
    assert vista_a["in_arrears"]["count"] == vista_b["in_arrears"]["count"] == 1
    assert Decimal(vista_a["in_arrears"]["overdue_interest_total"]) == Decimal("5000.00")
    assert Decimal(vista_b["in_arrears"]["overdue_interest_total"]) == Decimal("90000.00")
