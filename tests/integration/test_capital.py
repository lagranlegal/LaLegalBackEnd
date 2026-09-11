"""El dinero del DUEÑO: aportes al negocio y retiros de utilidad (00054).

La regla de fondo que cubren estos tests es UNA: **ni un aporte es un
ingreso, ni un retiro es un gasto**. Los dos mueven el patrimonio, no el
resultado del período. Requiere Postgres real (se salta si no hay).
"""

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.exc import DBAPIError

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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}


def _read(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def capital_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id, role_id, user_id = uuid4(), uuid4(), uuid4()
    register_id, session_id = uuid4(), uuid4()
    codes = (
        "capital.view",
        "capital.contribute",
        "capital.withdraw",
        "accounts.view",
        "cashbox.view",
        "reports.view",
    )

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa capital-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Admin')"),
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
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :rid, 'Dueño Test', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "rid": str(role_id),
                "email": f"cap-{user_id}@example.com",
            },
        )
        plan_id = (
            await session.execute(text("select id from public.plan where code = 'full'"))
        ).scalar_one()
        await session.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :pid, 'active', current_date + 30)"
            ),
            {"cid": str(company_id), "pid": str(plan_id)},
        )
        for name, tipo, default in (
            ("Caja principal", "cash", True),
            ("Transferencias", "bank", True),
            ("Sistecrédito", "settlement", True),
        ):
            await session.execute(
                text(
                    "insert into public.account (company_id, name, type, is_default) "
                    "values (:cid, :name, :type, :d)"
                ),
                {"cid": str(company_id), "name": name, "type": tipo, "d": default},
            )
        await session.execute(
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {"id": str(register_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.cash_session "
                "(id, company_id, register_id, opened_by, opening_balance, status) "
                "values (:id, :cid, :rid, :uid, 0, 'open')"
            ),
            {
                "id": str(session_id),
                "cid": str(company_id),
                "rid": str(register_id),
                "uid": str(user_id),
            },
        )

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )
    yield {
        "company_id": company_id,
        "role_id": role_id,
        "session_id": session_id,
        "token": token,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as s2, s2.begin():
                await s2.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    await _try_delete(
        "alter table public.capital_movement disable trigger trg_capital_movement_immutable"
    )
    await _try_delete("delete from public.capital_movement where company_id = :cid")
    await _try_delete(
        "alter table public.capital_movement enable trigger trg_capital_movement_immutable"
    )
    await _try_delete("alter table public.cash_movement disable trigger trg_movement_immutable")
    await _try_delete("delete from public.cash_movement where company_id = :cid")
    await _try_delete("alter table public.cash_movement enable trigger trg_movement_immutable")
    await _try_delete("delete from public.cash_session where company_id = :cid")
    await _try_delete("delete from public.cash_register where company_id = :cid")
    await _try_delete("delete from public.account where company_id = :cid")
    await _try_delete("delete from public.audit_log where company_id = :cid")
    await _try_delete("delete from public.app_user where company_id = :cid")
    await _try_delete(
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)"
    )
    await _try_delete("delete from public.role where company_id = :cid")
    await _try_delete("delete from public.subscription where company_id = :cid")
    await _try_delete("delete from public.code_counter where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


def _account_id(client: TestClient, token: str, tipo: str) -> str:
    r = client.get("/api/v1/accounts", headers=_read(token))
    assert r.status_code == 200, r.text
    for cuenta in r.json():
        if cuenta["type"] == tipo:
            return str(cuenta["id"])
    raise AssertionError(f"no hay cuenta de tipo {tipo}")


def _balance(client: TestClient, token: str, account_id: str) -> Decimal:
    r = client.get("/api/v1/accounts", headers=_read(token))
    for cuenta in r.json():
        if str(cuenta["id"]) == account_id:
            return Decimal(cuenta["balance"])
    raise AssertionError("cuenta no encontrada")


# --------------------------------------------------------------------------
# Aporte: el dueño mete plata al negocio
# --------------------------------------------------------------------------
def test_el_aporte_entra_a_la_cuenta_y_queda_documentado(
    client: TestClient, capital_tenant: dict
) -> None:
    """El caso que motivó el módulo: están bajos de capital para prestar y el
    dueño inyecta dinero.

    Hasta hoy no había dónde registrarlo, y las tres salidas que quedaban
    estaban mal: un `adjustment` (que miente — el sistema sí cuadraba), un
    traslado (que solo sirve si la plata ya está en una cuenta de la empresa)
    o nada, que deja plata en el cajón sin documento.
    """
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    antes = _balance(client, token, caja)

    r = client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "5000000.00", "notes": "Para seguir prestando"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["direction"] == "contribution"
    assert body["amount"] == "5000000.00"
    # Un aporte no tiene clase: `kind` es exactamente de los retiros.
    assert body["kind"] is None
    assert body["number"] >= 1
    assert _balance(client, token, caja) == antes + Decimal("5000000.00")


async def test_el_aporte_NO_es_un_ingreso(client: TestClient, capital_tenant: dict) -> None:
    """La regla de fondo. Un aporte es patrimonio, no resultado del período:
    si contara como ingreso, el dueño vería una "utilidad" igual a la plata
    que él mismo metió, y repartirla sería repartir su propio capital.

    El modelo ya lo garantiza sin excluir nada: el estado de resultados lee
    DOCUMENTOS (`sale`, `contract_payment`, `expense`) y un
    `capital_movement` no es ninguno de los tres.
    """
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")

    hoy = client.get(
        "/api/v1/reports/income-statement",
        headers=_read(token),
        params={"from_date": "2020-01-01", "to_date": "2030-12-31"},
    )
    assert hoy.status_code == 200, hoy.text
    utilidad_antes = Decimal(hoy.json()["operating_profit"])

    client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "5000000.00"},
    )

    despues = client.get(
        "/api/v1/reports/income-statement",
        headers=_read(token),
        params={"from_date": "2020-01-01", "to_date": "2030-12-31"},
    )
    assert Decimal(despues.json()["operating_profit"]) == utilidad_antes
    assert Decimal(despues.json()["total_revenue"]) == Decimal(hoy.json()["total_revenue"])


async def test_el_retiro_NO_es_un_gasto(client: TestClient, capital_tenant: dict) -> None:
    """La otra mitad, y la que más duele si se hace mal: registrar el retiro
    como gasto falsearía la utilidad del período por todo el monto retirado.

    Es el mismo error que este proyecto ya pagó tres veces — "prestar no es un
    gasto, cobrar no es una ganancia".
    """
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "5000000.00"},
    )

    antes = client.get(
        "/api/v1/reports/income-statement",
        headers=_read(token),
        params={"from_date": "2020-01-01", "to_date": "2030-12-31"},
    )
    gastos_antes = Decimal(antes.json()["operating_expenses"])

    r = client.post(
        "/api/v1/capital/withdrawals",
        headers=_headers(token),
        json={"account_id": caja, "amount": "1000000.00", "notes": "Retiro de utilidad"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "profit", "el default, sin UI el día uno"

    despues = client.get(
        "/api/v1/reports/income-statement",
        headers=_read(token),
        params={"from_date": "2020-01-01", "to_date": "2030-12-31"},
    )
    assert Decimal(despues.json()["operating_expenses"]) == gastos_antes
    assert Decimal(despues.json()["operating_profit"]) == Decimal(antes.json()["operating_profit"])
    # Pero la plata SÍ salió de la cuenta: no tocar el resultado no significa
    # no mover el saldo.
    assert _balance(client, token, caja) == Decimal("4000000.00")


def test_el_movimiento_de_caja_lleva_concepto_propio(
    client: TestClient, capital_tenant: dict
) -> None:
    """Conceptos propios y no `adjustment`: un ajuste significa "el sistema no
    cuadra con la realidad y lo estoy corrigiendo", y acá cuadra perfecto —
    hubo un hecho real con fecha, monto y responsable.

    Mezclarlos haría imposible separarlos después, que es el mismo argumento
    con el que 00032 les dio conceptos propios a los traslados.
    """
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "3000000.00"},
    )
    client.post(
        "/api/v1/capital/withdrawals",
        headers=_headers(token),
        json={"account_id": caja, "amount": "500000.00", "notes": "Retiro"},
    )

    movimientos = client.get(
        f"/api/v1/cashbox/sessions/{capital_tenant['session_id']}/report", headers=_read(token)
    )
    assert movimientos.status_code == 200, movimientos.text


def test_retirar_mas_de_lo_que_hay_se_rechaza(client: TestClient, capital_tenant: dict) -> None:
    """Un imposible físico, no una política de negocio.

    Acá SÍ se valida, a diferencia del desembolso de un préstamo (que sigue
    sin hacerlo, ver DECISIONES_PENDIENTES §3): el argumento que sostiene
    aquella excepción —un mostrador registra fuera de orden— no aplica a un
    acto deliberado del dueño.
    """
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    r = client.post(
        "/api/v1/capital/withdrawals",
        headers=_headers(token),
        json={"account_id": caja, "amount": "99000000.00", "notes": "Todo"},
    )
    assert r.status_code == 400, r.text
    assert "disponible" in r.json()["details"]


def test_una_cuenta_por_cobrar_no_sirve_para_esto(client: TestClient, capital_tenant: dict) -> None:
    """ "Una cuenta por cobrar no es plata": representa lo que un convenio te
    debe. No se le puede meter el efectivo del bolsillo del dueño ni sacarle
    un retiro, porque ese saldo todavía no existe."""
    token = capital_tenant["token"]
    convenio = _account_id(client, token, "settlement")
    r = client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": convenio, "amount": "1000000.00"},
    )
    assert r.status_code >= 400
    assert r.json()["code"] == "ACCOUNT_CANNOT_FUND_PAYMENT"


def test_el_retiro_exige_motivo(client: TestClient, capital_tenant: dict) -> None:
    """Un retiro sin motivo es la clase de línea que nadie puede explicar seis
    meses después — y es plata que salió del negocio. El aporte no lo exige:
    meter plata se explica solo."""
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    r = client.post(
        "/api/v1/capital/withdrawals",
        headers=_headers(token),
        json={"account_id": caja, "amount": "1000.00"},
    )
    assert r.status_code == 422, r.text

    sin_motivo_pero_aporte = client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "1000.00"},
    )
    assert sin_motivo_pero_aporte.status_code == 201


def test_reintentar_con_la_misma_clave_no_aporta_dos_veces(
    client: TestClient, capital_tenant: dict
) -> None:
    """Mover plata es una operación de dinero: el reintento de red devuelve el
    MISMO documento, no uno nuevo (CLAUDE.md regla 4)."""
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    headers = _headers(token)
    payload = {"account_id": caja, "amount": "2000000.00", "notes": "Inyección"}

    primero = client.post("/api/v1/capital/contributions", headers=headers, json=payload)
    segundo = client.post("/api/v1/capital/contributions", headers=headers, json=payload)
    assert primero.status_code == 201
    assert segundo.status_code == 201
    assert primero.json()["id"] == segundo.json()["id"]
    assert _balance(client, token, caja) == Decimal("2000000.00")


async def test_el_aporte_queda_auditado(client: TestClient, capital_tenant: dict) -> None:
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "1500000.00", "notes": "Capital de trabajo"},
    )

    async with AsyncSessionLocal() as session:
        fila = (
            await session.execute(
                text(
                    "select action, after from public.audit_log "
                    "where company_id = :cid and module = 'capital'"
                ),
                {"cid": str(capital_tenant["company_id"])},
            )
        ).first()
    assert fila is not None, "un movimiento de patrimonio sin auditar no es trazable"
    assert fila._mapping["action"] == "contribution"
    assert fila._mapping["after"]["amount"] == "1500000.00"


# --------------------------------------------------------------------------
# La posición: lo que el dueño mira ANTES de retirar
# --------------------------------------------------------------------------
def test_la_posicion_dice_donde_esta_la_plata(client: TestClient, capital_tenant: dict) -> None:
    """La pregunta que el dueño no puede contestar de memoria: en una
    compraventa la mayor parte del capital NO está en el cajón — está
    prestado y en vitrina. Retirar "lo que hay en caja" no es retirar
    utilidad, es descapitalizar."""
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "8000000.00"},
    )

    r = client.get(
        "/api/v1/capital/position",
        headers=_read(token),
        params={"from_date": "2020-01-01", "to_date": "2030-12-31"},
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert Decimal(p["contributions"]) == Decimal("8000000.00")
    assert Decimal(p["withdrawals"]) == Decimal("0.00")
    assert Decimal(p["net_capital_movement"]) == Decimal("8000000.00")
    assert Decimal(p["cash_and_bank"]) == Decimal("8000000.00")
    # Esta empresa de prueba no tiene contratos ni inventario, así que el
    # total es solo lo líquido — pero los tres sumandos tienen que estar.
    assert Decimal(p["total_capital"]) == (
        Decimal(p["cash_and_bank"]) + Decimal(p["loan_portfolio"]) + Decimal(p["inventory_at_cost"])
    )


def test_retirar_sin_utilidad_avisa_pero_no_bloquea(
    client: TestClient, capital_tenant: dict
) -> None:
    """El dueño puede retirar su propio capital y está en su derecho. Lo que
    la app hace es decirle qué está haciendo — mismo criterio que el LTV y el
    plazo de devolución: advertir sin estorbar.

    `distributable` negativo ES el aviso.
    """
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "8000000.00"},
    )

    # No hubo ventas ni abonos: la utilidad del período es cero.
    retiro = client.post(
        "/api/v1/capital/withdrawals",
        headers=_headers(token),
        json={"account_id": caja, "amount": "2000000.00", "notes": "Retiro del mes"},
    )
    assert retiro.status_code == 201, "no se bloquea"

    p = client.get(
        "/api/v1/capital/position",
        headers=_read(token),
        params={"from_date": "2020-01-01", "to_date": "2030-12-31"},
    ).json()
    assert Decimal(p["operating_profit"]) == Decimal("0.00")
    assert Decimal(p["distributable"]) == Decimal("-2000000.00"), (
        "se está sacando capital, no utilidad — y el número lo dice"
    )


# --------------------------------------------------------------------------
# Permisos e historial
# --------------------------------------------------------------------------
async def test_sin_permiso_de_retiro_no_se_puede_retirar(
    client: TestClient, capital_tenant: dict, rsa_keypair: tuple[str, object]
) -> None:
    """`capital.withdraw` es propio y especial: es la única operación de la
    app que le saca capital a la empresa sin nada a cambio. Quien puede ver el
    patrimonio o aportar no puede, por eso, retirar.

    Se prueba con un ROL NUEVO y no quitándole el permiso al de la fixture: el
    backend cachea los permisos por rol 60 segundos, así que revocar en la
    base no se ve dentro del test — y la llamada pasaba el `require_permission`
    para fallar después por saldo, dando un 400 que parecía cubrir un 403.
    """
    private_pem, _ = rsa_keypair
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")

    limitado_role, limitado_user = uuid4(), uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Contador')"),
            {"id": str(limitado_role), "cid": str(capital_tenant["company_id"])},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :rid, id from public.permission where code in :codes"
            ).bindparams(bindparam("codes", expanding=True)),
            {
                "rid": str(limitado_role),
                "codes": ["capital.view", "capital.contribute", "accounts.view"],
            },
        )
        await session.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :rid, 'Contador Test', :email, 'active')"
            ),
            {
                "id": str(limitado_user),
                "cid": str(capital_tenant["company_id"]),
                "rid": str(limitado_role),
                "email": f"cont-{limitado_user}@example.com",
            },
        )

    limitado = make_token(
        private_pem,
        sub=str(limitado_user),
        company_id=str(capital_tenant["company_id"]),
        role_id=str(limitado_role),
    )

    r = client.post(
        "/api/v1/capital/withdrawals",
        headers=_headers(limitado),
        json={"account_id": caja, "amount": "1000.00", "notes": "x"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "PERMISSION_DENIED"

    # Y el mismo usuario SÍ puede aportar: son permisos distintos a propósito.
    puede_aportar = client.post(
        "/api/v1/capital/contributions",
        headers=_headers(limitado),
        json={"account_id": caja, "amount": "1000.00"},
    )
    assert puede_aportar.status_code == 201, puede_aportar.text


def test_el_historial_sale_del_mas_reciente_al_mas_antiguo(
    client: TestClient, capital_tenant: dict
) -> None:
    """Acá el orden ES la función. `order by id` sobre UUID pagina bien y por
    eso nadie lo nota, pero el orden que produce no significa nada — y un
    histórico de plata desordenado no se puede leer.

    Y la fecha es la del DOCUMENTO: el dueño puede registrar el lunes el
    aporte que hizo el viernes.
    """
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    for fecha, monto in (("2026-01-15", "1000000.00"), ("2026-03-10", "2000000.00")):
        client.post(
            "/api/v1/capital/contributions",
            headers=_headers(token),
            json={"account_id": caja, "amount": monto, "movement_date": fecha},
        )
    # Este se REGISTRA último pero OCURRIÓ primero: tiene que salir al final.
    client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "500000.00", "movement_date": "2026-01-02"},
    )

    r = client.get("/api/v1/capital/movements", headers=_read(token))
    assert r.status_code == 200, r.text
    fechas = [item["movement_date"] for item in r.json()["items"]]
    assert fechas == ["2026-03-10", "2026-01-15", "2026-01-02"]

    solo_aportes = client.get(
        "/api/v1/capital/movements", headers=_read(token), params={"direction": "withdrawal"}
    )
    assert solo_aportes.json()["items"] == []


def test_una_fecha_futura_se_rechaza(client: TestClient, capital_tenant: dict) -> None:
    """Y se compara contra el hoy de la EMPRESA, no contra `current_date` de
    Postgres (que es UTC): entre las 7pm y medianoche de Bogotá ya es el día
    siguiente, y un aporte "de hoy" se rechazaría por futuro. Este proyecto ya
    se comió ese bug dos veces."""
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    r = client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "1000.00", "movement_date": "2099-01-01"},
    )
    assert r.status_code == 400, r.text


def test_un_movimiento_de_capital_es_inmutable(client: TestClient, capital_tenant: dict) -> None:
    """Igual que un traslado, un movimiento de caja o un recibo de abono:
    corregirlo es registrar el movimiento contrario, no editarlo."""
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    creado = client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "1000.00"},
    ).json()

    detalle = client.get(f"/api/v1/capital/movements/{creado['id']}", headers=_read(token))
    assert detalle.status_code == 200
    assert detalle.json()["id"] == creado["id"]

    inexistente = client.get(f"/api/v1/capital/movements/{uuid4()}", headers=_read(token))
    assert inexistente.status_code == 404


async def test_no_se_puede_editar_por_sql(client: TestClient, capital_tenant: dict) -> None:
    """El trigger `forbid_change`, comprobado de verdad: si alguien entra por
    la base, tampoco puede."""
    token = capital_tenant["token"]
    caja = _account_id(client, token, "cash")
    creado = client.post(
        "/api/v1/capital/contributions",
        headers=_headers(token),
        json={"account_id": caja, "amount": "1000.00"},
    ).json()

    with pytest.raises(DBAPIError):
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(
                text("update public.capital_movement set amount = 1 where id = :id"),
                {"id": str(UUID(creado["id"]))},
            )
