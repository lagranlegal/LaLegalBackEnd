"""Reglas puras sobre el cuerpo de una plantilla (F8-01/03/11)."""

from app.modules.company.template_body import (
    es_documento_valido,
    faltantes_para_activar,
    tiene_contenido,
)


def _doc(*nodos: dict) -> dict:
    return {"type": "doc", "content": list(nodos)}


def test_documento_valido_exige_doc_y_nodos_con_forma() -> None:
    assert es_documento_valido(_doc())
    assert es_documento_valido({"type": "doc"})
    assert not es_documento_valido({})
    assert not es_documento_valido({"content": [1, 2]})
    assert not es_documento_valido(_doc({"type": "text", "text": 5}))
    assert not es_documento_valido(_doc({"type": "paragraph", "content": {"a": 1}}))
    assert not es_documento_valido(_doc({"sin": "tipo"}))


def test_documento_demasiado_profundo_no_es_valido() -> None:
    nodo: dict = {"type": "text", "text": "x"}
    for _ in range(60):
        nodo = {"type": "paragraph", "content": [nodo]}
    assert not es_documento_valido(_doc(nodo))


def test_vacio_es_lo_que_no_imprime_nada() -> None:
    assert not tiene_contenido(_doc())
    assert not tiene_contenido(_doc({"type": "paragraph"}))
    assert not tiene_contenido(
        _doc({"type": "paragraph", "content": [{"type": "text", "text": " \n "}]})
    )
    assert not tiene_contenido(_doc({"type": "mergeField", "attrs": {"key": ""}}))
    assert not tiene_contenido(_doc({"type": "hardBreak"}))
    assert tiene_contenido(_doc({"type": "paragraph", "content": [{"type": "text", "text": "x"}]}))
    assert tiene_contenido(_doc({"type": "mergeField", "attrs": {"key": "fecha_hoy"}}))
    assert tiene_contenido(_doc({"type": "itemsTableBlock"}))


def test_minimos_del_contrato() -> None:
    completo = _doc(
        {"type": "mergeField", "attrs": {"key": "cliente.nombre"}},
        {"type": "itemsTableBlock"},
        {"type": "signatureBlock"},  # sin attrs = variante `cliente` (default del nodo)
    )
    assert faltantes_para_activar("contract", completo) == []
    solo_empresa = _doc(
        {"type": "mergeField", "attrs": {"key": "cliente.nombre"}},
        {"type": "itemsTableBlock"},
        {"type": "signatureBlock", "attrs": {"variant": "empresa"}},
    )
    assert faltantes_para_activar("contract", solo_empresa) == ["signatureBlock:cliente"]
    assert faltantes_para_activar("settlement", _doc()) == []
