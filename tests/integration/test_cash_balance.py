"""El saldo de efectivo es del CAJÓN, no del turno (migración 00048).

Hasta 00048 el saldo de una cuenta `cash` se derivaba de la sesión de caja
abierta: su `opening_balance` digitado a mano más los movimientos de esa
sesión. Tres cosas rotas por el mismo error, y hay un test acá por cada una:

  · sin sesión abierta el cajón reportaba 0.00;
  · todas las cuentas de efectivo de una empresa reportaban el MISMO saldo;
  · el saldo dependía de un número escrito cada mañana que nada comparaba
    contra el cierre de la noche anterior.

Los tres se vieron fallar con el cálculo viejo antes de darlos por buenos
(principio del proyecto: un test que pasa no prueba nada hasta verlo fallar
sin el fix). Detalle del modelo: docs/CAJA_TRAZABILIDAD.md.
"""

from collections.abc import AsyncGenerator
from decimal import Decimal
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
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def tenant_efectivo(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    """Empresa con DOS cuentas de efectivo y una bancaria.

    Las dos de efectivo son el punto: con el cálculo viejo reportaban el
    mismo saldo (las dos leían la única sesión abierta), que es el defecto
    que llevó a un cliente a crear cajas de más buscando más efectivo.
    """
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id, role_id, user_id, register_id = uuid4(), uuid4(), uuid4(), uuid4()
    cajon_id, cajon_2_id, banco_id = uuid4(), uuid4(), uuid4()
    codes = (
        "cashbox.view",
        "cashbox.open_close",
        "cashbox.expense",
        "accounts.view",
        "accounts.manage",
        "accounts.transfer",
    )

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa saldo-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Cajero')"),
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
                "values (:id, :cid, :role_id, 'Cajero Saldo', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "role_id": str(role_id),
                "email": f"saldo-{user_id}@example.com",
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
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {"id": str(register_id), "cid": str(company_id)},
        )
        for account_id, name, tipo, is_default in (
            (cajon_id, "Cajón principal", "cash", True),
            (cajon_2_id, "Cajón mostrador 2", "cash", False),
            (banco_id, "Banco", "bank", True),
        ):
            await session.execute(
                text(
                    "insert into public.account "
                    "(id, company_id, name, type, is_default, opening_balance) "
                    "values (:id, :cid, :name, cast(:tipo as account_type), :def, 0)"
                ),
                {
                    "id": str(account_id),
                    "cid": str(company_id),
                    "name": name,
                    "tipo": tipo,
                    "def": is_default,
                },
            )

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )
    yield {
        "company_id": company_id,
        "user_id": user_id,
        "token": token,
        "cajon_id": cajon_id,
        "cajon_2_id": cajon_2_id,
        "banco_id": banco_id,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    # `cash_movement` tiene trigger de inmutabilidad sobre update/delete: hay
    # que desactivarlo para limpiar, igual que hace la migración 00024.
    try:
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(
                text("alter table public.cash_movement disable trigger trg_movement_immutable")
            )
            await session.execute(
                text("delete from public.cash_movement where company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.execute(
                text("alter table public.cash_movement enable trigger trg_movement_immutable")
            )
    except Exception:
        pass
    await _try_delete("delete from public.audit_log where company_id = :cid")
    await _try_delete("delete from public.account where company_id = :cid")
    await _try_delete("delete from public.app_user where company_id = :cid")
    await _try_delete(
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)"
    )
    await _try_delete("delete from public.role where company_id = :cid")
    await _try_delete("delete from public.subscription where company_id = :cid")
    await _try_delete("delete from public.cash_session where company_id = :cid")
    await _try_delete("delete from public.cash_register where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


def _saldo(client: TestClient, token: str, account_id: UUID) -> Decimal:
    response = client.get("/api/v1/accounts", headers=_headers(token))
    assert response.status_code == 200, response.text
    for account in response.json():
        if account["id"] == str(account_id):
            return Decimal(account["balance"])
    raise AssertionError(f"la cuenta {account_id} no está en el listado")


def _abrir(client: TestClient, token: str, **body: object) -> dict:
    response = client.post("/api/v1/cashbox/sessions/open", headers=_headers(token), json=body)
    return {"status": response.status_code, "body": response.json()}


# --------------------------------------------------------------------------
# 1. El cajón sigue teniendo plata con el turno cerrado
# --------------------------------------------------------------------------
def test_el_saldo_del_cajon_sobrevive_al_cierre_del_turno(
    client: TestClient, tenant_efectivo: dict
) -> None:
    """Con el cálculo viejo esto daba 0.00: sin sesión abierta no había de
    dónde leer el saldo, así que la plata del cajón dejaba de existir para
    el sistema entre el cierre de la noche y la apertura de la mañana."""
    token = tenant_efectivo["token"]
    abierta = _abrir(client, token, counted_cash="500000.00", difference_reason="Base inicial")
    assert abierta["status"] == 201, abierta["body"]

    cerrar = client.post(
        f"/api/v1/cashbox/sessions/{abierta['body']['id']}/close",
        headers=_headers(token),
        json={"counted_cash": "500000.00"},
    )
    assert cerrar.status_code == 200, cerrar.text

    assert _saldo(client, token, tenant_efectivo["cajon_id"]) == Decimal("500000.00")


# --------------------------------------------------------------------------
# 2. Dos cajones, dos saldos
# --------------------------------------------------------------------------
def test_dos_cuentas_de_efectivo_tienen_saldos_independientes(
    client: TestClient, tenant_efectivo: dict
) -> None:
    """Con el cálculo viejo las dos reportaban lo MISMO —el `opening_balance`
    de la única sesión abierta— porque ninguna leía sus propios movimientos.
    Es el defecto que hizo que un cliente creara cajas de más buscando tener
    más efectivo disponible, y viera el mismo número en las tres."""
    token = tenant_efectivo["token"]
    _abrir(client, token, counted_cash="300000.00", difference_reason="Base inicial")

    assert _saldo(client, token, tenant_efectivo["cajon_id"]) == Decimal("300000.00")
    assert _saldo(client, token, tenant_efectivo["cajon_2_id"]) == Decimal("0.00")


# --------------------------------------------------------------------------
# 3. Abrir hereda; abrir contando distinto exige motivo y deja rastro
# --------------------------------------------------------------------------
def test_abrir_sin_contar_hereda_el_saldo_del_cajon(
    client: TestClient, tenant_efectivo: dict
) -> None:
    token = tenant_efectivo["token"]
    primera = _abrir(client, token, counted_cash="200000.00", difference_reason="Base inicial")
    client.post(
        f"/api/v1/cashbox/sessions/{primera['body']['id']}/close",
        headers=_headers(token),
        json={"counted_cash": "200000.00"},
    )
    # Un turno por día calendario: para abrir otro hay que correr la fecha de
    # la ya cerrada, que es lo que haría el día siguiente.
    import asyncio

    async def _envejecer() -> None:
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(
                # `session_date - 1`, NO `current_date - 1`.
                #
                # `current_date` es la fecha del SERVIDOR (UTC); la sesión se
                # creó con el "hoy" de la EMPRESA (America/Bogota). Entre las
                # 7pm y medianoche esas dos fechas no coinciden, así que
                # `current_date - 1` daba exactamente la fecha que la sesión ya
                # tenía: el envejecido no hacía nada y el test fallaba con
                # `CASH_SESSION_ALREADY_CLOSED_TODAY`, pero SOLO de noche.
                #
                # Es la misma ventana de 5 horas que el backend ya arregló en
                # su día (`tenant_time`/`get_company_today`), reaparecida en un
                # test. Decrementar la columna es independiente de la zona.
                text(
                    "update public.cash_session set session_date = session_date - 1 "
                    "where company_id = :cid"
                ),
                {"cid": str(tenant_efectivo["company_id"])},
            )

    asyncio.get_event_loop().run_until_complete(_envejecer())

    segunda = _abrir(client, token)
    assert segunda["status"] == 201, segunda["body"]
    # Sin digitar nada: el saldo de apertura salió del cajón.
    assert segunda["body"]["opening_balance"] == "200000.00"


def test_contar_distinto_al_abrir_exige_motivo(client: TestClient, tenant_efectivo: dict) -> None:
    """Mismo rigor que el descuadre de cierre, y se asevera por CÓDIGO: un
    test que mira el status y no el `code` no cubre nada."""
    resultado = _abrir(client, tenant_efectivo["token"], counted_cash="50000.00")
    assert resultado["status"] == 400, resultado["body"]
    assert resultado["body"]["code"] == "CASH_OPENING_DIFFERENCE_UNJUSTIFIED"


def test_contar_distinto_al_abrir_deja_el_saldo_en_lo_contado(
    client: TestClient, tenant_efectivo: dict
) -> None:
    token = tenant_efectivo["token"]
    resultado = _abrir(
        client, token, counted_cash="50000.00", difference_reason="Faltaban billetes"
    )
    assert resultado["status"] == 201, resultado["body"]
    # El ajuste movió el saldo: el cajón vale lo que se contó, no lo que el
    # sistema creía.
    assert _saldo(client, token, tenant_efectivo["cajon_id"]) == Decimal("50000.00")


# --------------------------------------------------------------------------
# 4. El descuadre de cierre mueve el saldo, y no contamina el acta
# --------------------------------------------------------------------------
def test_el_descuadre_de_cierre_mueve_el_saldo(client: TestClient, tenant_efectivo: dict) -> None:
    """Antes el descuadre era SOLO un campo del acta: el saldo seguía
    diciendo lo esperado hasta que la apertura siguiente lo pisaba con otro
    número a mano, y la plata que faltó no quedaba en ninguna parte
    consultable."""
    token = tenant_efectivo["token"]
    abierta = _abrir(client, token, counted_cash="100000.00", difference_reason="Base inicial")
    cerrar = client.post(
        f"/api/v1/cashbox/sessions/{abierta['body']['id']}/close",
        headers=_headers(token),
        json={"counted_cash": "92000.00", "difference_reason": "Faltaron 8.000"},
    )
    assert cerrar.status_code == 200, cerrar.text
    assert cerrar.json()["difference"] == "-8000.00"

    assert _saldo(client, token, tenant_efectivo["cajon_id"]) == Decimal("92000.00")


def test_el_ajuste_de_cierre_no_ensucia_el_acta(client: TestClient, tenant_efectivo: dict) -> None:
    """El ajuste va con `session_id = NULL` a propósito. Metido dentro de la
    sesión, `get_report` recalcularía un `expected_cash` igual al contado —
    un acta que siempre cuadra, que es lo contrario de lo que tiene que
    hacer."""
    token = tenant_efectivo["token"]
    abierta = _abrir(client, token, counted_cash="100000.00", difference_reason="Base inicial")
    session_id = abierta["body"]["id"]
    client.post(
        f"/api/v1/cashbox/sessions/{session_id}/close",
        headers=_headers(token),
        json={"counted_cash": "92000.00", "difference_reason": "Faltaron 8.000"},
    )

    reporte = client.get(f"/api/v1/cashbox/sessions/{session_id}/report", headers=_headers(token))
    assert reporte.status_code == 200, reporte.text
    # Sigue diciendo lo que se ESPERABA, no lo que se contó.
    assert reporte.json()["expected_cash"] == "100000.00"


# --------------------------------------------------------------------------
# 5. La caja fuerte: efectivo real que no es un punto de cobro (00049)
# --------------------------------------------------------------------------
def test_una_caja_fuerte_no_puede_cobrar(client: TestClient, tenant_efectivo: dict) -> None:
    """Una `vault` es plata REAL, a diferencia de una cuenta por cobrar. Lo
    que no es, es un punto de cobro: nadie vende parado frente a la caja
    fuerte. Aceptar un cobro directo ahí saltaría el arqueo del cajón sin que
    nada lo note."""
    token = tenant_efectivo["token"]
    _abrir(client, token, counted_cash="100000.00", difference_reason="Base inicial")

    fuerte = client.post(
        "/api/v1/accounts",
        headers=_headers(token),
        json={
            "name": "Caja fuerte",
            "type": "vault",
            "is_default": False,
            "opening_balance": "0.00",
        },
    )
    assert fuerte.status_code == 201, fuerte.text

    categoria = client.post(
        "/api/v1/cashbox/expense-categories", headers=_headers(token), json={"name": "Varios"}
    )
    gasto = client.post(
        "/api/v1/cashbox/expenses",
        headers={**_headers(token), "Idempotency-Key": str(uuid4())},
        json={
            "category_id": categoria.json()["id"],
            "module": "general",
            "description": "Gasto pagado desde la caja fuerte",
            "amount": "10000.00",
            "payment_method": "cash",
            "account_id": fuerte.json()["id"],
        },
    )
    assert gasto.status_code == 400, gasto.text
    assert gasto.json()["code"] == "ACCOUNT_NOT_OPERATIONAL"


def test_la_caja_fuerte_no_entra_al_arqueo_del_cajon(
    client: TestClient, tenant_efectivo: dict
) -> None:
    """El arqueo diario es del CAJÓN. Si la caja fuerte entrara, el cierre
    pediría contar todas las noches plata que está guardada bajo llave."""
    token = tenant_efectivo["token"]
    abierta = _abrir(client, token, counted_cash="100000.00", difference_reason="Base inicial")
    fuerte = client.post(
        "/api/v1/accounts",
        headers=_headers(token),
        json={
            "name": "Caja fuerte",
            "type": "vault",
            "is_default": False,
            "opening_balance": "500000.00",
        },
    )
    assert fuerte.status_code == 201, fuerte.text

    reporte = client.get(
        f"/api/v1/cashbox/sessions/{abierta['body']['id']}/report", headers=_headers(token)
    )
    # Los 500.000 de la caja fuerte existen como saldo, pero no se cuentan hoy.
    assert reporte.json()["expected_cash"] == "100000.00"
    assert _saldo(client, token, UUID(fuerte.json()["id"])) == Decimal("500000.00")


def test_no_se_puede_crear_una_segunda_cuenta_de_efectivo(
    client: TestClient, tenant_efectivo: dict
) -> None:
    """La guarda que `00024_accounts.sql` prometía en un comentario y su
    índice parcial no daba — por ese hueco una empresa terminó con tres
    cajones compartiendo un solo arqueo."""
    segunda = client.post(
        "/api/v1/accounts",
        headers=_headers(tenant_efectivo["token"]),
        json={"name": "Otro cajón", "type": "cash", "is_default": False, "opening_balance": "0.00"},
    )
    assert segunda.status_code == 409, segunda.text
    assert segunda.json()["code"] == "CASH_ACCOUNT_ALREADY_EXISTS"


def test_la_caja_fuerte_se_llena_por_traslado(client: TestClient, tenant_efectivo: dict) -> None:
    """Su única puerta. Y el traslado exige el cajón abierto porque la pata de
    efectivo sí lo toca — sin sesión, el arqueo no podría cuadrar."""
    token = tenant_efectivo["token"]
    _abrir(client, token, counted_cash="300000.00", difference_reason="Base inicial")
    fuerte = client.post(
        "/api/v1/accounts",
        headers=_headers(token),
        json={
            "name": "Caja fuerte",
            "type": "vault",
            "is_default": False,
            "opening_balance": "0.00",
        },
    )
    traslado = client.post(
        "/api/v1/accounts/transfers",
        headers={**_headers(token), "Idempotency-Key": str(uuid4())},
        json={
            "from_account_id": str(tenant_efectivo["cajon_id"]),
            "to_account_id": fuerte.json()["id"],
            "amount": "200000.00",
            "notes": "Guardar el excedente del día",
        },
    )
    assert traslado.status_code == 201, traslado.text
    assert _saldo(client, token, tenant_efectivo["cajon_id"]) == Decimal("100000.00")
    assert _saldo(client, token, UUID(fuerte.json()["id"])) == Decimal("200000.00")
