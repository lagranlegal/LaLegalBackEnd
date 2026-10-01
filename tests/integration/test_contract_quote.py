"""`POST /api/v1/contracts/quote` — la cotización de Nuevo contrato, contra Postgres.

La promesa del endpoint es una sola: crear el contrato después, con el mismo
cuerpo y el mismo día, da EXACTAMENTE los números cotizados. Por eso cada
prueba de cálculo crea el contrato y compara campo por campo contra la
respuesta real de `POST /contracts` y de `payment-options`, no contra cifras
escritas a mano. Las fechas salen del hoy de la EMPRESA (`_dates`).
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
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

QUOTE = "/api/v1/contracts/quote"


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
    """Fábrica de empresas con los roles semilla Admin (tiene
    `contracts.override_ltv`), Asesor (crea contratos, sin override) y Bodega
    (sin `contracts.create`), un cliente, un árbol de categorías con la hoja
    a 4 meses de plazo y 4 de ventana, una hoja de nivel 2 sin plazo, y una
    caja registradora (sin sesión: la abre quien la necesite)."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    creadas: list[UUID] = []

    async def crear(nombre: str) -> Empresa:
        company_id = uuid4()
        creadas.append(company_id)
        customer_id, category_id, register_id = uuid4(), uuid4(), uuid4()
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
                plazo = 4 if nivel == 3 else None
                await s.execute(
                    text(
                        "insert into public.category (id, company_id, parent_id, level, name, "
                        "code_letter, default_term_months, arrears_window_months) "
                        "values (:id, :cid, :p, :lvl, :n, :letra, :plazo, :plazo)"
                    ),
                    {
                        "id": str(cat_id),
                        "cid": str(company_id),
                        "p": str(parent) if parent else None,
                        "lvl": nivel,
                        "n": f"Cat {nivel}",
                        "letra": "JOC"[nivel - 1],
                        "plazo": plazo,
                    },
                )
            await s.execute(
                text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
                {"id": str(register_id), "cid": str(company_id)},
            )
        return {
            "company_id": company_id,
            "customer_id": customer_id,
            "category_id": category_id,
            "level2_category_id": cats[1],
            "register_id": register_id,
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
            "delete from public.cash_session where company_id = :cid",
            "delete from public.cash_register where company_id = :cid",
            "delete from public.company where id = :cid",
        ):
            try:
                async with AsyncSessionLocal() as s, s.begin():
                    await s.execute(text(sql), {"cid": str(company_id)})
            except Exception:
                pass  # cash_movement y audit_log son inmutables: huérfanos locales


def _h(token: str, key: str | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if key:
        h["Idempotency-Key"] = key
    return h


async def _abrir_caja(e: Empresa) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.cash_session "
                "(company_id, register_id, opened_by, opening_balance) "
                "values (:cid, :rid, :cid, 0)"
            ),
            {"cid": str(e["company_id"]), "rid": str(e["register_id"])},
        )


async def _ltv(e: Empresa, pct: int) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "update public.category set max_ltv_pct = :p where id = :id and company_id = :cid"
            ),
            {"p": pct, "id": str(e["category_id"]), "cid": str(e["company_id"])},
        )


def _prestamo(e: Empresa, **campos: object) -> dict[str, Any]:
    """Lo que define el préstamo: el mismo dict va a la cotización y a crear."""
    base: dict[str, Any] = {
        "principal": "1000000.00",
        "interest_rate_pct": "5",
        "items": [{"category_id": str(e["category_id"]), "description": "Cadena de oro 10g"}],
    }
    base.update(campos)
    return base


def _crear(client: TestClient, e: Empresa, rol: str, prestamo: dict[str, Any]) -> Any:
    return client.post(
        "/api/v1/contracts",
        headers=_h(e["tokens"][rol], str(uuid4())),
        json={**prestamo, "customer_id": str(e["customer_id"]), "payment_method": "cash"},
    )


async def _conteos(company_id: UUID) -> dict[str, int]:
    tablas = ("contract", "contract_item", "cash_movement", "audit_log", "code_counter")
    async with AsyncSessionLocal() as s, s.begin():
        return {
            t: (
                await s.execute(
                    text(f"select count(*) from public.{t} where company_id = :cid"),  # noqa: S608
                    {"cid": str(company_id)},
                )
            ).scalar_one()
            for t in tablas
        }


# --------------------------------------------------------------------------
# La cotización es el contrato
# --------------------------------------------------------------------------
async def test_la_cotizacion_coincide_con_el_contrato_creado(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    """Tasa con tres decimales a propósito: la base la guarda `numeric(5,2)`
    (5,555 → 5,56) y el interés del contrato sale de la guardada."""
    e = await empresas("Cotiza")
    await _ltv(e, 70)
    await _abrir_caja(e)
    prestamo = _prestamo(
        e,
        principal="1234567.00",
        interest_rate_pct="5.555",
        appraisal_value="2000000.00",
        extension_months=2,
        extension_window_days=10,
    )

    q = client.post(QUOTE, headers=_h(e["tokens"]["Asesor"]), json=prestamo)
    assert q.status_code == 200, q.text
    cot = q.json()

    creado = _crear(client, e, "Asesor", prestamo)
    assert creado.status_code == 201, creado.text
    c = creado.json()
    opciones = client.get(
        f"/api/v1/contracts/{c['id']}/payment-options", headers=_h(e["tokens"]["Asesor"])
    ).json()

    hoy = hoy_empresa()
    assert cot["start_date"] == c["start_date"] == hoy.isoformat()
    assert cot["interest_rate_pct"] == c["interest_rate_pct"] == "5.56"
    assert cot["monthly_interest"] == opciones["monthly_interest"] == "68641.93"
    assert cot["term_months"] == c["term_months"] == 4
    assert cot["arrears_window_months"] == c["arrears_window_months"] == 4
    assert cot["extension_months"] == c["extension_months"] == 2
    assert cot["extension_window_days"] == c["extension_window_days"] == 10
    assert cot["due_date"] == c["due_date"] == add_months(hoy, 4).isoformat()
    # La primera cuota es el ancla del contrato + 1 mes.
    assert cot["first_due_date"] == add_months(hoy, 1).isoformat()
    assert c["interest_paid_until"] == hoy.isoformat()
    assert cot["appraisal_total"] == c["appraisal_value"] == "2000000.00"
    assert cot["amount_to_disburse"] == c["principal"] == "1234567.00"
    # 1.234.567 / 2.000.000 = 61,73 %, bajo el 70 %: sin bandera, como el contrato.
    assert cot["ltv_pct"] == "61.73"
    assert cot["ltv_ceiling"] == "70.00"
    assert cot["max_loan"] == "1400000.00"
    assert cot["ltv_exceeded"] is False
    assert cot["requires_override"] is c["ltv_warning"] is False
    assert cot["override_reason"] is None

    async with AsyncSessionLocal() as s, s.begin():
        salida = (
            await s.execute(
                text(
                    "select amount from public.cash_movement where company_id = :cid "
                    "and reference_type = 'contract' and reference_id = :id"
                ),
                {"cid": str(e["company_id"]), "id": c["id"]},
            )
        ).scalar_one()
    assert str(salida) == cot["amount_to_disburse"]


async def test_sin_ventana_en_el_cuerpo_usa_la_politica_de_la_empresa(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    e = await empresas("Ventana")
    await _abrir_caja(e)
    cot = client.post(QUOTE, headers=_h(e["tokens"]["Asesor"]), json=_prestamo(e)).json()
    c = _crear(client, e, "Asesor", _prestamo(e)).json()
    assert cot["extension_window_days"] == c["extension_window_days"] == 28
    assert cot["extension_months"] == c["extension_months"] == 1


async def test_sobre_el_techo_la_cotizacion_dice_lo_que_hara_crear(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    e = await empresas("Techo")
    await _ltv(e, 70)
    await _abrir_caja(e)
    prestamo = _prestamo(e, principal="1400000.01", appraisal_value="2000000.00")

    for rol in ("Asesor", "Admin"):  # la cotización no depende del permiso
        cot = client.post(QUOTE, headers=_h(e["tokens"][rol]), json=prestamo).json()
        assert cot["ltv_exceeded"] is True
        assert cot["requires_override"] is True
        assert cot["override_reason"] == "ltv_exceeded"
        assert cot["max_loan"] == "1400000.00"
        assert cot["ltv_pct"] == "70.00"  # redondeado para mostrar; decide `ltv_exceeded`

    sin_permiso = _crear(client, e, "Asesor", prestamo)
    assert sin_permiso.status_code == 403, sin_permiso.text
    assert sin_permiso.json()["code"] == "PERMISSION_DENIED"
    con_permiso = _crear(client, e, "Admin", prestamo)
    assert con_permiso.status_code == 201, con_permiso.text
    assert con_permiso.json()["ltv_warning"] is True

    # Justo en el techo no se pasa, ni en la cotización ni al crear.
    en_el_techo = _prestamo(e, principal="1400000.00", appraisal_value="2000000.00")
    cot = client.post(QUOTE, headers=_h(e["tokens"]["Asesor"]), json=en_el_techo).json()
    assert cot["ltv_exceeded"] is False and cot["requires_override"] is False
    creado = _crear(client, e, "Asesor", en_el_techo)
    assert creado.status_code == 201, creado.text
    assert creado.json()["ltv_warning"] is False


async def test_con_ltv_sin_avaluo_exige_el_permiso_como_crear(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    e = await empresas("Sin avalúo")
    await _ltv(e, 70)
    await _abrir_caja(e)
    for avaluo in (None, "0"):
        prestamo = _prestamo(e, appraisal_value=avaluo)
        cot = client.post(QUOTE, headers=_h(e["tokens"]["Asesor"]), json=prestamo).json()
        assert cot["requires_override"] is True
        assert cot["override_reason"] == "appraisal_missing"
        assert cot["ltv_exceeded"] is False
        assert cot["appraisal_total"] is None
        assert cot["max_loan"] is None
        assert cot["ltv_ceiling"] == "70.00"
        rechazo = _crear(client, e, "Asesor", prestamo)
        assert rechazo.status_code == 422, rechazo.text
        assert rechazo.json()["code"] == "CONTRACT_APPRAISAL_REQUIRED"


# --------------------------------------------------------------------------
# Datos parciales: el resumen en vivo no muestra errores mientras se escribe
# --------------------------------------------------------------------------
async def test_un_cuerpo_vacio_responde_200_con_lo_que_se_sabe(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    e = await empresas("Vacío")
    r = client.post(QUOTE, headers=_h(e["tokens"]["Asesor"]), json={})
    assert r.status_code == 200, r.text
    hoy = hoy_empresa()
    assert r.json() == {
        "start_date": hoy.isoformat(),
        "interest_rate_pct": None,
        "monthly_interest": None,
        "term_months": None,
        "arrears_window_months": None,
        "extension_months": 1,
        "extension_window_days": 28,
        "first_due_date": add_months(hoy, 1).isoformat(),
        "due_date": None,
        "appraisal_total": None,
        "ltv_pct": None,
        "ltv_ceiling": None,
        "max_loan": None,
        "ltv_exceeded": False,
        "requires_override": False,
        "override_reason": None,
        "amount_to_disburse": None,
    }


async def test_capital_en_cero_y_prenda_sin_categoria_son_datos_que_faltan(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    """El formulario arranca con capital «0.00» y una prenda vacía: eso no es
    un error, es lo que todavía no se ha escrito."""
    e = await empresas("Parcial")
    r = client.post(
        QUOTE,
        headers=_h(e["tokens"]["Asesor"]),
        json={
            "principal": "0.00",
            "interest_rate_pct": "5",
            "items": [{"category_id": None, "description": ""}],
        },
    )
    assert r.status_code == 200, r.text
    cot = r.json()
    assert cot["amount_to_disburse"] is None
    assert cot["monthly_interest"] is None
    assert cot["interest_rate_pct"] == "5.00"
    assert cot["term_months"] is None and cot["due_date"] is None


async def test_capital_y_tasa_sin_categoria_ya_dan_el_interes(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    e = await empresas("Interés")
    r = client.post(
        QUOTE,
        headers=_h(e["tokens"]["Asesor"]),
        json={"principal": "1000000", "interest_rate_pct": "5", "appraisal_value": "4000000"},
    )
    assert r.status_code == 200, r.text
    cot = r.json()
    assert cot["monthly_interest"] == "50000.00"
    assert cot["amount_to_disburse"] == "1000000.00"
    assert cot["ltv_pct"] == "25.00"  # se informa aunque aún no haya techo
    assert cot["ltv_ceiling"] is None and cot["requires_override"] is False
    assert cot["term_months"] is None


async def test_una_tasa_invalida_es_422_como_al_crear(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    e = await empresas("Tasa")
    r = client.post(QUOTE, headers=_h(e["tokens"]["Asesor"]), json={"interest_rate_pct": "150"})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "VALIDATION_ERROR"


async def test_una_categoria_que_no_es_hoja_se_rechaza_como_al_crear(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    e = await empresas("Nivel 2")
    await _abrir_caja(e)
    prestamo = _prestamo(e, items=[{"category_id": str(e["level2_category_id"])}])
    cot = client.post(QUOTE, headers=_h(e["tokens"]["Asesor"]), json=prestamo)
    crear = _crear(
        client,
        e,
        "Asesor",
        {**prestamo, "items": [{**prestamo["items"][0], "description": "x"}]},
    )
    assert cot.status_code == crear.status_code == 400, cot.text
    assert cot.json()["code"] == crear.json()["code"] == "BAD_REQUEST"


# --------------------------------------------------------------------------
# Permiso, aislamiento, y que no escribe
# --------------------------------------------------------------------------
async def test_sin_contracts_create_es_403(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    e = await empresas("Bodega")
    r = client.post(QUOTE, headers=_h(e["tokens"]["Bodega"]), json=_prestamo(e))
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "PERMISSION_DENIED"
    assert r.json()["details"]["permission"] == "contracts.create"


async def test_una_categoria_de_otra_empresa_no_cotiza(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    a = await empresas("Empresa A")
    b = await empresas("Empresa B")
    await _ltv(b, 50)
    r = client.post(QUOTE, headers=_h(a["tokens"]["Admin"]), json=_prestamo(b))
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "NOT_FOUND"
    assert r.json()["details"] == {"category_id": str(b["category_id"])}


async def test_cotizar_no_escribe_nada(
    client: TestClient, empresas: Callable[[str], Awaitable[Empresa]]
) -> None:
    """Sin caja abierta y sin `Idempotency-Key`: si escribiera algo (un
    movimiento, un consecutivo, una auditoría) lo delatarían los conteos."""
    e = await empresas("Lectura")
    await _ltv(e, 70)
    antes = await _conteos(e["company_id"])
    for prestamo in (
        _prestamo(e, appraisal_value="2000000"),
        _prestamo(e, principal="9000000", appraisal_value="2000000"),
        {},
    ):
        r = client.post(QUOTE, headers=_h(e["tokens"]["Admin"]), json=prestamo)
        assert r.status_code == 200, r.text
    assert await _conteos(e["company_id"]) == antes
    assert Decimal(antes["contract"]) == 0
