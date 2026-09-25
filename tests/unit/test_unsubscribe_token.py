"""El token del enlace de baja (docs/NOTIFICACIONES.md §9.2-e, §17).

Es lo único que protege un endpoint público que escribe en la ficha de un
cliente: tiene que ser imposible de fabricar sin el secreto, y tiene que
seguir sirviendo meses después (un correo viejo en la bandeja sigue teniendo
su enlace de salida).
"""

from uuid import uuid4

import pytest

from app.core.settings import get_settings
from app.modules.notifications import unsubscribe


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_LINK_SECRET", "un-secreto-de-prueba-suficientemente-largo")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com/")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_round_trip(secret: None) -> None:
    company_id, customer_id = uuid4(), uuid4()
    token = unsubscribe.make_token(company_id=company_id, customer_id=customer_id)
    assert unsubscribe.read_token(token) == (company_id, customer_id)
    # Va en una ruta: nada que haya que escapar.
    assert all(c.isalnum() or c in "-_." for c in token)


def test_a_tampered_token_is_rejected(secret: None) -> None:
    token = unsubscribe.make_token(company_id=uuid4(), customer_id=uuid4())
    body, sig = token.split(".")
    # Otro cliente con la firma del primero: el caso que importa.
    other = unsubscribe.make_token(company_id=uuid4(), customer_id=uuid4()).split(".")[0]
    assert unsubscribe.read_token(f"{other}.{sig}") is None
    # Se altera el PRIMER carácter: en 16 bytes el último carácter base64
    # lleva bits de relleno, y cambiarlo puede decodificar a lo mismo.
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert unsubscribe.read_token(f"{body}.{flipped}") is None
    for garbage in ("", "x", "a.b", "....", token + "x", "1" + token):
        assert unsubscribe.read_token(garbage) is None


def test_a_token_signed_with_another_secret_is_rejected(
    secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = unsubscribe.make_token(company_id=uuid4(), customer_id=uuid4())
    monkeypatch.setenv("NOTIFICATIONS_LINK_SECRET", "otro-secreto-de-prueba-igual-de-largo-xx")
    get_settings.cache_clear()
    assert unsubscribe.read_token(token) is None


def test_without_secret_nothing_is_signed_and_nothing_is_accepted(
    secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un HMAC con clave vacía lo firma cualquiera. Sin secreto no hay enlace,
    y un endpoint público que aceptara tokens sin secreto dejaría dar de baja
    a cualquier cliente de cualquier empresa."""
    token = unsubscribe.make_token(company_id=uuid4(), customer_id=uuid4())
    monkeypatch.setenv("NOTIFICATIONS_LINK_SECRET", "")
    get_settings.cache_clear()
    assert unsubscribe.read_token(token) is None
    with pytest.raises(unsubscribe.LinkNotConfigured):
        unsubscribe.make_token(company_id=uuid4(), customer_id=uuid4())


def test_link_points_to_the_front_page_not_to_the_api(secret: None) -> None:
    """El enlace abre una PÁGINA que pregunta; la baja la hace un POST desde
    ahí. Nunca un enlace que dé de baja al abrirse (§17)."""
    company_id, customer_id = uuid4(), uuid4()
    link = unsubscribe.unsubscribe_link(company_id=company_id, customer_id=customer_id)
    assert link.startswith("https://app.example.com/baja/")
    assert "//baja" not in link
    assert "/api/" not in link
    token = link.rsplit("/", 1)[1]
    assert unsubscribe.read_token(token) == (company_id, customer_id)


def test_link_needs_the_front_url(secret: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", "")
    get_settings.cache_clear()
    with pytest.raises(unsubscribe.LinkNotConfigured):
        unsubscribe.unsubscribe_link(company_id=uuid4(), customer_id=uuid4())


def test_mask_email() -> None:
    assert unsubscribe.mask_email("juana.perez@gmail.com") == "j•••@gmail.com"
    assert unsubscribe.mask_email("a@b.co") == "a•••@b.co"
    assert unsubscribe.mask_email(None) is None
    assert unsubscribe.mask_email("   ") is None
    assert unsubscribe.mask_email("sin-arroba") == "s•••"
