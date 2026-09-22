"""El invariante que F21-10 rompió: la consulta que alimenta el job nocturno
(`repository.list_active_contracts_for_recompute`) NO puede traer contratos en
un estado terminal.

Durante once días ese filtro fue una lista negra escrita a mano
(`status not in ('paid', 'auctioned')`) que quedó desincronizada de
`rules.TERMINAL_STATUSES` cuando `superseded` entró en 00051: el job tomaba los
contratos ya reemplazados por una ampliación y los recalculaba como si siguieran
vivos.

Por eso estos tests NO repiten la lista de estados terminales — derivarla de la
constante es justo lo que se está probando. El segundo test inventa un estado
terminal nuevo y exige que la consulta lo excluya sin que nadie haya tocado el
SQL: con la lista a mano (vieja o nueva, aunque hoy esté completa) falla.
"""

import re
from datetime import date
from typing import Any

import pytest

from app.modules.contracts import repository, rules


class _FakeResult:
    def all(self) -> list[Any]:
        return []


class _SesionQueSoloEspia:
    """Sesión de mentira: no toca Postgres, solo guarda qué se iba a ejecutar.

    El invariante es de la CONSULTA, no de la base — verificarlo sin Postgres
    hace que este test corra siempre, también donde la suite de integración se
    salta por falta de Docker.
    """

    def __init__(self) -> None:
        self.statement: Any = None
        self.params: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.statement = statement
        self.params = params
        return _FakeResult()


async def _estados_que_la_consulta_excluye() -> set[str]:
    """Corre la consulta contra la sesión espía y devuelve los estados que su
    `status not in ...` deja afuera.

    Entiende las dos formas posibles a propósito: el parámetro ligado (lo que
    hace el código arreglado) y la lista literal dentro del SQL (lo que hacía el
    código viejo). Así, con el código viejo el test falla por la aserción —que
    dice cuál estado se coló— y no por un error de plomería.
    """
    db = _SesionQueSoloEspia()
    await repository.list_active_contracts_for_recompute(db)  # type: ignore[arg-type]

    sql = " ".join(str(db.statement).split())
    match = re.search(r"status\s+not\s+in\s+(?P<clausula>:\w+|\([^)]*\))", sql)
    assert match is not None, f"La consulta del job ya no filtra por `status not in`: {sql}"

    clausula = match.group("clausula")
    # SQLAlchemy renderiza un `bindparam(expanding=True)` como
    # `(__[POSTCOMPILE_nombre])` hasta que lo ejecuta de verdad.
    parametro = re.fullmatch(r":(\w+)|\(__\[POSTCOMPILE_(\w+)\]\)", clausula)
    if parametro is not None:
        nombre = parametro.group(1) or parametro.group(2)
        valores = (db.params or {}).get(nombre)
        assert valores is not None, f"Falta el parámetro `{nombre}` al ejecutar la consulta"
        return {str(v) for v in valores}
    return set(re.findall(r"'([^']*)'", clausula))


async def test_la_consulta_excluye_exactamente_los_estados_terminales() -> None:
    """Ni de menos (el bug de F21-10) ni de más (excluir un estado vivo dejaría
    contratos sin recalcular para siempre, y su ausencia es silenciosa)."""
    assert await _estados_que_la_consulta_excluye() == set(rules.TERMINAL_STATUSES)


async def test_un_estado_terminal_nuevo_queda_excluido_sin_tocar_la_consulta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El invariante de verdad: agregar un estado a `TERMINAL_STATUSES` basta.

    Si mañana aparece un cuarto estado terminal y alguien se olvida de la
    consulta, esto falla acá y no once noches después en producción.
    """
    inventado = "estado_terminal_inventado"
    monkeypatch.setattr(
        rules, "TERMINAL_STATUSES", frozenset(rules.TERMINAL_STATUSES | {inventado})
    )

    excluidos = await _estados_que_la_consulta_excluye()
    assert inventado in excluidos, (
        "La consulta del job no excluyó un estado terminal nuevo: sigue atada a una "
        f"lista propia ({sorted(excluidos)}) en vez de a rules.TERMINAL_STATUSES."
    )


async def test_compute_status_y_la_consulta_leen_la_misma_constante(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La guarda de `compute_status` era lo ÚNICO que protegía cuando la lista
    se desincronizó — y no protegió, porque la imagen del job era vieja. Las dos
    defensas tienen que salir de la misma fuente, no parecerse."""
    inventado = "estado_terminal_inventado"
    monkeypatch.setattr(
        rules, "TERMINAL_STATUSES", frozenset(rules.TERMINAL_STATUSES | {inventado})
    )

    estado, _ = rules.compute_status(
        current_status=inventado,
        interest_paid_until=date(2020, 1, 1),  # años sin pagar
        arrears_window_months=4,
        extension_months=1,
        extension_ends_at=None,
        today=date(2026, 9, 21),
    )
    assert estado == inventado
    assert inventado in await _estados_que_la_consulta_excluye()
