"""El armado del `to_tsquery` de prefijo (`app/common/search.py`).

Lo que cubre es lo que rompió en producción: un buscador que solo encontraba
con la palabra completa, y un `to_tsquery` que puede reventar con 500 si le
llega un signo de puntuación.
"""

import re

import pytest

from app.common.search import MIN_SEARCH_CHARS, name_clauses, prefix_tsquery


class TestPrefixTsquery:
    def test_una_palabra_lleva_el_operador_de_prefijo(self) -> None:
        """Es el arreglo entero: "mate" tiene que poder encontrar a "Mateo"."""
        assert prefix_tsquery("mate") == "mate:*"

    def test_todas_las_palabras_quedan_abiertas(self) -> None:
        """No solo la última. En un buscador que filtra mientras se escribe,
        quien teclea "jara mat" tiene las DOS a medias — y con la última sola
        "jara mateo" no encontraba a Mateo Jaramillo, porque "jara" tenía que
        coincidir exacto contra el lexema "jaramill"."""
        assert prefix_tsquery("jara mateo") == "jara:* & mateo:*"

    def test_los_espacios_de_mas_no_producen_lexemas_vacios(self) -> None:
        """Un `to_tsquery` con `& &` es un SyntaxError de Postgres, o sea un
        500 por teclear dos espacios."""
        assert prefix_tsquery("  mateo   jara  ") == "mateo:* & jara:*"

    @pytest.mark.parametrize("q", ["", "   ", "!!!", "&|()", " - "])
    def test_sin_lexemas_devuelve_none_en_vez_de_una_consulta_vacia(self, q: str) -> None:
        """`None` obliga a quien llama a caer al `ilike`. Con `''`, Postgres
        no coincide con NADA y el usuario ve "sin resultados" creyendo que el
        cliente no existe."""
        assert prefix_tsquery(q) is None

    @pytest.mark.parametrize(
        "q",
        ["mateo & jara", "mateo|jara", "(mateo)", "mateo:*", "o'brien", "mateo!", "<->", "a:*|b"],
    )
    def test_la_sintaxis_del_usuario_nunca_llega_a_postgres(self, q: str) -> None:
        """Un error de dedo con `&`, `|`, `(` o `:` sería un SyntaxError de
        Postgres — o sea un 500 en un buscador. Los signos se descartan como
        separadores, así que lo que sale SIEMPRE tiene la forma que este
        módulo arma: palabras unidas por ` & `, y `:*` solo al final."""
        resultado = prefix_tsquery(q)
        if resultado is None:
            return
        assert re.fullmatch(r"\w+:\*( & \w+:\*)*", resultado), resultado

    def test_las_tildes_y_la_enie_sobreviven(self) -> None:
        """`\\w` con `re.UNICODE` — si "Muñoz" se partiera en "mu" y "oz", la
        búsqueda encontraría cualquier cosa menos a Muñoz."""
        assert prefix_tsquery("muñoz josé") == "muñoz:* & josé:*"


class TestNameClauses:
    def test_siempre_hay_respaldo_de_ilike(self) -> None:
        """Las stopwords del español son lexemas VACÍOS: sin el `ilike`,
        "de la" (parte de "De la Cruz") no encontraría a nadie."""
        clauses, params = name_clauses("full_name", "de la", prefix="name")
        assert "public.f_unaccent(full_name) ilike public.f_unaccent(:name_like)" in clauses
        assert params["name_like"] == "%de la%"

    def test_con_lexemas_van_las_dos_clausulas(self) -> None:
        clauses, params = name_clauses("cu.full_name", "mate", prefix="name")
        assert len(clauses) == 2
        assert clauses[0] == (
            "to_tsvector('spanish', public.f_unaccent(cu.full_name)) "
            "@@ to_tsquery('spanish', public.f_unaccent(:name_tsq))"
        )
        assert params["name_tsq"] == "mate:*"

    def test_el_unaccent_se_aplica_a_LOS_DOS_lados(self) -> None:
        """Normalizar solo la columna compararía un texto sin eñes contra uno
        con eñes: no encontraría nada y parecería que el arreglo no sirvió."""
        clauses, _ = name_clauses("full_name", "munoz", prefix="name")
        for clausula in clauses:
            assert clausula.count("f_unaccent") == 2, clausula

    def test_la_expresion_es_LA_MISMA_del_indice(self) -> None:
        """`ix_customer_name_unaccent` (00056) está creado sobre
        `to_tsvector('spanish', public.f_unaccent(full_name))`. Si esta
        cláusula deja de coincidir carácter por carácter, Postgres no usa el
        índice y no avisa: la búsqueda pasa a seq scan en silencio, que es la
        peor forma de perderlo."""
        clauses, _ = name_clauses("full_name", "mate", prefix="name")
        assert clauses[0].startswith("to_tsvector('spanish', public.f_unaccent(full_name))")

    def test_sin_lexemas_queda_solo_el_ilike_y_ningun_parametro_huerfano(self) -> None:
        """Un `:name_tsq` en el SQL sin su valor en `params` es un error de
        vinculación de SQLAlchemy, no un resultado vacío."""
        clauses, params = name_clauses("full_name", "...", prefix="name")
        assert clauses == ["public.f_unaccent(full_name) ilike public.f_unaccent(:name_like)"]
        assert "name_tsq" not in params

    def test_el_prefijo_aisla_los_parametros(self) -> None:
        """Dos búsquedas por nombre en la misma consulta (cliente y producto)
        se pisarían los `:name_like` si el prefijo no los separara."""
        _, a = name_clauses("cu.full_name", "mate", prefix="cliente")
        _, b = name_clauses("p.name", "cade", prefix="producto")
        assert set(a) & set(b) == set()


def test_el_piso_es_de_tres_caracteres() -> None:
    """Lo que pidió el cliente el 11/09/2026. Vale la pena fijarlo: bajarlo a
    1 devuelve el bug del documento que hacía aparecer contratos ajenos, y
    subirlo devuelve el "solo filtra desde la quinta letra"."""
    assert MIN_SEARCH_CHARS == 3
