"""Catálogo de cuentas y liquidaciones (00024).

El caso que motiva el módulo: el negocio vende con Sistecrédito, donde el
dinero NO entra al vender — el convenio asume el crédito y consigna días
después, menos una comisión. Con el enum de medios de pago esa plata era
invisible. Requiere Postgres real (se salta si no hay).
"""

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}


@pytest_asyncio.fixture
async def accounts_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id, role_id, user_id = uuid4(), uuid4(), uuid4()
    register_id, session_id = uuid4(), uuid4()
    # `accounts.*` son propios del módulo desde 00029: antes se colaba por
    # `cashbox.view` (leer) y `company.configure` (administrar), y liquidar
    # —que mueve plata— quedaba detrás de un permiso de solo lectura.
    codes = (
        "cashbox.view",
        "cashbox.open_close",
        "company.configure",
        "accounts.view",
        "accounts.manage",
        "accounts.settle",
        # 00032: consignar el efectivo del día.
        "accounts.transfer",
        # Para probar que una cuenta POR COBRAR no puede financiar una salida:
        # el gasto es la salida más simple de montar (no necesita proveedor ni
        # mercancía) y pasa por el mismo `resolve_account_for_movement` que las
        # compras y los desembolsos.
        "cashbox.expense",
    )

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa accounts-test')"),
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
                "values (:id, :cid, :rid, 'Admin Test', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "rid": str(role_id),
                "email": f"acc-{user_id}@example.com",
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
        # Las cuentas base las crea la migración por empresa; esta empresa se
        # inserta después, así que se replican acá igual que lo haría el alta.
        for name, tipo, default in (
            ("Caja principal", "cash", True),
            ("Transferencias", "bank", True),
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
    yield {"company_id": company_id, "session_id": session_id, "token": token}

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as s2, s2.begin():
                await s2.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

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
    await _try_delete("delete from public.company where id = :cid")


def _accounts(client: TestClient, token: str) -> list[dict]:
    r = client.get("/api/v1/accounts", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return list(r.json())


def _create(client: TestClient, token: str, **body: object) -> dict:
    r = client.post("/api/v1/accounts", headers=_headers(token), json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_accounts_start_with_cash_and_bank(client: TestClient, accounts_tenant: dict) -> None:
    tipos = {a["type"] for a in _accounts(client, accounts_tenant["token"])}
    assert tipos == {"cash", "bank"}


def test_create_settlement_account_for_sistecredito(
    client: TestClient, accounts_tenant: dict
) -> None:
    cuenta = _create(client, accounts_tenant["token"], name="Sistecrédito", type="settlement")
    assert cuenta["type"] == "settlement"
    # Nace en cero: nadie le debe nada todavía.
    assert cuenta["balance"] == "0.00"


@pytest.mark.asyncio
async def test_settling_derives_the_commission_without_configuring_it(
    client: TestClient, accounts_tenant: dict
) -> None:
    """El corazón del diseño: se informa lo liquidado y lo recibido, y la
    comisión SALE de la diferencia. Nunca hay que configurar el porcentaje del
    convenio, así que el sistema no puede quedar desactualizado."""
    token = accounts_tenant["token"]
    sistecredito = _create(client, token, name="Sistecrédito", type="settlement")
    banco = next(a for a in _accounts(client, token) if a["type"] == "bank")

    # Simula una venta por Sistecrédito: quedan $1.000.000 por cobrar.
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.cash_movement "
                "(company_id, session_id, module, direction, concept, reference_type, "
                " reference_id, amount, payment_method, account_id) "
                "values (:cid, :sid, 'store', 'in', 'sale', 'sale', :ref, 1000000, "
                " 'other', :aid)"
            ),
            {
                "cid": str(accounts_tenant["company_id"]),
                "sid": str(accounts_tenant["session_id"]),
                "ref": str(uuid4()),
                "aid": sistecredito["id"],
            },
        )

    pendiente = next(a for a in _accounts(client, token) if a["id"] == sistecredito["id"])
    assert pendiente["balance"] == "1000000.00"

    # Sistecrédito consigna $920.000 de ese millón: la comisión son $80.000.
    r = client.post(
        f"/api/v1/accounts/{sistecredito['id']}/settle",
        headers=_headers(token),
        json={
            "to_account_id": banco["id"],
            "amount_settled": "1000000.00",
            "amount_received": "920000.00",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["commission"] == "80000.00"
    assert body["commission_pct"] == "8.00"
    assert body["new_pending_balance"] == "0.00"


def test_cannot_receive_more_than_settled(client: TestClient, accounts_tenant: dict) -> None:
    """La diferencia es la comisión del convenio: nunca puede ser negativa."""
    token = accounts_tenant["token"]
    cuenta = _create(client, token, name="Sistecrédito", type="settlement")
    banco = next(a for a in _accounts(client, token) if a["type"] == "bank")

    r = client.post(
        f"/api/v1/accounts/{cuenta['id']}/settle",
        headers=_headers(token),
        json={
            "to_account_id": banco["id"],
            "amount_settled": "100000.00",
            "amount_received": "120000.00",
        },
    )
    assert r.status_code == 400


def test_only_settlement_accounts_can_be_settled(client: TestClient, accounts_tenant: dict) -> None:
    token = accounts_tenant["token"]
    cuentas = _accounts(client, token)
    caja = next(a for a in cuentas if a["type"] == "cash")
    banco = next(a for a in cuentas if a["type"] == "bank")

    r = client.post(
        f"/api/v1/accounts/{caja['id']}/settle",
        headers=_headers(token),
        json={
            "to_account_id": banco["id"],
            "amount_settled": "1000.00",
            "amount_received": "1000.00",
        },
    )
    assert r.status_code == 400


def test_cannot_deactivate_the_default_account(client: TestClient, accounts_tenant: dict) -> None:
    """Desactivar la cuenta por defecto dejaría los cobros sin dónde caer."""
    token = accounts_tenant["token"]
    caja = next(a for a in _accounts(client, token) if a["type"] == "cash")

    r = client.patch(
        f"/api/v1/accounts/{caja['id']}",
        headers=_headers(token),
        json={"active": False},
    )
    assert r.status_code == 409


# ---- La sesión la exige el TIPO DE CUENTA, no la operación (00026) -------


@pytest.mark.asyncio
async def test_non_cash_movement_does_not_require_an_open_session(
    client: TestClient, accounts_tenant: dict
) -> None:
    """El problema de las 11 de la noche, resuelto de raíz: una venta por
    Sistecrédito no pasa por el cajón físico, así que no tiene por qué exigir
    que el cajón esté abierto. Antes toda operación de dinero lo exigía."""
    from app.core.db import AsyncSessionLocal as SL
    from app.modules.cashbox import integration as cashbox_integration

    token = accounts_tenant["token"]
    sistecredito = _create(client, token, name="Sistecrédito", type="settlement")

    async with SL() as s, s.begin():
        await s.execute(
            text("update public.cash_session set status = 'closed' where id = :sid"),
            {"sid": str(accounts_tenant["session_id"])},
        )

    async with SL() as s:
        resolved = await cashbox_integration.resolve_account_for_movement(
            s,
            company_id=accounts_tenant["company_id"],
            payment_method="other",
            account_id=UUID(sistecredito["id"]),
        )

    assert resolved.account_type == "settlement"
    # Sin sesión abierta y sin excepción: el movimiento no pertenece a ningún
    # turno de caja, y eso es correcto.
    assert resolved.session_id is None


@pytest.mark.asyncio
async def test_cash_movement_still_requires_an_open_session(
    client: TestClient, accounts_tenant: dict
) -> None:
    """El efectivo NO se relaja: no se pueden meter billetes a un cajón
    cerrado, y sin sesión el arqueo no podría cuadrar nunca."""
    from app.core.db import AsyncSessionLocal as SL
    from app.core.errors import CashSessionNotOpenError
    from app.modules.cashbox import integration as cashbox_integration

    token = accounts_tenant["token"]
    caja = next(a for a in _accounts(client, token) if a["type"] == "cash")

    async with SL() as s, s.begin():
        await s.execute(
            text("update public.cash_session set status = 'closed' where id = :sid"),
            {"sid": str(accounts_tenant["session_id"])},
        )

    with pytest.raises(CashSessionNotOpenError):
        async with SL() as s:
            await cashbox_integration.resolve_account_for_movement(
                s,
                company_id=accounts_tenant["company_id"],
                payment_method="cash",
                account_id=UUID(caja["id"]),
            )


def test_cash_balance_is_what_should_be_in_the_drawer(
    client: TestClient, accounts_tenant: dict
) -> None:
    """Regresión del bug encontrado sembrando datos reales: el saldo de una
    cuenta de efectivo NO es el neto histórico de movimientos —eso daba
    negativo porque la base de apertura no es un movimiento— sino la base de
    la sesión abierta más lo movido en ella."""
    caja = next(a for a in _accounts(client, accounts_tenant["token"]) if a["type"] == "cash")
    # El fixture abre la sesión con base 0 y no registra movimientos.
    assert caja["balance"] == "0.00"


def test_bank_balance_starts_from_its_opening_balance(
    client: TestClient, accounts_tenant: dict
) -> None:
    """La otra mitad del mismo bug: una cuenta bancaria ya tenía plata antes
    de que el sistema existiera, así que sin `opening_balance` el primer
    egreso la dejaba en negativo."""
    token = accounts_tenant["token"]
    cuenta = _create(client, token, name="Bancolombia", type="bank", opening_balance="3000000.00")
    assert cuenta["opening_balance"] == "3000000.00"
    assert cuenta["balance"] == "3000000.00"


@pytest_asyncio.fixture
async def solo_lectura_token(
    accounts_tenant: dict, monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> str:
    """Usuario con `accounts.view` y nada más — el caso del asesor que cobra."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    role_id, user_id = uuid4(), uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Solo Ver')"),
            {"id": str(role_id), "cid": str(accounts_tenant["company_id"])},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code = 'accounts.view'"
            ),
            {"role_id": str(role_id)},
        )
        await session.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :rid, 'Solo Ver', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(accounts_tenant["company_id"]),
                "rid": str(role_id),
                "email": f"solover-{user_id}@test.local",
            },
        )
    return make_token(
        private_pem,
        sub=str(user_id),
        company_id=str(accounts_tenant["company_id"]),
        role_id=str(role_id),
    )


def test_ver_cuentas_no_alcanza_para_liquidar(
    client: TestClient, accounts_tenant: dict, solo_lectura_token: str
) -> None:
    """Liquidar MUEVE PLATA, así que no puede colgar de un permiso de lectura.

    Hasta 00029 `settle` exigía `cashbox.view` — o sea que cualquiera que
    pudiera mirar la caja podía liquidar Sistecrédito. Este test fija la
    separación: ver el saldo y cobrarlo son cosas distintas.
    """
    headers = {"Authorization": f"Bearer {solo_lectura_token}"}

    # Ver sí puede.
    assert client.get("/api/v1/accounts", headers=headers).status_code == 200

    convenio = _create(client, accounts_tenant["token"], name="Sistecrédito", type="settlement")
    destino = next(a for a in _accounts(client, accounts_tenant["token"]) if a["type"] == "cash")

    respuesta = client.post(
        f"/api/v1/accounts/{convenio['id']}/settle",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "to_account_id": destino["id"],
            "amount_settled": "100000.00",
            "amount_received": "95000.00",
        },
    )
    assert respuesta.status_code == 403
    assert respuesta.json()["code"] == "PERMISSION_DENIED"


def test_ver_cuentas_no_alcanza_para_crearlas(client: TestClient, solo_lectura_token: str) -> None:
    """Mismo criterio del otro lado: administrar el catálogo es `accounts.manage`."""
    respuesta = client.post(
        "/api/v1/accounts",
        headers={"Authorization": f"Bearer {solo_lectura_token}"},
        json={"name": "No debería crearse", "type": "bank"},
    )
    assert respuesta.status_code == 403


def test_settlement_account_cannot_fund_a_payment(
    client: TestClient, accounts_tenant: dict
) -> None:
    """Una cuenta por cobrar no puede pagar.

    El bug que motiva esto salió en uso real: al registrar una compra a
    proveedor, el selector de cuenta ofrecía Sistecrédito. Filtraba solo por
    medio de pago ("otro") sin mirar la dirección del movimiento, así que
    dejaba elegir "pagarle al proveedor con Sistecrédito" — una operación que
    no existe: esa plata todavía te la deben, no la tienes.

    El front ya no la ofrece, pero la UI oculta y no protege (CLAUDE.md regla
    7): la autoridad es esta validación.
    """
    headers = _headers(accounts_tenant["token"])
    sistecredito = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={"name": "Sistecrédito", "type": "settlement"},
    )
    assert sistecredito.status_code == 201, sistecredito.text
    account_id = sistecredito.json()["id"]

    category_id = str(uuid4())
    client.post(
        "/api/v1/cashbox/expense-categories",
        headers=_headers(accounts_tenant["token"]),
        json={"name": f"Servicios {category_id[:8]}"},
    )
    categories = client.get(
        "/api/v1/cashbox/expense-categories", headers=_headers(accounts_tenant["token"])
    ).json()
    assert categories, "el gasto necesita una categoría para poder registrarse"

    rechazado = client.post(
        "/api/v1/cashbox/expenses",
        headers=_headers(accounts_tenant["token"]),
        json={
            "account_id": account_id,
            "category_id": categories[0]["id"],
            "description": "Pago de arriendo",
            "amount": "150000.00",
            "payment_method": "other",
        },
    )
    assert rechazado.status_code == 400, rechazado.text
    assert rechazado.json()["code"] == "ACCOUNT_CANNOT_FUND_PAYMENT"

    # Y la contraparte: COBRAR a esa misma cuenta sigue siendo válido, que es
    # justamente para lo que existe. Si esto se rompiera, el arreglo habría
    # inutilizado el módulo en vez de corregirlo.
    banco = next(
        a for a in client.get("/api/v1/accounts", headers=headers).json() if a["type"] == "bank"
    )
    assert banco is not None


def test_transfer_moves_cash_to_bank_without_touching_results(
    client: TestClient, accounts_tenant: dict
) -> None:
    """Consignar el efectivo baja el cajón y sube el banco. Nada más.

    Es el caso que no existía: al final del día se saca la plata del cajón y
    se lleva al banco. Sin esta operación había que registrarlo como gasto
    —que falsea la utilidad por el monto consignado, prácticamente toda la
    caja del día— o no registrarlo, y entonces el efectivo esperado del día
    siguiente queda inflado y el arqueo descuadra sin culpa del cajero.
    """
    token = accounts_tenant["token"]
    cuentas = {a["type"]: a for a in _accounts(client, token)}
    caja, banco = cuentas["cash"], cuentas["bank"]

    saldo_caja_antes = float(caja["balance"])

    traslado = client.post(
        "/api/v1/accounts/transfers",
        headers=_headers(token),
        json={
            "from_account_id": banco["id"],
            "to_account_id": caja["id"],
            "amount": "200000.00",
            "notes": "Retiro para base de caja",
        },
    )
    # El banco arranca en 0, así que trasladar de ahí debe rechazarse: no se
    # puede mover plata que no hay.
    assert traslado.status_code == 400, traslado.text
    assert "más de lo que hay" in traslado.json()["message"]

    # Se le da saldo inicial a una cuenta bancaria nueva y desde ahí sí.
    origen = _create(
        client, token, name="Bancolombia ahorros", type="bank", opening_balance="1000000.00"
    )
    ok = client.post(
        "/api/v1/accounts/transfers",
        headers=_headers(token),
        json={
            "from_account_id": origen["id"],
            "to_account_id": caja["id"],
            "amount": "300000.00",
        },
    )
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert float(body["amount"]) == 300000.0
    assert body["from_account_name"] == "Bancolombia ahorros"
    # Los saldos vienen en la respuesta: el origen bajó, el destino subió.
    assert float(body["from_balance"]) == 700000.0
    assert float(body["to_balance"]) == saldo_caja_antes + 300000.0


def test_transfer_rejects_same_account_and_receivables(
    client: TestClient, accounts_tenant: dict
) -> None:
    """Los tres casos que no son un traslado."""
    token = accounts_tenant["token"]
    cuentas = {a["type"]: a for a in _accounts(client, token)}
    caja = cuentas["cash"]
    sistecredito = _create(client, token, name="Sistecrédito tr", type="settlement")

    misma = client.post(
        "/api/v1/accounts/transfers",
        headers=_headers(token),
        json={
            "from_account_id": caja["id"],
            "to_account_id": caja["id"],
            "amount": "1000.00",
        },
    )
    assert misma.status_code == 400
    assert "misma cuenta" in misma.json()["message"]

    # Desde una cuenta por cobrar: esa plata todavía no llegó. Su salida
    # legítima es la liquidación, que además calcula la comisión.
    desde_cobrar = client.post(
        "/api/v1/accounts/transfers",
        headers=_headers(token),
        json={
            "from_account_id": sistecredito["id"],
            "to_account_id": caja["id"],
            "amount": "1000.00",
        },
    )
    assert desde_cobrar.status_code == 400
    assert desde_cobrar.json()["code"] == "ACCOUNT_CANNOT_FUND_PAYMENT"

    # Hacia una cuenta por cobrar: lo que un convenio te debe lo genera
    # vender, no consignar.
    hacia_cobrar = client.post(
        "/api/v1/accounts/transfers",
        headers=_headers(token),
        json={
            "from_account_id": caja["id"],
            "to_account_id": sistecredito["id"],
            "amount": "1000.00",
        },
    )
    assert hacia_cobrar.status_code == 400


def test_transfer_out_of_cash_lowers_expected_cash_of_the_close(
    client: TestClient, accounts_tenant: dict
) -> None:
    """Consignar baja el efectivo esperado — el punto entero de la operación.

    Si el traslado no se reflejara en el arqueo, el cajero contaría menos
    billetes de los que el sistema espera y tendría que justificar un
    descuadre por haber hecho exactamente lo que debía.
    """
    token = accounts_tenant["token"]
    cuentas = {a["type"]: a for a in _accounts(client, token)}
    caja = cuentas["cash"]
    origen = _create(
        client, token, name="Banco origen arqueo", type="bank", opening_balance="500000.00"
    )

    session_id = str(accounts_tenant["session_id"])
    antes = client.get(
        f"/api/v1/cashbox/sessions/{session_id}/report",
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    # Entra plata al cajón…
    client.post(
        "/api/v1/accounts/transfers",
        headers=_headers(token),
        json={
            "from_account_id": origen["id"],
            "to_account_id": caja["id"],
            "amount": "400000.00",
        },
    )
    con_ingreso = client.get(
        f"/api/v1/cashbox/sessions/{session_id}/report",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert float(con_ingreso["expected_cash"]) == float(antes["expected_cash"]) + 400000.0

    # …y se consigna de vuelta: el esperado tiene que volver a bajar.
    client.post(
        "/api/v1/accounts/transfers",
        headers=_headers(token),
        json={
            "from_account_id": caja["id"],
            "to_account_id": origen["id"],
            "amount": "150000.00",
            "notes": "Consignación del día",
        },
    )
    despues = client.get(
        f"/api/v1/cashbox/sessions/{session_id}/report",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert float(despues["expected_cash"]) == float(con_ingreso["expected_cash"]) - 150000.0

    # Y aparece en el desglose con concepto propio, no como ajuste ni gasto.
    conceptos = {line["concept"] for line in despues["lines"]}
    assert "transfer_out" in conceptos
    assert "transfer_in" in conceptos
