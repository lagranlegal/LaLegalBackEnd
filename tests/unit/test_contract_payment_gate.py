"""La puerta de los abonos: qué estados de contrato NO admiten un abono.

El defecto que originó este archivo (21/09/2026, hallazgo F21-11 de
`docs/QA_AUDITORIA.md`): `service.create_payment` filtraba con una lista
escrita a mano —`status in ("paid", "auctioned")`— a la que le faltaba
`superseded`. O sea que **un contrato ya reemplazado por una ampliación
admitía un abono**: la plata entraba a la caja, el sucesor seguía debiendo
todo, y quedaba registrado un abono que no bajaba ninguna deuda viva.

Es la misma forma del bug de F21-10 (una lista negra que se desincroniza de
`rules.TERMINAL_STATUSES`), así que estos tests **no repiten la lista de
estados**: uno de ellos inventa un estado terminal nuevo y exige que la puerta
lo rechace sin que nadie toque `service.py`. Con la lista a mano —vieja o
"hoy completa"— falla.

Corre sin Postgres a propósito (el rechazo ocurre antes de tocar la base, con
el repositorio monkeypatcheado), así que también cubre donde la suite de
integración se salta por falta de Docker.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.modules.contracts import repository, rules, service
from app.modules.contracts.schemas import PaymentCreateIn

_CONTRATO_ID = UUID("00000000-0000-0000-0000-0000000000c1")
_EMPRESA_ID = UUID("00000000-0000-0000-0000-0000000000e1")
_SUCESOR_ID = UUID("00000000-0000-0000-0000-0000000000c2")


class _Fila:
    """Lo único que el servicio usa de un `Row`: su `_mapping`."""

    def __init__(self, **campos: Any) -> None:
        self._mapping = campos


def _contrato(status: str) -> _Fila:
    return _Fila(
        id=_CONTRATO_ID,
        status=status,
        capital_balance=Decimal("1000000.00"),
        interest_rate_pct=Decimal("5.00"),
        interest_paid_until=date(2026, 9, 1),
        arrears_window_months=4,
        extension_months=1,
    )


def _usuario() -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        company_id=_EMPRESA_ID,
        role_id=uuid4(),
        full_name="Cajero",
        email="cajero@example.com",
    )


async def _abonar(
    monkeypatch: pytest.MonkeyPatch, *, status: str, con_sucesor: bool = True
) -> AppError:
    """Intenta un abono sobre un contrato en `status` y devuelve el error.

    Todo lo que toca la base está monkeypatcheado. La puerta tiene que rechazar
    ANTES de consultar el "hoy" de la empresa, así que ese es el centinela: si
    el abono se cuela, el test falla diciendo que se coló y con qué estado, no
    con un `AttributeError` de plomería sobre una sesión de mentira.
    """

    async def _sin_idempotencia(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _get_contract(*_args: Any, **_kwargs: Any) -> _Fila:
        return _contrato(status)

    async def _find_successor(*_args: Any, **_kwargs: Any) -> _Fila | None:
        return _Fila(id=_SUCESOR_ID, number=41) if con_sucesor else None

    async def _centinela(*_args: Any, **_kwargs: Any) -> date:
        raise AssertionError(
            f"La puerta de los abonos dejó pasar un contrato en `{status}`: el abono siguió "
            "hasta consultar el 'hoy' de la empresa. Se habría registrado plata contra un "
            "contrato que no admite abonos."
        )

    monkeypatch.setattr(service.platform_integration, "get_company_today", _centinela)
    monkeypatch.setattr(repository, "find_payment_by_idempotency_key", _sin_idempotencia)
    monkeypatch.setattr(repository, "get_contract", _get_contract)
    monkeypatch.setattr(repository, "find_successor_contract", _find_successor)

    with pytest.raises(AppError) as excinfo:
        await service.create_payment(
            None,  # type: ignore[arg-type]
            company_id=_EMPRESA_ID,
            contract_id=_CONTRATO_ID,
            body=PaymentCreateIn(months_covered=1, payment_method="cash"),
            user=_usuario(),
            idempotency_key=str(uuid4()),
        )
    return excinfo.value


async def test_un_contrato_reemplazado_no_admite_abonos(monkeypatch: pytest.MonkeyPatch) -> None:
    """El defecto. Y el CÓDIGO, no el status: un código de error es un
    contrato entre dos capas y nadie lo compila."""
    error = await _abonar(monkeypatch, status="superseded")

    assert error.code == "CONTRACT_SUPERSEDED"
    assert error.status_code == 409
    # El mensaje nombra la acción que falta, no solo niega la que se intentó:
    # "no puedes" sin "quién sí" es un callejón sin salida.
    assert "41" in error.message, error.message
    assert error.details["successor_contract_id"] == str(_SUCESOR_ID)
    assert error.details["successor_number"] == 41


async def test_sin_sucesor_se_rechaza_igual_y_con_el_mismo_codigo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`superseded` sin sucesor no debería existir —lo vigila
    `scripts/qa/verificar_cadenas.py`—, pero si existe el abono se rechaza
    igual: este documento ya no es la deuda. Lo que no se hace es inventar un
    número de contrato que nadie va a encontrar."""
    error = await _abonar(monkeypatch, status="superseded", con_sucesor=False)

    assert error.code == "CONTRACT_SUPERSEDED"
    assert error.details == {}


@pytest.mark.parametrize("status", ["paid", "auctioned"])
async def test_los_otros_terminales_siguen_dando_CONTRACT_CLOSED(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """El contrato viejo con el front no se rompe: `paid` y `auctioned` siguen
    respondiendo `400 CONTRACT_CLOSED`, que es lo que la UI escucha hoy."""
    error = await _abonar(monkeypatch, status=status)

    assert error.code == "CONTRACT_CLOSED"
    assert error.status_code == 400


async def test_un_estado_terminal_nuevo_queda_cerrado_para_abonos_sin_tocar_el_servicio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El invariante de verdad, y la razón de reusar `rules.TERMINAL_STATUSES`
    en vez de abrir una constante paralela: agregar un estado terminal tiene
    que ALCANZAR.

    Con la lista escrita a mano —incluso con los tres estados de hoy
    completos— el estado inventado se cuela y el abono se registra contra un
    contrato que no debe moverse.
    """
    inventado = "cancelled_by_court"
    monkeypatch.setattr(
        rules, "TERMINAL_STATUSES", frozenset(rules.TERMINAL_STATUSES | {inventado})
    )

    error = await _abonar(monkeypatch, status=inventado)

    assert error.code == "CONTRACT_CLOSED", (
        "La puerta de los abonos no deriva de `rules.TERMINAL_STATUSES`: un estado "
        f"terminal nuevo ({inventado}) admite abonos."
    )
